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


def storage_origin():
    parsed = urlparse(settings.supabase_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://*.supabase.co"


def content_security_policy():
    origin = storage_origin()
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
            f"img-src 'self' data: blob: {origin}",
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com",
            f"connect-src 'self' {origin}",
            "frame-src 'self' blob:",
            "object-src 'self' blob:",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
        ]
    )


SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": content_security_policy(),
}


def with_security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if urlparse(origin).netloc != host and origin.rstrip("/") not in settings.allowed_origins:
                return with_security_headers(
                    JSONResponse(status_code=403, content={"detail": "Request origin is not allowed."})
                )
    response = await call_next(request)
    return with_security_headers(response)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    first = error.errors()[0] if error.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    message = f"Please check the submitted information ({field})." if field else "Please check the submitted information."
    return JSONResponse(status_code=422, content={"detail": message})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, error: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again."},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **SECURITY_HEADERS},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


for module in (auth, users, admin, audit, terms, applications, files, notifications):
    app.include_router(module.router, prefix="/api")
