import base64
import binascii

from app.models.document import WEB_IMAGE_TYPES, Document, ElementType
from app.services.asset_service import AssetService

_UNSTORABLE_IMAGE = "An inline image that isn't a valid PNG, JPEG, GIF, WebP or BMP was removed."


def _inline_sources(document: Document) -> list[str]:
    return [
        element.image.src
        for element in document.elements
        if element.type == ElementType.IMAGE and element.image is not None and not element.image.assetId and element.image.src.startswith("data:")
    ]


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
    or in undo snapshots. An inline image that can't be decoded as a web image
    is removed and reported in unsupportedFeatures rather than kept as dead
    weight. Returns whether the document changed."""
    changed = False
    kept = []
    for element in document.elements:
        image = element.image
        if element.type != ElementType.IMAGE or image is None or image.assetId or not image.src.startswith("data:"):
            kept.append(element)
            continue
        changed = True
        decoded = _decode_image_data_uri(image.src)
        if decoded is None:
            if _UNSTORABLE_IMAGE not in document.unsupportedFeatures:
                document.unsupportedFeatures.append(_UNSTORABLE_IMAGE)
            continue
        content_type, data = decoded
        asset = await assets.store(workspace_id, data, content_type, document_id=document.id)
        image.assetId, image.src = asset.id, ""
        kept.append(element)

    if len(kept) != len(document.elements):
        for index, element in enumerate(kept):
            element.order = index
        document.elements = kept
    return changed


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
