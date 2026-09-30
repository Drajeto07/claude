import base64
import binascii
import math
from collections.abc import Mapping

from app.models.document import ImageContent


def resolve_image_bytes(image: ImageContent, assets: Mapping[str, bytes]) -> bytes | None:
    """Bytes for an image element. `assets` must already be scoped to the
    requesting user, so a foreign assetId planted in a document resolves to
    nothing instead of leaking another workspace's image into an export."""
    if image.assetId:
        return assets.get(image.assetId)
    if image.src.startswith("data:"):
        try:
            return base64.b64decode(image.src.split(",", 1)[1], validate=True)
        except (IndexError, ValueError, binascii.Error):
            return None
    return None


def turned_box(width: float, height: float, rotation: float | None) -> tuple[float, float]:
    """The room a picture `width` by `height` takes turned `rotation` degrees
    (DOCX-018): its turned outline's, as Word lays a turned picture out."""
    if not rotation:
        return width, height
    angle = math.radians(rotation)
    across, down = abs(math.cos(angle)), abs(math.sin(angle))
    return width * across + height * down, width * down + height * across


def picture_width_cm(image: ImageContent, width_css: str, content_width_cm: float) -> float | None:
    """The width a picture is exported at (DOCX-018): its width rule's share of the
    text width -- or its own width from Word while the rule is still the share the
    importer made of it (to a tenth of a percent, parsers/docx.py), so an unchanged
    picture keeps its size exactly -- and without a rule, its own."""
    try:
        percent = float(width_css[:-1]) if width_css.endswith("%") else None
    except ValueError:
        percent = None
    if percent is None or content_width_cm <= 0:
        return image.widthCm
    own = image.widthCm
    if own and percent < 100 and round(own / content_width_cm * 100, 1) == round(percent, 1):
        return own
    return content_width_cm * percent / 100
