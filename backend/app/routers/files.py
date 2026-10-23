from fastapi import APIRouter, HTTPException, Query, Request

from .. import storage
from ..catalog import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, MAX_FILE_BYTES
from ..db import transaction
from ..deps import current_user
from ..schemas import PathsIn, UploadUrlIn
from ..security import bad_request

router = APIRouter(prefix="/files")

MAX_PATHS = 20


@router.post("/upload-url")
def upload_url(body: UploadUrlIn, request: Request):
    parts = storage.parse_path(body.path)
    if body.applicationId.lower() != parts["app"].lower() or body.requirementKey != parts["key"]:
        raise bad_request("The document upload path is invalid.")
    if not body.fileName.lower().endswith(ALLOWED_EXTENSIONS) or body.contentType not in ALLOWED_MIME_TYPES:
        raise bad_request("Unsupported file type. Accepted: .pdf, .jpg, .jpeg, .png")
    if body.sizeBytes <= 0 or body.sizeBytes > MAX_FILE_BYTES:
        raise bad_request("File is too large. Maximum size is 5MB.")
    with transaction() as conn:
        user = current_user(conn, request, "student")
        if parts["user"].lower() != str(user["id"]).lower():
            raise HTTPException(status_code=403, detail="You do not have permission to upload this file.")
        existing = conn.execute(
            "select student_id, status, duty_hours from applications where id = %s", (parts["app"],)
        ).fetchone()
        if parts["key"] == "terminalReport":
            if (
                not existing
                or str(existing["student_id"]) != str(user["id"])
                or existing["status"] != "Approved"
                or existing["duty_hours"] != 80
            ):
                raise bad_request("The terminal report is not available for this application.")
        elif existing:
            raise bad_request("This application was already submitted.")
    return {"signedUrl": storage.signed_upload_url(body.path), "path": body.path}


@router.get("/download-url")
def download_url(request: Request, path: str = Query(...)):
    parts = storage.parse_path(path)
    with transaction() as conn:
        user = current_user(conn, request)
        row = conn.execute(
            """
            select a.student_id
            from application_documents d
            join applications a on a.id = d.application_id
            where d.path = %s and a.deleted_at is null
            """,
            (path,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")
        if user["role"] == "student" and str(row["student_id"]) != str(user["id"]):
            raise HTTPException(status_code=404, detail="Document not found.")
    return {"signedUrl": storage.signed_download_url(path), "path": path, "key": parts["key"]}


@router.post("/discard")
def discard_files(body: PathsIn, request: Request):
    if len(body.paths) > MAX_PATHS:
        raise bad_request("Too many files.")
    for path in body.paths:
        storage.parse_path(path)
    with transaction() as conn:
        user = current_user(conn, request, "student")
        removable = []
        for path in body.paths:
            if storage.parse_path(path)["user"].lower() != str(user["id"]).lower():
                continue
            if conn.execute("select 1 from application_documents where path = %s", (path,)).fetchone():
                continue
            removable.append(path)
    storage.remove_objects(removable)
    return {"deleted": len(removable)}


@router.post("/delete")
def delete_files(body: PathsIn, request: Request):
    if len(body.paths) > MAX_PATHS:
        raise bad_request("Too many files.")
    for path in body.paths:
        storage.parse_path(path)
    with transaction() as conn:
        current_user(conn, request, "staff", "admin")
        removable = []
        for path in body.paths:
            row = conn.execute(
                """
                select 1
                from application_documents d
                join applications a on a.id = d.application_id
                where d.path = %s and a.deleted_at is not null
                """,
                (path,),
            ).fetchone()
            if row:
                removable.append(path)
    storage.remove_objects(removable)
    return {"deleted": len(removable)}
