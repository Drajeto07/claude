"""One shape for every error the API returns (корекции.docx §49):

    {"code": "not_found", "message": "Document not found", "details": null, "request_id": "4f0c..."}

`message` is written for people and safe to show as it is; `code` is for code to
branch on; `details` holds anything structured (the fields a validation error
names, the conflicts formatting found, the revision a write collided with).
Every response also carries its request id in the X-Request-ID header -- the
caller's own when it sends a sane one, a new one otherwise -- so what a user
reports can be found in the server's log."""

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models.base import ApiModel

logger = logging.getLogger(__name__)


class ApiErrorOut(ApiModel):
    """The body of every error response."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None

REQUEST_ID_HEADER = "X-Request-ID"
# The id of the request being handled, for error bodies and log lines.
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
_SANE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_CODES = {
    400: "bad_request",
    401: "not_signed_in",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    413: "too_large",
    415: "unsupported_media_type",
    422: "invalid_request",
    429: "too_many_requests",
    500: "internal_error",
    503: "unavailable",
}
_MESSAGES = {
    404: "Not found.",
    405: "That isn't allowed here.",
    422: "Some of what was sent isn't valid.",
    500: "Something went wrong on our side. Please try again.",
}


def error_response(
    status: int, message: str, *, code: str | None = None, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code or _CODES.get(status, "error"),
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": current_request_id.get(),
        },
        headers=headers,
    )


def request_id_for(request: Request) -> str:
    """The caller's X-Request-ID when it looks like an id, else a new one."""
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    return incoming if _SANE_ID.match(incoming) else uuid.uuid4().hex


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # HTTPException(detail="text"), or detail={"code": ..., "message": ..., anything else -> details}.
    if isinstance(exc.detail, dict):
        extra = {key: value for key, value in exc.detail.items() if key not in ("code", "message")}
        message = exc.detail.get("message") or _MESSAGES.get(exc.status_code, "The request failed.")
        return error_response(exc.status_code, message, code=exc.detail.get("code"), details=extra or None, headers=exc.headers)
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else _MESSAGES.get(exc.status_code, "The request failed.")
    return error_response(exc.status_code, message, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Where and what, not the submitted values (a password field's value would come back).
    errors = [{"loc": list(error.get("loc", ())), "msg": error.get("msg", ""), "type": error.get("type", "")} for error in exc.errors()]
    return error_response(422, _MESSAGES[422], details={"errors": errors})


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    _document_errors(app)


_FASTAPI_ERROR_REF = "#/components/schemas/HTTPValidationError"
_ERROR_REF = "#/components/schemas/ApiError"


def _replace_ref(node: Any, old: str, new: str) -> Any:
    if isinstance(node, dict):
        return {key: new if key == "$ref" and value == old else _replace_ref(value, old, new) for key, value in node.items()}
    if isinstance(node, list):
        return [_replace_ref(item, old, new) for item in node]
    return node


def _document_errors(app: FastAPI) -> None:
    """The OpenAPI schema (and so the frontend's generated types) shows errors as
    they are sent: FastAPI documents its own {"detail": [...]} for a 422, which
    this API never returns."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            schemas = schema.setdefault("components", {}).setdefault("schemas", {})
            schemas.pop("HTTPValidationError", None)
            schemas.pop("ValidationError", None)
            schemas["ApiError"] = ApiErrorOut.model_json_schema(mode="serialization")
            app.openapi_schema = _replace_ref(schema, _FASTAPI_ERROR_REF, _ERROR_REF)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


async def unexpected_error(request: Request) -> JSONResponse:
    """What the caller gets for an exception nothing handled: never its details,
    which go to the log with the request id instead."""
    logger.exception("Unhandled error in %s %s (request %s)", request.method, request.url.path, current_request_id.get())
    return error_response(500, _MESSAGES[500])
