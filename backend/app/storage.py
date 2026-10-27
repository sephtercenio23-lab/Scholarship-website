import re
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .catalog import ALL_DOCUMENT_KEYS
from .config import get_settings

PATH_PATTERN = re.compile(
    r"^(?P<user>[0-9a-fA-F-]{36})/(?P<app>[0-9a-fA-F-]{36})/(?P<key>"
    + "|".join(ALL_DOCUMENT_KEYS)
    + r")/(?P<file>[0-9a-fA-F-]{36}_[A-Za-z0-9._-]{1,200})$"
)

SIGNATURE_BYTES = 16
FILE_SIGNATURES = {
    "pdf": (b"%PDF-", "application/pdf"),
    "png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    "jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}
EXTENSION_KINDS = {".pdf": "pdf", ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}


def file_extension(name):
    text = str(name or "")
    if "." not in text:
        return ""
    return "." + text.rsplit(".", 1)[-1].lower()


def detect_file_kind(head):
    for kind, (signature, _mime) in FILE_SIGNATURES.items():
        if head.startswith(signature):
            return kind
    return ""


def file_mime_type(kind):
    return FILE_SIGNATURES[kind][1] if kind in FILE_SIGNATURES else ""


def parse_path(path):
    match = PATH_PATTERN.match(str(path or ""))
    if not match:
        raise HTTPException(status_code=400, detail="The document path is invalid.")
    return match.groupdict()


def _headers():
    key = get_settings().service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _base():
    return f"{get_settings().supabase_url}/storage/v1"


def _absolute(url):
    if url.startswith("http"):
        return url
    if url.startswith("/storage/v1"):
        return get_settings().supabase_url + url
    return _base() + url


def _unavailable():
    return HTTPException(status_code=502, detail="Secure storage is unavailable. Please try again.")


def signed_upload_url(path):
    bucket = get_settings().bucket
    try:
        response = httpx.post(
            f"{_base()}/object/upload/sign/{bucket}/{quote(path, safe='/')}",
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return _absolute(response.json()["url"])
    except (httpx.HTTPError, KeyError, ValueError):
        raise _unavailable()


def signed_download_url(path, expires_in=300):
    bucket = get_settings().bucket
    try:
        response = httpx.post(
            f"{_base()}/object/sign/{bucket}/{quote(path, safe='/')}",
            headers=_headers(),
            json={"expiresIn": expires_in},
            timeout=15,
        )
        response.raise_for_status()
        return _absolute(response.json()["signedURL"])
    except (httpx.HTTPError, KeyError, ValueError):
        raise _unavailable()


def object_info(path):
    bucket = get_settings().bucket
    folder, _, name = path.rpartition("/")
    try:
        response = httpx.post(
            f"{_base()}/object/list/{bucket}",
            headers=_headers(),
            json={"prefix": folder, "limit": 100, "search": name},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
    except (httpx.HTTPError, ValueError):
        raise _unavailable()
    for item in items:
        if item.get("name") == name:
            metadata = item.get("metadata") or {}
            return {"size": metadata.get("size"), "mimetype": metadata.get("mimetype")}
    return None


def object_head_bytes(path, length=SIGNATURE_BYTES):
    bucket = get_settings().bucket
    try:
        with httpx.stream(
            "GET",
            f"{_base()}/object/{bucket}/{quote(path, safe='/')}",
            headers={**_headers(), "Range": f"bytes=0-{length - 1}"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            head = b""
            for chunk in response.iter_bytes():
                head += chunk
                if len(head) >= length:
                    break
            return head[:length]
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return None
        raise _unavailable()
    except (httpx.HTTPError, ValueError):
        raise _unavailable()


def list_object_paths(prefix=""):
    """Recursively list every object path in the bucket under prefix."""
    bucket = get_settings().bucket
    found = []

    def walk(folder):
        offset = 0
        while True:
            try:
                response = httpx.post(
                    f"{_base()}/object/list/{bucket}",
                    headers=_headers(),
                    json={"prefix": folder, "limit": 1000, "offset": offset},
                    timeout=20,
                )
                response.raise_for_status()
                items = response.json()
            except (httpx.HTTPError, ValueError):
                raise _unavailable()
            if not items:
                break
            for item in items:
                name = item.get("name") or ""
                path = f"{folder}{name}" if folder else name
                if item.get("metadata"):
                    found.append(path)
                else:
                    walk(path + "/")
            if len(items) < 1000:
                break
            offset += len(items)

    walk(prefix)
    return found


def remove_objects(paths):
    paths = [path for path in paths if path]
    if not paths:
        return
    bucket = get_settings().bucket
    try:
        response = httpx.request(
            "DELETE",
            f"{_base()}/object/{bucket}",
            headers=_headers(),
            json={"prefixes": paths},
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        raise _unavailable()
