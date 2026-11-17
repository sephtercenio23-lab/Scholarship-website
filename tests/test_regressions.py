import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://unused")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unused")
os.environ.setdefault("JWT_SECRET", "x" * 32)

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app.common import normalize_academic_year, parse_deadline_at, term_state
from backend.app.main import app
from backend.app.routers import applications, files, terms
from backend.app.schemas import ApplicationIn, DocumentIn, TermIn, UploadUrlIn
from backend.app.security import check_password, hash_password, verify_password
from backend.app.spreadsheet import build_xlsx
from backend.app.storage import detect_file_kind, looks_dangerous


@contextmanager
def transaction(conn):
    yield conn


class RegressionTests(unittest.TestCase):
    def test_health_and_request_validation(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
            self.assertEqual(client.post("/api/auth/login", json={}).status_code, 422)

    def test_term_year_and_deadline(self):
        for value in ("2026-2027", "2026/2027", "2026–2027"):
            self.assertEqual(normalize_academic_year(value), "2026–2027")
        with self.assertRaises(HTTPException):
            normalize_academic_year("2026-2028")
        self.assertEqual(parse_deadline_at("2026-11-03T08:00"), datetime(2026, 11, 3, tzinfo=timezone.utc))
        current = {"id": "a", "academic_year": "2026–2027", "trimester": "2nd Trimester"}
        previous = {"id": "b", "academic_year": "2026–2027", "trimester": "1st Trimester"}
        self.assertEqual(term_state(current, current), "Current")
        self.assertEqual(term_state(previous, current), "Past")

    def test_term_change_preserves_previous_applications(self):
        previous = {"id": uuid4(), "trimester": "1st Trimester", "academic_year": "2026–2027"}
        target = {"id": uuid4(), "trimester": "2nd Trimester", "academic_year": "2026–2027"}
        conn = Mock()
        conn.execute.side_effect = [Mock(), Mock(fetchone=Mock(return_value=target)), Mock(fetchone=Mock(return_value={"total": 3})), Mock(), Mock(), Mock(fetchone=Mock(return_value=target))]
        with patch.object(terms, "transaction", return_value=transaction(conn)), patch.object(terms, "current_user", return_value={}), patch.object(terms, "ensure_current_term", return_value=previous), patch.object(terms, "audit"):
            result = terms.set_current_term(TermIn(trimester="2nd Trimester", academicYear="2026–2027"), Mock())
        self.assertEqual(result["archived"], 3)
        self.assertFalse(any(call.args[0].strip().lower().startswith("delete ") for call in conn.execute.call_args_list))

    def test_password_validation_and_hash(self):
        check_password("Validpass1!")
        password_hash = hash_password("Validpass1!")
        self.assertTrue(verify_password("Validpass1!", password_hash))
        self.assertFalse(verify_password("Wrongpass1!", password_hash))
        with self.assertRaises(HTTPException):
            check_password("short")

    def test_empty_stored_document_rejected(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_grades.pdf"
        document = DocumentIn(name="grades.pdf", path=path, sizeBytes=12, mimeType="application/pdf")
        with patch.object(applications.storage, "object_info", return_value={"size": 0, "mimetype": "application/pdf"}):
            with self.assertRaises(HTTPException):
                applications.check_stored_document(user_id, app_id, "copyOfGrades", document)

    def test_deleted_application_cannot_request_terminal_upload(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        path = f"{user_id}/{app_id}/terminalReport/{file_id}_report.pdf"
        body = UploadUrlIn(path=path, applicationId=str(app_id), requirementKey="terminalReport", fileName="report.pdf", contentType="application/pdf", sizeBytes=12)
        row = {"student_id": user_id, "status": "Approved", "duty_hours": 80, "deleted_at": datetime.now(timezone.utc)}
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = row
        with patch.object(files, "transaction", return_value=transaction(conn)), patch.object(files, "current_user", return_value={"id": user_id}), patch.object(files.storage, "signed_upload_url") as signed:
            with self.assertRaises(HTTPException):
                files.upload_url(body, Mock())
            signed.assert_not_called()

    def test_new_application_stores_no_manual_grade_fields(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_grades.jpg"
        body = ApplicationIn(
            id=str(app_id),
            program="BS Information Technology",
            yearLevel="3rd Year",
            scholarshipType="Academic Scholarship",
            documents={
                "copyOfGrades": DocumentIn(
                    name="grades.jpg", path=path, sizeBytes=1200, mimeType="image/jpeg"
                )
            },
        )
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = {"status": "Open", "deadline_at": None}
        user = {
            "id": user_id,
            "full_name": "Student",
            "email": "student@panpacificu.edu.ph",
            "role": "student",
            "program": "BS Information Technology",
        }
        term = {"id": uuid4(), "trimester": "1st Trimester"}
        with patch.object(applications, "transaction", return_value=transaction(conn)), patch.object(applications, "current_user", return_value=user), patch.object(applications, "ensure_current_term", return_value=term), patch.object(applications, "check_stored_document", return_value=("grades.jpg", path, 1200, "image/jpeg")), patch.object(applications, "add_history"), patch.object(applications, "load_application", return_value={"code": "APP-00001"}), patch.object(applications, "notify"), patch.object(applications, "staff_ids", return_value=[]), patch.object(applications, "queue_email"), patch.object(applications, "application_out", return_value={"code": "APP-00001"}):
            result = applications.create_application(body, Mock())
        self.assertEqual(result, {"code": "APP-00001"})
        insert_call = next(
            call for call in conn.execute.call_args_list if "insert into applications" in call.args[0]
        )
        sql, params = insert_call.args
        self.assertNotIn("gwa", sql)
        self.assertNotIn("has_failing_grade", sql)
        self.assertEqual(len(params), 6)

    def test_file_signatures_and_spreadsheet(self):
        self.assertEqual(detect_file_kind(b"%PDF-1.7"), "pdf")
        self.assertEqual(detect_file_kind(b"\xef\xbb\xbfjunk%PDF-1.7"), "pdf")
        self.assertEqual(detect_file_kind(b"not a document"), "")
        self.assertTrue(looks_dangerous(b"<!DOCTYPE html><script>"))
        self.assertFalse(looks_dangerous(b"RIFF\x00\x00\x00\x00WEBPVP8 "))
        self.assertTrue(build_xlsx(["Name"], [["Student"]]).startswith(b"PK"))

    def test_apply_form_has_no_manual_grade_entry(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "PU scholarship system/scholarships.html",
            root / "PU scholarship system/js/scholarships.js",
            root / "PU scholarship system/js/data.js",
            root / "backend/app/schemas.py",
        ]
        sources = "".join(path.read_text(encoding="utf-8") for path in files)
        for token in (
            "applyGwa",
            "applyLowest",
            "applyFailingGrade",
            "applyIncompleteGrade",
            "applyDroppedGrade",
            "gwa:",
            "lowestGrade:",
            "hasFailingGrade:",
            "hasIncompleteGrade:",
            "hasDroppedGrade:",
        ):
            self.assertNotIn(token, sources)

    def test_browser_saved_jpg_is_accepted(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_asus.jpg"
        document = DocumentIn(name="asus.jpg", path=path, sizeBytes=1200, mimeType="image/jpeg")
        head = b"RIFF\x1a\x00\x00\x00WEBPVP8 "
        with patch.object(applications.storage, "object_info", return_value={"size": 1200, "mimetype": "image/webp"}), patch.object(applications.storage, "object_head_bytes", return_value=head):
            name, stored_path, size, mime = applications.check_stored_document(user_id, app_id, "copyOfGrades", document)
        self.assertEqual(name, "asus.jpg")
        self.assertEqual(stored_path, path)
        self.assertEqual(size, 1200)
        self.assertEqual(mime, "image/jpeg")

    def test_mismatched_png_content_is_accepted_for_image_extension(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_grades.jpg"
        document = DocumentIn(name="grades.jpg", path=path, sizeBytes=1200, mimeType="image/jpeg")
        head = b"\x89PNG\r\n\x1a\n" + b"0" * 8
        with patch.object(applications.storage, "object_info", return_value={"size": 1200, "mimetype": "image/jpeg"}), patch.object(applications.storage, "object_head_bytes", return_value=head):
            _, _, _, mime = applications.check_stored_document(user_id, app_id, "copyOfGrades", document)
        self.assertEqual(mime, "image/png")

    def test_html_as_pdf_and_pdf_as_jpg_are_rejected(self):
        user_id, app_id, file_id = uuid4(), uuid4(), uuid4()
        html_path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_grades.pdf"
        html_doc = DocumentIn(name="grades.pdf", path=html_path, sizeBytes=1200, mimeType="application/pdf")
        with patch.object(applications.storage, "object_info", return_value={"size": 1200, "mimetype": "application/pdf"}), patch.object(applications.storage, "object_head_bytes", return_value=b"<!DOCTYPE html><html>"):
            with self.assertRaises(HTTPException):
                applications.check_stored_document(user_id, app_id, "copyOfGrades", html_doc)

        jpg_path = f"{user_id}/{app_id}/copyOfGrades/{file_id}_grades.jpg"
        jpg_doc = DocumentIn(name="grades.jpg", path=jpg_path, sizeBytes=1200, mimeType="image/jpeg")
        with patch.object(applications.storage, "object_info", return_value={"size": 1200, "mimetype": "image/jpeg"}), patch.object(applications.storage, "object_head_bytes", return_value=b"%PDF-1.7\n1 0 obj"):
            with self.assertRaises(HTTPException):
                applications.check_stored_document(user_id, app_id, "copyOfGrades", jpg_doc)


if __name__ == "__main__":
    unittest.main()
