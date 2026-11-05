"""One error format for the whole API (Phase 2 design):  {"error": {"code", "message", "details"}}."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT",
         422: "VALIDATION_ERROR", 503: "UNAVAILABLE"}


def error_body(status: int, message: str, details=None) -> dict:
    return {"error": {"code": CODES.get(status, "ERROR"), "message": message, "details": details}}


def register(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(error_body(exc.status_code, str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
                   for e in jsonable_encoder(exc.errors())]
        return JSONResponse(error_body(422, "The request is not valid", details), status_code=422)
