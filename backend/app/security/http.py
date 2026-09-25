"""What every request and response goes through (корекции.docx §33): a cap on
how much of a request body the API takes in at all, and the security headers
on every response."""

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response


class RequestSizeLimit:
    """Refuses a request body over `max_bytes` with 413: by its Content-Length
    before anything is read, or -- when it sends none -- as soon as the bytes
    received pass the cap, so an oversized upload is never spooled to disk or
    parsed. Placed inside the request-id and CORS middleware, so the refusal
    carries both."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _too_large(self) -> str:
        return f"The request is larger than the {self.max_bytes // (1024 * 1024)} MB the server accepts."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await error_response(413, self._too_large(), code="too_large")(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the app while it reads the body; answered by the error handlers.
                    raise HTTPException(status_code=413, detail=self._too_large())
            return message

        await self.app(scope, limited_receive, send)


# The API answers data, never pages: nothing it sends may run as a page, be
# framed, or be sniffed as another type. /docs (FastAPI's own page) is left alone.
API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def secure_headers(path: str, hsts_seconds: int) -> dict[str, str]:
    headers = dict(API_HEADERS) if path.startswith("/api/") else {"X-Content-Type-Options": "nosniff"}
    if hsts_seconds > 0:
        headers["Strict-Transport-Security"] = f"max-age={hsts_seconds}; includeSubDomains"
    return headers
