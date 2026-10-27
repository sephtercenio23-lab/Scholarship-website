from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import admin, applications, audit, auth, files, notifications, terms, users

settings = get_settings()

app = FastAPI(title="Scholarship Application and Monitoring System", docs_url=None, redoc_url=None, openapi_url=None)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if urlparse(origin).netloc != host and origin.rstrip("/") not in settings.allowed_origins:
                return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed."})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    first = error.errors()[0] if error.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    message = f"Please check the submitted information ({field})." if field else "Please check the submitted information."
    return JSONResponse(status_code=422, content={"detail": message})


@app.get("/api/health")
def health():
    return {"status": "ok"}


for module in (auth, users, admin, audit, terms, applications, files, notifications):
    app.include_router(module.router, prefix="/api")
