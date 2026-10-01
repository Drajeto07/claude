import base64
import binascii

from app.models.document import WEB_IMAGE_TYPES, Document, Element, ElementType, walk_elements
from app.security import files as limits
from app.security.files import picture_problem
from app.services.asset_service import AssetService

_UNSTORABLE_IMAGE = "An inline image that isn't a valid PNG, JPEG, GIF, WebP or BMP was removed."


class PictureLimitError(Exception):
    """A change that would take a document's pictures past their number or their bytes
    (SEC-012). Nothing is stored; the API answers 413 "too_large", and the editor says
    why its save was refused."""


def _is_inline(element: Element) -> bool:
    image = element.image
    return element.type == ElementType.IMAGE and image is not None and not image.assetId and image.src.startswith("data:")


def _inline_sources(document: Document) -> list[str]:
    # Nested blocks too: a picture pasted into a table cell arrives the same way.
    return [element.image.src for element in walk_elements(document.elements) if _is_inline(element)]


def inline_image_bytes(document: Document) -> int:
    """About what the document's inline (data: URI) images take once moved into
    storage: base64 is a third larger than the bytes it encodes."""
    return sum(len(src.partition(",")[2]) * 3 // 4 for src in _inline_sources(document))


def stored_size(document: Document) -> int:
    """About what a new document takes once stored (usage_service.storage_bytes
    counts the same): its JSON without the inline images, plus the images."""
    return len(document.model_dump_json()) - sum(len(src) for src in _inline_sources(document)) + inline_image_bytes(document)


async def externalize_inline_images(document: Document, assets: AssetService, workspace_id: str) -> bool:
    """Moves every inline data: URI image into asset storage and points its
    element at the stored asset, so image bytes never sit in the document JSON
    or in undo snapshots -- at any depth: pictures inside table cells, list items
    and quotes too. An inline image that can't be decoded as a web image, or not
    safely (SEC-012), is removed and reported in unsupportedFeatures rather than
    kept as dead weight. PictureLimitError, before anything is stored, when the
    document's pictures would pass their number or their bytes.
    Returns whether the document changed."""
    changed = False
    # Every inline picture judged first, and the whole document's: nothing is stored
    # for a change that is refused.
    judged = {id(element): _judged(element.image.src) for element in walk_elements(document.elements) if _is_inline(element)}
    taken = [verdict for verdict in judged.values() if isinstance(verdict, tuple)]
    stored = [element.image.assetId for element in walk_elements(document.elements) if element.image and element.image.assetId]
    if len(stored) + len(taken) > limits.MAX_PICTURES:
        raise PictureLimitError(f"A document can hold at most {limits.MAX_PICTURES} pictures.")
    total = sum(len(data) for _, data in taken) + await assets.total_size(workspace_id, stored)
    if total > limits.MAX_PICTURE_TOTAL_BYTES:
        raise PictureLimitError(f"A document's pictures can take at most {limits.MAX_PICTURE_TOTAL_BYTES // limits.MB} MB in all.")

    async def keep(elements: list[Element]) -> list[Element]:
        nonlocal changed
        kept = []
        for element in elements:
            await nested(element)
            if not _is_inline(element):
                kept.append(element)
                continue
            changed = True
            verdict = judged[id(element)]
            if isinstance(verdict, str):
                if verdict not in document.unsupportedFeatures:
                    document.unsupportedFeatures.append(verdict)
                continue
            content_type, data = verdict
            asset = await assets.store(workspace_id, data, content_type, document_id=document.id)
            element.image.assetId, element.image.src = asset.id, ""
            kept.append(element)
        if len(kept) != len(elements):
            for index, element in enumerate(kept):
                element.order = index
        return kept

    async def nested(element: Element) -> None:
        if element.children:
            element.children = await keep(element.children) or None
        for item in element.listItems or []:
            if item.blocks:
                item.blocks = await keep(item.blocks) or None
        if element.table:
            for row in element.table.rows:
                for cell in row.cells:
                    if cell.blocks:
                        cell.blocks = await keep(cell.blocks) or None

    document.elements = await keep(document.elements)
    return changed


def _judged(src: str) -> tuple[str, bytes] | str:
    """An inline picture's type and bytes, or why it can't be kept."""
    decoded = _decode_image_data_uri(src)
    if decoded is None:
        return _UNSTORABLE_IMAGE
    # Stored and later served under its type, so the bytes have to be that kind of image,
    # and one that can be decoded safely.
    problem = picture_problem(decoded[1], decoded[0])
    if problem is None:
        return decoded
    return _UNSTORABLE_IMAGE if problem.kind == "unreadable" else f"An inline image that {problem.reason} was removed."


def _decode_image_data_uri(src: str) -> tuple[str, bytes] | None:
    header, _, payload = src.partition(",")
    media_type = header.removeprefix("data:").split(";")[0].strip().lower()
    if media_type not in WEB_IMAGE_TYPES or ";base64" not in header.lower():
        return None
    try:
        data = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None
    return (media_type, data) if data else None
