import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
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
from backend.app.schemas import DocumentIn, TermIn, UploadUrlIn
from backend.app.security import check_password, hash_password, verify_password
from backend.app.spreadsheet import build_xlsx
from backend.app.storage import detect_file_kind


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

    def test_file_signatures_and_spreadsheet(self):
        self.assertEqual(detect_file_kind(b"%PDF-1.7"), "pdf")
        self.assertEqual(detect_file_kind(b"not a document"), "")
        self.assertTrue(build_xlsx(["Name"], [["Student"]]).startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
