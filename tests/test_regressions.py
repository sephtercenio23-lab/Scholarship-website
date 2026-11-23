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
from backend.app.common import (
    build_applications,
    can_act_on_stage,
    export_approvals,
    next_approval_stage,
    normalize_academic_year,
    parse_deadline_at,
    term_state,
)
from backend.app.main import app
from backend.app.routers import admin, applications, files, terms
from backend.app.schemas import AccountIn, ApplicationIn, DocumentIn, StatusIn, TermIn, UploadUrlIn
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

    def test_staff_application_list_can_include_past_terms_without_history_route(self):
        conn = Mock()
        with (
            TestClient(app) as client,
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user") as require_user,
            patch.object(applications, "load_applications", return_value=[]) as load,
        ):
            self.assertEqual(client.get("/api/staff/applications").status_code, 200)
            load.assert_called_once_with(conn, "a.deleted_at is null and t.is_current")

            self.assertEqual(client.get("/api/staff/applications?active=false").status_code, 200)
            load.assert_called_with(conn, "a.deleted_at is null")
            self.assertEqual(require_user.call_args.args[2:], ("staff", "admin", "president", "executive_president", "super_admin"))
            self.assertIn(client.get("/api/staff/applications/history").status_code, (404, 405))

    def test_staff_evaluators_returns_active_staff_and_admin_names(self):
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = [
            {"full_name": "Authorized Staff"},
            {"full_name": "System Admin"},
        ]
        with (
            TestClient(app) as client,
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user") as require_user,
        ):
            response = client.get("/api/staff/evaluators")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), ["Authorized Staff", "System Admin"])
            self.assertEqual(require_user.call_args.args[2:], ("staff", "admin", "president", "executive_president", "super_admin"))
            sql = conn.execute.call_args.args[0]
            self.assertIn("role in ('staff', 'admin', 'president', 'executive_president', 'super_admin')", sql)
            self.assertIn("deleted_at is null", sql)

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
            pastDiscount="50",
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
        self.assertIn("past_discount", sql)
        self.assertEqual(len(params), 7)
        self.assertEqual(params[-1], 50)

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

    def test_evaluator_history_query_excludes_student_submissions_and_keeps_true_approval(self):
        app_id = uuid4()
        owner_id = uuid4()
        term_id = uuid4()
        approved_at = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
        doc_reviewed_at = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)
        current_term = {"id": term_id, "trimester": "2nd Trimester", "academic_year": "2026–2027"}
        row = {
            "id": app_id,
            "code": "APP-00006",
            "owner_id": owner_id,
            "student_name": "Arman Clark Untalan",
            "student_number": "2400779",
            "student_email": "arman@panpacificu.edu.ph",
            "program": "BS Information Technology",
            "year_level": "3rd Year",
            "scholarship_type": "Academic Scholarship",
            "status": "Approved",
            "remarks": None,
            "evaluated_by": "System Admin",
            "discount_percent": 100,
            "has_failing_grade": False,
            "has_incomplete_grade": False,
            "has_dropped_grade": False,
            "duty_hours": 0,
            "duty_completed": False,
            "report_received_at": None,
            "term_id": term_id,
            "trimester": "2nd Trimester",
            "academic_year": "2026–2027",
            "deleted_at": None,
            "created_at": datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc),
        }
        history_rows = [
            {
                "application_id": app_id,
                "status": "Under Evaluation",
                "event_type": "status_changed",
                "created_at": datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc),
                "actor_name": "System Admin",
                "actor_role": "admin",
            },
            {
                "application_id": app_id,
                "status": "Approved",
                "event_type": "status_changed",
                "created_at": approved_at,
                "actor_name": "System Admin",
                "actor_role": "admin",
            },
            {
                "application_id": app_id,
                "status": "Approved",
                "event_type": "document_accepted",
                "created_at": doc_reviewed_at,
                "actor_name": "Authorized Staff",
                "actor_role": "staff",
            },
        ]
        conn = Mock()
        conn.execute.side_effect = [[], [], history_rows, []]
        with patch("backend.app.common.ensure_current_term", return_value=current_term):
            result = build_applications(conn, [row])

        history_sql = conn.execute.call_args_list[2].args[0]
        self.assertIn("and ah.event_type in (", history_sql)
        self.assertNotIn("'document_submitted'", history_sql)
        self.assertNotIn("'report_submitted'", history_sql)
        self.assertIn("stu.role = 'student'", history_sql)
        self.assertIn("staff.role in ('staff', 'admin', 'president', 'executive_president', 'super_admin')", history_sql)

        self.assertEqual(result[0]["evaluators"], ["Authorized Staff", "System Admin"])
        self.assertEqual(result[0]["evaluatorRoles"], ["admin", "staff"])
        self.assertEqual(result[0]["approvedBy"], "System Admin")
        self.assertEqual(result[0]["approvedAt"], approved_at.isoformat())

    def test_export_evaluator_filter_supports_role_filters(self):
        conn = Mock()
        apps = [
            {"code": "APP-00001", "status": "Approved", "approvals": {"staff": {"by": "S"}, "president": {"by": "P"}, "executivePresident": {"by": "E"}}, "evaluators": ["System Admin"], "evaluatorRoles": ["admin"]},
            {"code": "APP-00002", "status": "Approved", "approvals": {"staff": {"by": "S"}, "president": {"by": "P"}, "executivePresident": {"by": "E"}}, "evaluators": ["Staff One"], "evaluatorRoles": ["staff"]},
        ]
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"id": uuid4(), "role": "admin"}),
            patch.object(applications, "load_applications", return_value=apps),
            patch.object(applications, "audit"),
        ):
            staff_only, _, _ = applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "", "", "staff", "csv"
            )
            admin_only, _, _ = applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "", "", "admin", "csv"
            )
        self.assertEqual([app["code"] for app in staff_only], ["APP-00002"])
        self.assertEqual([app["code"] for app in admin_only], ["APP-00001"])

    def test_export_excludes_incomplete_and_legacy_approvals(self):
        conn = Mock()
        full = {"staff": {"by": "Staff"}, "president": {"by": "President"}, "executivePresident": {"by": "Executive"}}
        apps = [
            {"code": "complete", "status": "Approved", "approvals": full},
            {"code": "pending", "status": "Under Evaluation", "approvals": full},
            {"code": "legacy", "status": "Approved", "approvals": {"staff": {"by": "Staff"}}},
        ]
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"id": uuid4(), "role": "staff"}),
            patch.object(applications, "load_applications", return_value=apps),
            patch.object(applications, "audit"),
        ):
            result, _, _ = applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "", "", "", "csv"
            )
        self.assertEqual([item["code"] for item in result], ["complete"])

    def test_evaluation_waits_until_application_period_ends(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = {"status": "Open", "deadline_at": datetime(2099, 1, 1, tzinfo=timezone.utc)}
        row = {"id": uuid4(), "term_id": uuid4(), "scholarship_type": "Academic Scholarship", "status": "Submitted"}
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"id": uuid4(), "role": "staff"}),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", return_value={"approvals": {}}),
        ):
            with self.assertRaises(HTTPException) as error:
                applications.update_status(str(row["id"]), StatusIn(status="Under Evaluation"), Mock())
        self.assertIn("application period has ended", error.exception.detail)

    def test_three_level_approval_stage_order(self):
        self.assertEqual(next_approval_stage({}), "staff")
        self.assertEqual(next_approval_stage({"staff": {"by": "Staff"}}), "president")
        self.assertEqual(
            next_approval_stage({"staff": {"by": "Staff"}, "president": {"by": "President"}}),
            "executive_president",
        )
        self.assertIsNone(
            next_approval_stage(
                {
                    "staff": {"by": "Staff"},
                    "president": {"by": "President"},
                    "executive_president": {"by": "Executive"},
                }
            )
        )
        self.assertTrue(can_act_on_stage("staff", "staff"))
        self.assertFalse(can_act_on_stage("staff", "president"))
        self.assertTrue(can_act_on_stage("president", "president"))
        self.assertTrue(can_act_on_stage("executive_president", "executive_president"))
        self.assertFalse(can_act_on_stage("super_admin", "executive_president"))

    def test_export_certification_shows_only_completed_approvers_uppercase(self):
        apps = [
            {
                "status": "Approved",
                "approvedBy": "Juan Dela Cruz",
                "evaluatedBy": "Juan Dela Cruz",
                "approvals": {
                    "staff": {"by": "Juan Dela Cruz"},
                    "president": {"by": "Maria Santos"},
                    "executivePresident": {"by": "Pedro Reyes"},
                },
            },
            {
                "status": "Under Evaluation",
                "approvedBy": "",
                "evaluatedBy": "",
                "approvals": {"staff": {"by": "Ana Lim"}, "president": None, "executivePresident": None},
            },
        ]
        approvers = export_approvals(apps)
        self.assertEqual(
            approvers,
            [
                {"name": "ANA LIM", "position": "Authorized Staff", "office": "CSS Office"},
                {"name": "JUAN DELA CRUZ", "position": "Authorized Staff", "office": "CSS Office"},
                {"name": "MARIA SANTOS", "position": "President"},
                {"name": "PEDRO REYES", "position": "Executive President"},
            ],
        )
        rows = applications.export_certification_rows(apps)
        flat = [row[0] for row in rows]
        self.assertIn("APPROVED BY:", flat)

    def test_export_certification_omits_pending_approvers(self):
        apps = [
            {
                "status": "Under Evaluation",
                "approvedBy": "",
                "evaluatedBy": "",
                "approvals": {"staff": {"by": "Ana Lim"}, "president": None, "executivePresident": None},
            }
        ]
        approvers = export_approvals(apps)
        self.assertEqual(approvers, [{"name": "ANA LIM", "position": "Authorized Staff", "office": "CSS Office"}])
        self.assertEqual(applications.export_certification_rows([]), [])

    def test_staff_endorsement_does_not_final_approve_or_notify_student(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Staff One", "role": "staff"}
        current = {"approvals": {}}
        notified = []
        history = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[current, current]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append((list(ids), msg, kind))),
            patch.object(applications, "add_history", side_effect=lambda c, app_id, status, event, actor, remarks="": history.append((status, event))),
            patch.object(applications, "queue_email"),
            patch.object(applications, "staff_ids", return_value=[]),
            patch.object(applications, "role_ids", return_value=[]),
        ):
            applications.update_status(str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=50), Mock())
        self.assertEqual(history, [("Under Evaluation", "staff_endorsed")])
        self.assertTrue(all(kind == "admin" for _, _, kind in notified))
        update_call = next(call for call in conn.execute.call_args_list if "update applications" in call.args[0])
        self.assertEqual(update_call.args[1][0], "Under Evaluation")
        self.assertIsNone(update_call.args[1][3])

    def test_final_approval_sets_approved_and_notifies_student(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Executive One", "role": "executive_president"}
        current = {"approvals": {"staff": {"by": "Staff"}, "president": {"by": "President"}}}
        notified = []
        history = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[current, current]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append((list(ids), msg, kind))),
            patch.object(applications, "add_history", side_effect=lambda c, app_id, status, event, actor, remarks="": history.append((status, event))),
            patch.object(applications, "queue_email"),
            patch.object(applications, "staff_ids", return_value=[]),
            patch.object(applications, "role_ids", return_value=[]),
        ):
            applications.update_status(str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=50), Mock())
        self.assertEqual(history, [("Approved", "executive_approved")])
        self.assertTrue(any(kind == "student" and "was approved" in msg for _, msg, kind in notified))
        update_call = next(call for call in conn.execute.call_args_list if "update applications" in call.args[0])
        self.assertEqual(update_call.args[1][0], "Approved")
        self.assertEqual(update_call.args[1][3], 50)

    def test_president_cannot_approve_before_staff_endorsement(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "President One", "role": "president"}
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", return_value={"approvals": {}}),
        ):
            with self.assertRaises(HTTPException):
                applications.update_status(str(row["id"]), StatusIn(status="Approved", remarks=""), Mock())

    def test_rejection_requires_remarks_and_notifies_student_with_remarks(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Staff One", "role": "staff"}
        notified = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[{"approvals": {}}, {"approvals": {}}]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append(msg)),
            patch.object(applications, "add_history"),
            patch.object(applications, "queue_email"),
            patch.object(applications, "staff_ids", return_value=[]),
        ):
            with self.assertRaises(HTTPException):
                applications.update_status(str(row["id"]), StatusIn(status="Rejected", remarks=""), Mock())
            applications.update_status(str(row["id"]), StatusIn(status="Rejected", remarks="Incomplete grades"), Mock())
        self.assertTrue(any("Incomplete grades" in msg for msg in notified))

    def test_account_creation_rules_for_new_roles(self):
        def attempt(actor_role, new_role):
            conn = Mock()
            conn.execute.return_value.fetchone.side_effect = [
                None,
                {"id": uuid4(), "full_name": "New User", "email": "new@panpacificu.edu.ph", "role": new_role, "student_id": None, "program": None, "year_level": None, "created_at": None},
            ]
            actor = {"id": uuid4(), "full_name": "Actor", "role": actor_role}
            body = AccountIn(role=new_role, fullName="New User", email="new@panpacificu.edu.ph", password="Validpass1!")
            with (
                patch.object(admin, "transaction", side_effect=lambda: transaction(conn)),
                patch.object(admin, "current_user", return_value=actor),
                patch.object(admin, "audit"),
            ):
                try:
                    admin.create_account(body, Mock())
                    return True
                except HTTPException:
                    return False

        self.assertTrue(attempt("admin", "president"))
        self.assertTrue(attempt("admin", "executive_president"))
        self.assertFalse(attempt("admin", "super_admin"))
        self.assertTrue(attempt("super_admin", "super_admin"))
        self.assertFalse(attempt("admin", "student"))
        self.assertFalse(attempt("super_admin", "student"))

    def test_past_discount_is_required_and_limited_to_supported_choices(self):
        # Grades cannot be submitted until the student picks their past tuition discount.
        # "none" means the student was not a scholar, so it is stored as an empty value.
        for value, expected in (("25", 25), ("50", 50), ("75", 75), ("100", 100), ("none", None)):
            self.assertEqual(applications.parse_past_discount(value), expected)
        for invalid in (None, "", "30", "0", "half", "-25"):
            with self.assertRaises(HTTPException):
                applications.parse_past_discount(invalid)


if __name__ == "__main__":
    unittest.main()
