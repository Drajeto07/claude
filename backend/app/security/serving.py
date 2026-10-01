"""How a stored or generated file is sent to a browser (STOR-001, brief §70).

Every file leaves the API through `file_response`, so each route gets the same
guarantees without repeating them: only a type this app produces is sent as
itself (anything else, which the stored row or job result should never hold,
goes out as an opaque download), `nosniff`, a policy that lets nothing in the
file run, and a Content-Disposition."""

from fastapi import Response

from app.export.filenames import content_disposition
from app.security.files import CONTENT_TYPES

# What the app itself stores or generates: pictures, the Word file kept as the
# original and exported, PDF exports.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})
SERVED_TYPES = IMAGE_TYPES | frozenset(CONTENT_TYPES.values())
OPAQUE_TYPE = "application/octet-stream"


def file_response(content: bytes, content_type: str, *, filename: str | None = None, cache: str = "private, no-store") -> Response:
    """`content` as a Response. A picture is shown in place (`inline`; the editor draws it
    in an <img>) unless a filename is given; everything else, and any type this app
    doesn't produce, is a download (`attachment`)."""
    media_type = content_type if content_type in SERVED_TYPES else OPAQUE_TYPE
    if media_type in IMAGE_TYPES and filename is None:
        disposition = "inline"
    elif filename is not None:
        disposition = content_disposition(filename)
    else:
        disposition = "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": cache,
            # The file is served from the API's origin: never let a browser reinterpret
            # its bytes as HTML or script, whatever they hold.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
