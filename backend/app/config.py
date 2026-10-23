import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def load_env_file():
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


@dataclass(frozen=True)
class Settings:
    database_url: str
    supabase_url: str
    service_key: str
    bucket: str
    jwt_secret: str
    cookie_secure: bool
    cookie_samesite: str
    session_hours: int
    allowed_origins: tuple
    public_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str


@lru_cache
def get_settings() -> Settings:
    def env(name, default=""):
        return os.environ.get(name, default).strip()

    missing = [
        name
        for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "JWT_SECRET")
        if not env(name)
    ]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    if len(env("JWT_SECRET")) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters long.")
    origins = tuple(o.strip().rstrip("/") for o in env("ALLOWED_ORIGINS").split(",") if o.strip())
    return Settings(
        database_url=env("DATABASE_URL"),
        supabase_url=env("SUPABASE_URL").rstrip("/"),
        service_key=env("SUPABASE_SERVICE_ROLE_KEY"),
        bucket=env("STORAGE_BUCKET", "documents"),
        jwt_secret=env("JWT_SECRET"),
        cookie_secure=env("COOKIE_SECURE", "true").lower() != "false",
        cookie_samesite=env("COOKIE_SAMESITE", "lax").lower(),
        session_hours=int(env("SESSION_HOURS", "12")),
        allowed_origins=origins,
        public_base_url=env("PUBLIC_BASE_URL").rstrip("/"),
        smtp_host=env("SMTP_HOST"),
        smtp_port=int(env("SMTP_PORT", "587")),
        smtp_user=env("SMTP_USER"),
        smtp_password=env("SMTP_PASSWORD"),
        smtp_from=env("SMTP_FROM"),
    )
