"""How a stored or generated file is sent to a browser (STOR-001, brief §70).

Every file leaves the API through `file_response`, so each route gets the same
guarantees without repeating them: only a type this app produces is sent as
itself (anything else, which the stored row or job result should never hold,
goes out as an opaque download), `nosniff`, a policy that lets nothing in the
file run, and a Content-Disposition.

A file larger than one hosted response may carry (B-035B: Vercel stops a function's
response body at 4.5 MB -- a 500 FUNCTION_RESPONSE_PAYLOAD_TOO_LARGE -- and lets a
streamed one through) leaves as a stream of parts instead of one body: the same bytes,
the same headers, no Content-Length (chunked), so a download cut off on the way is an
incomplete download to the browser, never a short file taken as whole. Everything is
checked and the bytes are complete before the first part goes: a refusal or an error
is still a plain HTTP answer. Smaller files leave as before, in one body."""

from collections.abc import AsyncIterator

from fastapi import Response
from fastapi.responses import StreamingResponse

from app.export.filenames import content_disposition
from app.security.files import CONTENT_TYPES

# What the app itself stores or generates: pictures, the Word file kept as the
# original and exported, PDF exports, and the ZIPs of a batch export or a PDF split
# (FEAT-002, PDF-020) -- always a download.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})
ZIP_TYPE = "application/zip"
SERVED_TYPES = IMAGE_TYPES | frozenset(CONTENT_TYPES.values()) | {ZIP_TYPE}
OPAQUE_TYPE = "application/octet-stream"
# Up to this many bytes a file leaves in one body, as it always did (the owner's 4.00 MB download works on the
# Preview); above it, streamed. Under Vercel's 4,500,000 bytes, with room for the headers.
STREAM_ABOVE = 4_400_000
STREAM_PART = 256 * 1024


async def _parts(content: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(content), STREAM_PART):
        yield content[start : start + STREAM_PART]


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
    headers = {
        "Content-Disposition": disposition,
        "Cache-Control": cache,
        # The file is served from the API's origin: never let a browser reinterpret
        # its bytes as HTML or script, whatever they hold.
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    if len(content) > STREAM_ABOVE:
        return StreamingResponse(_parts(content), media_type=media_type, headers=headers)
    return Response(content=content, media_type=media_type, headers=headers)
