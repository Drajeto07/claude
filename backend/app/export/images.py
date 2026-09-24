import base64
import binascii
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
