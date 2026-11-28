import os
import re
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4
from zipfile import ZipFile

os.environ.setdefault("DATABASE_URL", "postgresql://unused")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unused")
os.environ.setdefault("JWT_SECRET", "x" * 32)

import psycopg
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import common
from backend.app.common import (
    build_applications,
    can_act_on_stage,
    ensure_user_role_check,
    export_approvals,
    next_approval_stage,
    normalize_academic_year,
    parse_deadline_at,
    term_state,
)
from backend.app.main import app
from backend.app.routers import admin, applications, files, terms
from backend.app.schemas import AccountIn, ApplicationIn, DiscountIn, DocumentIn, StatusIn, TermIn, UploadUrlIn
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
        conn.execute.side_effect = [Mock(), Mock(fetchone=Mock(return_value=target)), Mock(fetchone=Mock(return_value={"total": 3})), Mock(), Mock(), Mock(), Mock(fetchone=Mock(return_value=target))]
        with patch.object(terms, "transaction", return_value=transaction(conn)), patch.object(terms, "current_user", return_value={}) as require_user, patch.object(terms, "ensure_current_term", return_value=previous), patch.object(terms, "audit"):
            result = terms.set_current_term(TermIn(trimester="2nd Trimester", academicYear="2026–2027", deadlineAt="2026-12-15T17:00"), Mock())
        self.assertEqual(require_user.call_args.args[2:], ("staff", "admin", "super_admin"))
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

    def test_removed_duty_and_terminal_report_endpoints_and_uploads(self):
        app_id = uuid4()
        with TestClient(app) as client:
            for method, url in (
                ("patch", f"/api/admin/applications/{app_id}/duty"),
                ("post", f"/api/applications/{app_id}/terminal-report"),
                ("post", f"/api/staff/applications/{app_id}/terminal-report/receive"),
            ):
                self.assertIn(getattr(client, method)(url, json={}).status_code, (404, 405))
        user_id, file_id = uuid4(), uuid4()
        path = f"{user_id}/{app_id}/terminalReport/{file_id}_report.pdf"
        body = UploadUrlIn(path=path, applicationId=str(app_id), requirementKey="terminalReport", fileName="report.pdf", contentType="application/pdf", sizeBytes=12)
        with patch.object(files.storage, "signed_upload_url") as signed:
            with self.assertRaises(HTTPException):
                files.upload_url(body, Mock())
            signed.assert_not_called()
        self.assertNotIn("Duty hours", applications.EXPORT_HEADERS)
        self.assertNotIn("Report received", applications.EXPORT_HEADERS)

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
                Mock(), "", "", "", "", "", "", "", "staff", "csv"
            )
            admin_only, _, _ = applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "admin", "csv"
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
                Mock(), "", "", "", "", "", "", "", "", "csv"
            )
        self.assertEqual([item["code"] for item in result], ["complete"])

    def test_reviewers_can_start_evaluation_regardless_of_submission_window(self):
        conn = Mock()
        row = {
            "id": uuid4(), "status": "Submitted", "code": "APP-00001", "term_id": uuid4(),
            "scholarship_type": "Academic Scholarship", "owner_id": uuid4(),
            "student_name": "Student", "student_email": "student@panpacificu.edu.ph",
        }
        windows = [
            ("Open", datetime(2099, 1, 1, tzinfo=timezone.utc)), ("Open", None),
            ("Open", datetime(2000, 1, 1, tzinfo=timezone.utc)), ("Closed", None),
        ]
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user") as reviewer,
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "application_out", return_value={"status": "Under Evaluation"}),
            patch.object(applications, "add_history") as history,
            patch.object(applications, "notify") as notify,
            patch.object(applications, "queue_email"),
        ):
            for role in ("staff", "president", "executive_president"):
                reviewer.return_value = {"id": uuid4(), "role": role, "full_name": "Reviewer"}
                for status, deadline in windows:
                    with self.subTest(role=role, status=status, deadline=deadline):
                        conn.execute.return_value.fetchone.return_value = {"status": status, "deadline_at": deadline}
                        applications.update_status(str(row["id"]), StatusIn(status="Under Evaluation"), Mock())
                        self.assertEqual(conn.execute.call_args.args[1][0], "Under Evaluation")
                        history.assert_called_with(conn, row["id"], "Under Evaluation", "status_changed", "Reviewer", "")
                        notify.assert_called_with(conn, [row["owner_id"]], row["id"], "Your application APP-00001 is now under evaluation.")
            # Authorization is enforced by current_user before accessing the application.
            self.assertEqual(set(reviewer.call_args.args[2:]), {"staff", "president", "executive_president"})

    def test_student_submissions_still_close_manually_or_at_deadline(self):
        body = ApplicationIn(
            id=str(uuid4()), program="BS IT", yearLevel="1st Year", scholarshipType="Academic Scholarship",
            pastDiscount="none", documents={"copyOfGrades": DocumentIn(name="grades.pdf", path="grades.pdf")},
        )
        conn = Mock()
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"role": "student"}),
            patch.object(applications, "ensure_current_term", return_value={"id": uuid4()}),
        ):
            for status, deadline, message in (
                ("Closed", None, "closed"), ("Open", datetime(2000, 1, 1, tzinfo=timezone.utc), "has passed"),
            ):
                with self.subTest(status=status), self.assertRaises(HTTPException) as caught:
                    conn.execute.return_value.fetchone.return_value = {"status": status, "deadline_at": deadline}
                    applications.create_application(body, Mock())
                self.assertIn(message, caught.exception.detail)

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
        # One signature per approval level, in stage order, names in capital letters.
        self.assertEqual(
            approvers,
            [
                {
                    "stage": "staff",
                    "name": "ANA LIM",
                    "position": "Authorized Staff",
                    "office": "CSS Office",
                },
                {"stage": "president", "name": "MARIA SANTOS", "position": "Director of Academic Services"},
                {
                    "stage": "executive_president",
                    "name": "PEDRO REYES",
                    "position": "University President",
                },
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
        self.assertEqual(
            approvers,
            [
                {
                    "stage": "staff",
                    "name": "ANA LIM",
                    "position": "Authorized Staff",
                    "office": "CSS Office",
                }
            ],
        )
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
        self.assertEqual(history, [("Endorsed by Staff", "staff_endorsed")])
        self.assertTrue(all(kind == "admin" for _, _, kind in notified))
        update_call = next(call for call in conn.execute.call_args_list if "update applications" in call.args[0])
        self.assertEqual(update_call.args[1][0], "Endorsed by Staff")
        self.assertIsNone(update_call.args[1][3])

    def test_final_approval_sends_scholar_to_finance_and_notifies_staff(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
            "changed_after_finance": False,
            "finance_sent_at": None,
            "discount_percent": None,
        }
        user = {"id": uuid4(), "full_name": "Executive One", "role": "executive_president"}
        current = {"approvals": {"staff": {"by": "Staff"}, "president": {"by": "President"}}}
        approved = {"code": "APP-00001", "approvals": current["approvals"]}
        notified = []
        history = []
        audits = []
        finance_calls = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[current, approved, approved]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append((list(ids), msg, kind))),
            patch.object(applications, "add_history", side_effect=lambda c, app_id, status, event, actor, remarks="": history.append((status, event))),
            patch.object(applications, "queue_email"),
            patch.object(applications, "staff_ids", return_value=[]),
            patch.object(applications, "role_ids", return_value=[uuid4()]),
            patch.object(applications, "audit", side_effect=lambda *args, **kwargs: audits.append(args[2])),
            patch.object(
                applications,
                "send_scholars_to_finance",
                side_effect=lambda c, actor, apps, correction=False: finance_calls.append((list(apps), correction))
                or {"to": "zyren.ynalvez.ihs@panpacificu.edu.ph", "filename": "approved-scholars.xlsx"},
            ),
        ):
            applications.update_status(
                str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=50), Mock()
            )

        # The Excel file is emailed to Finance for the scholar that just got the third approval.
        self.assertEqual(finance_calls, [([approved], False)])
        self.assertIn(("Approved by Executive President", "executive_approved"), history)
        self.assertIn(("Sent to Finance", "finance_sent"), history)
        updates = [
            call.args[1][0]
            for call in conn.execute.call_args_list
            if "update applications" in call.args[0]
        ]
        self.assertEqual(updates, ["Approved by Executive President", "Sent to Finance"])
        finance_update = next(
            call for call in conn.execute.call_args_list if "finance_sent_at = now()" in call.args[0]
        )
        self.assertIn("changed_after_finance = false", finance_update.args[0])
        # The Authorized Staff are told both approvals are complete and where the file went.
        staff_messages = [msg for ids, msg, kind in notified if "automatically sent to Finance" in msg]
        self.assertTrue(staff_messages)
        self.assertIn("zyren.ynalvez.ihs@panpacificu.edu.ph", staff_messages[0])
        self.assertIn("The Director of Academic Services and the University President have completed their approvals.", staff_messages[0])
        self.assertIn("Excel", staff_messages[0])
        # The student only sees the final Approved status after the three approvals.
        self.assertTrue(any(kind == "student" and "approved scholar" in msg for _, msg, kind in notified))
        self.assertIn("application_approved", audits)

    def test_final_approval_of_a_correction_sends_the_correction_list(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Under Evaluation",
            "scholarship_type": "Academic Scholarship",
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
            "changed_after_finance": True,
            "finance_sent_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "discount_percent": 100,
        }
        user = {"id": uuid4(), "full_name": "Executive One", "role": "executive_president"}
        current = {"approvals": {"staff": {"by": "Staff"}, "president": {"by": "President"}}}
        history = []
        finance_calls = []
        notified = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[current, current, current]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append(msg)),
            patch.object(applications, "add_history", side_effect=lambda c, app_id, status, event, actor, remarks="": history.append((status, event))),
            patch.object(applications, "queue_email"),
            patch.object(applications, "role_ids", return_value=[]),
            patch.object(applications, "audit"),
            patch.object(
                applications,
                "send_scholars_to_finance",
                side_effect=lambda c, actor, apps, correction=False: finance_calls.append(correction)
                or {"to": "zyren.ynalvez.ihs@panpacificu.edu.ph", "filename": "finance-corrections.xlsx"},
            ),
        ):
            applications.update_status(
                str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=None), Mock()
            )

        self.assertEqual(finance_calls, [True])
        self.assertIn(("Sent to Finance", "finance_sent"), history)
        # The stored discount survives the correction approval when the field is left blank.
        first_update = next(
            call for call in conn.execute.call_args_list if "update applications" in call.args[0]
        )
        self.assertEqual(first_update.args[1][3], 100)
        self.assertTrue(any("correction list was automatically sent to Finance" in msg for msg in notified))

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

    def test_ensure_user_role_check_rewrites_stale_constraint(self):
        conn = MagicMock()
        original_flag = common._role_check_ready
        common._role_check_ready = False
        try:
            with patch.object(common.psycopg, "connect", return_value=conn):
                self.assertTrue(ensure_user_role_check())
        finally:
            common._role_check_ready = original_flag
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertTrue(any("drop constraint if exists users_role_check" in sql for sql in statements))
        add_sql = next(sql for sql in statements if "add constraint users_role_check" in sql)
        for role in ("student", "staff", "admin", "president", "executive_president", "super_admin"):
            self.assertIn(role, add_sql)
        conn.close.assert_called()

    def test_ensure_user_role_check_reports_when_ddl_fails(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("permission denied for table users")
        original_flag = common._role_check_ready
        common._role_check_ready = False
        try:
            with patch.object(common.psycopg, "connect", return_value=conn):
                self.assertFalse(ensure_user_role_check())
        finally:
            common._role_check_ready = original_flag
        conn.close.assert_called()

    def test_ensure_user_role_check_accepts_already_current_constraint(self):
        definition = "CHECK ((role = ANY (ARRAY['student'::text, 'staff'::text, 'admin'::text, 'president'::text, 'executive_president'::text, 'super_admin'::text])))"

        def run(sql, *args, **kwargs):
            if "pg_get_constraintdef" in sql:
                cursor = Mock()
                cursor.fetchone.return_value = (definition,)
                return cursor
            raise psycopg.errors.InsufficientPrivilege("permission denied for table users")

        conn = MagicMock()
        conn.execute.side_effect = run
        original_flag = common._role_check_ready
        common._role_check_ready = False
        try:
            with patch.object(common.psycopg, "connect", return_value=conn):
                self.assertTrue(ensure_user_role_check())
        finally:
            common._role_check_ready = original_flag
        conn.close.assert_called()
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse(any("alter table public.users" in sql for sql in statements))

    def test_create_account_reports_actionable_error_when_constraint_is_stale(self):
        class StaleRoleConn:
            def __init__(self):
                self.rolled_back = False

            def execute(self, sql, params=None):
                if "select 1 from users" in sql:
                    return Mock(fetchone=Mock(return_value=None))
                if "insert into users" in sql:
                    raise psycopg.errors.CheckViolation(
                        'new row for relation "users" violates check constraint "users_role_check"'
                    )
                raise AssertionError(f"unexpected sql: {sql}")

            def rollback(self):
                self.rolled_back = True

        conn = StaleRoleConn()
        actor = {"id": uuid4(), "full_name": "Actor", "role": "admin"}
        body = AccountIn(role="president", fullName="New User", email="new@panpacificu.edu.ph", password="Validpass1!")
        with (
            patch.object(admin, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(admin, "current_user", return_value=actor),
            patch.object(admin, "audit"),
            patch.object(admin, "ensure_user_role_check", return_value=False),
        ):
            with self.assertRaises(HTTPException) as caught:
                admin.create_account(body, Mock())
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIn("apply_all.sql", caught.exception.detail)

    def test_unhandled_error_maps_missing_schema_objects_to_actionable_message(self):
        import asyncio
        import json

        from backend.app import main as main_module

        for error in (
            psycopg.errors.UndefinedColumn('column a.past_discount does not exist'),
            psycopg.errors.UndefinedTable('relation "application_appeals" does not exist'),
            psycopg.errors.CheckViolation("unrelated constraint"),
        ):
            request = Mock()
            request.method = "GET"
            request.url.path = "/api/staff/applications"
            response = asyncio.run(main_module.unhandled_error(request, error))
            detail = json.loads(response.body)["detail"]
            if isinstance(error, (psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable)):
                self.assertIn("apply_all.sql", detail)
            else:
                self.assertEqual(detail, "Something went wrong on our side. Please try again.")

    def test_past_discount_is_required_and_limited_to_supported_choices(self):
        # Grades cannot be submitted until the student picks their past tuition discount.
        # "none" means the student was not a scholar, so it is stored as an empty value.
        for value, expected in (("25", 25), ("50", 50), ("75", 75), ("100", 100), ("none", None)):
            self.assertEqual(applications.parse_past_discount(value), expected)
        for invalid in (None, "", "30", "0", "half", "-25"):
            with self.assertRaises(HTTPException):
                applications.parse_past_discount(invalid)

    def export_application(self, approvals=None):
        return {
            "id": uuid4(),
            "code": "APP-00001",
            "studentName": "Arman Clark Untalan",
            "studentId": "2400779",
            "universityEmail": "arman@panpacificu.edu.ph",
            "program": "BS Information Technology",
            "yearLevel": "3rd Year",
            "scholarshipType": "Academic Scholarship",
            "term": "2nd Trimester, AY 2026\u20132027",
            "status": "Sent to Finance",
            "dateSubmitted": "2026-11-18T08:00:00+00:00",
            "evaluatedBy": "Staff One",
            "remarks": "",
            "discountPercent": 100,
            "dutyHours": 0,
            "reportReceivedAt": None,
            "postApprovalDocuments": {},
            "approvals": approvals
            if approvals is not None
            else {
                "staff": {"by": "Juan Dela Cruz", "at": "2026-11-19T01:00:00+00:00"},
                "president": {"by": "Maria Santos", "at": "2026-11-19T02:00:00+00:00"},
                "executivePresident": {"by": "Pedro Reyes", "at": "2026-11-19T03:00:00+00:00"},
            },
        }

    def test_excel_export_embeds_one_signature_per_approver_above_the_names(self):
        app = self.export_application()
        # The Finance workbook is generated from the final approval before the Finance hand-off.
        app["status"] = "Approved by Executive President"
        data = applications.build_application_workbook([app])
        with ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            drawing = archive.read("xl/drawings/drawing1.xml").decode("utf-8")
            styles = archive.read("xl/styles.xml").decode("utf-8")

        # One signature image per approving role, embedded in the workbook.
        self.assertEqual(
            sorted(name for name in names if name.startswith("xl/media/")),
            ["xl/media/image1.png", "xl/media/image2.png", "xl/media/image3.png"],
        )
        self.assertIn("xl/drawings/drawing1.xml", names)
        self.assertIn("xl/worksheets/_rels/sheet1.xml.rels", names)
        self.assertEqual(drawing.count("<xdr:oneCellAnchor>"), 3)
        # Names in capital letters, the role below the name, and the CSS Office for staff.
        self.assertIn("APPROVED BY:", sheet)
        self.assertIn("JUAN DELA CRUZ", sheet)
        self.assertIn("Authorized Staff", sheet)
        self.assertIn("CSS Office", sheet)
        self.assertIn("MARIA SANTOS", sheet)
        self.assertIn("Director of Academic Services", sheet)
        self.assertIn("PEDRO REYES", sheet)
        self.assertIn(">University President<", sheet)
        self.assertIn("Approved by University President", sheet)
        self.assertNotIn("Executive President", sheet)
        self.assertEqual(applications.status_label("Approved by President"), "Review by Director of Academic Services")
        self.assertEqual(applications.status_label("Approved by Executive President"), "Approved by University President")
        # The signature row is tall enough for the image to sit above the name.
        self.assertEqual(sheet.count('customHeight="1"'), 3)
        for height in re.findall(r'ht="(\d+)" customHeight="1"', sheet):
            self.assertLessEqual(int(height), 72)

    def test_excel_export_omits_approvers_who_have_not_approved(self):
        approvals = {
            "staff": {"by": "Juan Dela Cruz", "at": "2026-11-19T01:00:00+00:00"},
            "president": {"by": "Maria Santos", "at": "2026-11-19T02:00:00+00:00"},
            "executivePresident": None,
        }
        app = self.export_application(approvals=approvals)
        data = applications.build_application_workbook([app])
        with ZipFile(BytesIO(data)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            drawing = archive.read("xl/drawings/drawing1.xml").decode("utf-8")
            media = [name for name in archive.namelist() if name.startswith("xl/media/")]
        self.assertEqual(drawing.count("<xdr:oneCellAnchor>"), 2)
        self.assertEqual(len(media), 2)
        self.assertNotIn("University President", sheet.split("APPROVED BY:")[1])

    def test_csv_export_marks_the_signature_row_above_each_approver(self):
        rows = applications.export_certification_rows([self.export_application()])
        values = [row[0] for row in rows]
        self.assertEqual(values[0], "")
        self.assertEqual(values[1], "APPROVED BY:")
        self.assertEqual(
            values[2:10],
            [
                "[SIGNATURE]",
                "JUAN DELA CRUZ",
                "Authorized Staff",
                "CSS Office",
                "",
                "[SIGNATURE]",
                "MARIA SANTOS",
                "Director of Academic Services",
            ],
        )
        self.assertIn("[SIGNATURE]", values)
        self.assertEqual(values.count("[SIGNATURE]"), 3)

    def test_send_scholars_to_finance_emails_excel_attachment_and_audits(self):
        conn = Mock()
        user = {"id": uuid4(), "full_name": "Executive One", "role": "executive_president"}
        app = self.export_application()
        with (
            patch.object(applications, "queue_email") as queue,
            patch.object(applications, "audit") as audit_mock,
            patch.object(applications, "mail_configured", return_value=True),
        ):
            summary = applications.send_scholars_to_finance(conn, user, [app])

        self.assertEqual(summary["to"], "zyren.ynalvez.ihs@panpacificu.edu.ph")
        args = queue.call_args.args
        self.assertEqual(args[2], "zyren.ynalvez.ihs@panpacificu.edu.ph")
        self.assertIn("Approved scholars sent to Finance", args[3])
        self.assertIn("MARIA SANTOS (Director of Academic Services)", args[4])
        self.assertIn("PEDRO REYES (University President)", args[4])
        attachment = queue.call_args.kwargs["attachments"][0]
        self.assertEqual(attachment["mime"], applications.XLSX_MIME)
        self.assertTrue(attachment["content"].startswith(b"PK"))
        self.assertTrue(attachment["filename"].endswith(".xlsx"))
        self.assertEqual(audit_mock.call_args.args[2], "scholars_sent_to_finance")
        details = audit_mock.call_args.args[5]
        self.assertEqual(details["recipient"], "zyren.ynalvez.ihs@panpacificu.edu.ph")
        self.assertEqual(details["format"], "xlsx")
        self.assertEqual(details["codes"], ["APP-00001"])

    def test_send_scholars_to_finance_uses_the_correction_subject(self):
        conn = Mock()
        user = {"id": uuid4(), "full_name": "Executive One", "role": "executive_president"}
        with (
            patch.object(applications, "queue_email") as queue,
            patch.object(applications, "audit") as audit_mock,
            patch.object(applications, "mail_configured", return_value=True),
        ):
            applications.send_scholars_to_finance(
                conn, user, [self.export_application()], correction=True
            )
        self.assertIn("Correction list sent to Finance", queue.call_args.args[3])
        self.assertEqual(audit_mock.call_args.args[2], "finance_correction_sent")

    def test_editing_after_finance_flags_reapproval_and_notifies_student(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00001",
            "status": "Sent to Finance",
            "finance_sent_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Staff One", "role": "staff"}
        notified = []
        emails = []
        audits = []
        with (
            patch.object(applications, "add_history") as history,
            patch.object(applications, "audit", side_effect=lambda *args, **kwargs: audits.append(args[2])),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append(msg)),
            patch.object(applications, "queue_email", side_effect=lambda *args, **kwargs: emails.append(args[3])),
        ):
            flagged = applications.flag_changed_after_finance(conn, row, user, "Grades corrected.")

        self.assertTrue(flagged)
        update = next(
            call for call in conn.execute.call_args_list if "changed_after_finance = true" in call.args[0]
        )
        self.assertIn("set status = 'Under Evaluation'", update.args[0])
        self.assertEqual(update.args[1], (row["id"],))
        self.assertEqual(history.call_args.args[3], "finance_change_flagged")
        self.assertIn("application_changed_after_finance", audits)
        self.assertTrue(any("Changed after sent to Finance" in msg for msg in notified))
        self.assertTrue(any("Grades corrected." in msg for msg in notified))
        self.assertTrue(emails)

    def test_editing_before_finance_does_not_set_the_flag(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00002",
            "status": "Under Evaluation",
            "finance_sent_at": None,
            "owner_id": uuid4(),
            "student_name": "Student",
            "student_email": "student@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Staff One", "role": "staff"}
        with patch.object(applications, "add_history") as history, patch.object(applications, "notify") as notify_mock:
            self.assertFalse(
                applications.flag_changed_after_finance(conn, row, user, "Nothing to flag.")
            )
        history.assert_not_called()
        notify_mock.assert_not_called()
        self.assertFalse(any("changed_after_finance" in call.args[0] for call in conn.execute.call_args_list))

    def test_president_and_executive_president_can_export_approved_scholars(self):
        conn = Mock()
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"id": uuid4()}) as require_user,
            patch.object(applications, "load_applications", return_value=[]),
            patch.object(applications, "audit"),
        ):
            applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "", "xlsx"
            )
        roles = require_user.call_args.args[2:]
        for role in ("staff", "president", "executive_president", "admin", "super_admin"):
            self.assertIn(role, roles)

    def test_export_does_not_change_the_status_of_approved_scholars(self):
        conn = Mock()
        apps = [self.export_application()]
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value={"id": uuid4(), "role": "president"}),
            patch.object(applications, "load_applications", return_value=apps),
            patch.object(applications, "audit"),
        ):
            exported, _, _ = applications.prepare_application_export(
                Mock(), "", "", "", "", "", "", "", "", "csv"
            )
        self.assertEqual(exported[0]["status"], "Sent to Finance")
        self.assertFalse(
            any("set status = 'Exported'" in call.args[0] for call in conn.execute.call_args_list)
        )

    def test_students_see_approved_grades_then_approved_as_scholar(self):
        from backend.app.common import student_status

        self.assertEqual(student_status("Submitted"), "Submitted")
        self.assertEqual(student_status("Under Evaluation"), "Under Evaluation")
        self.assertEqual(student_status("Endorsed by Staff"), "Approved (Grades)")
        self.assertEqual(student_status("Approved by President"), "Approved (Grades)")
        self.assertEqual(
            student_status("Approved by Executive President"), "Approved as a Scholar"
        )
        self.assertEqual(student_status("Sent to Finance"), "Approved as a Scholar")
        self.assertEqual(student_status("Exported"), "Approved as a Scholar")
        self.assertEqual(student_status("Approved"), "Approved as a Scholar")
        self.assertEqual(student_status("Rejected"), "Rejected")

    def test_audit_log_migration_makes_the_log_append_only(self):
        root = Path(__file__).resolve().parents[1]
        migration = (root / "supabase/migrations/20261126_finance_workflow.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("before update or delete on public.audit_log", migration)
        self.assertIn("revoke update, delete, truncate on public.audit_log from public", migration)
        self.assertIn("'Sent to Finance'", migration)
        self.assertIn("changed_after_finance", migration)
        schema = (root / "supabase/schema.sql").read_text(encoding="utf-8")
        self.assertIn("audit_log_append_only", schema)
        self.assertIn("Sent to Finance", schema)
        apply_all = (root / "supabase/apply_all.sql").read_text(encoding="utf-8")
        self.assertIn("20261126_finance_workflow.sql", apply_all)

    def test_finance_address_comes_from_configuration(self):
        from backend.app.catalog import FINANCE_EMAIL

        self.assertEqual(FINANCE_EMAIL, "zyren.ynalvez.ihs@panpacificu.edu.ph")


    def test_deliver_attaches_the_excel_workbook_to_the_email(self):
        from types import SimpleNamespace

        from backend.app import mailer

        captured = {}

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                pass

            def login(self, *args):
                pass

            def send_message(self, message):
                captured["message"] = message

        settings = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_from="no-reply@panpacificu.edu.ph",
            smtp_user="",
            smtp_password="",
        )
        attachment = {
            "filename": "approved-scholars.xlsx",
            "content": b"PK\x03\x04workbook",
            "mime": applications.XLSX_MIME,
        }
        with patch.object(mailer.smtplib, "SMTP", FakeSMTP):
            mailer.deliver(
                "zyren.ynalvez.ihs@panpacificu.edu.ph",
                "Approved scholars sent to Finance",
                "Attached.",
                settings,
                [attachment],
            )
        message = captured["message"]
        self.assertEqual(message["To"], "zyren.ynalvez.ihs@panpacificu.edu.ph")
        parts = [part for part in message.walk() if part.get_filename()]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].get_filename(), "approved-scholars.xlsx")
        self.assertEqual(parts[0].get_content_type(), applications.XLSX_MIME)
        self.assertEqual(parts[0].get_payload(decode=True), attachment["content"])


    def test_resend_delivery_base64_encodes_the_excel_attachment(self):
        import base64
        from types import SimpleNamespace

        from backend.app import mailer

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

        settings = SimpleNamespace(
            resend_api_key="re_test_key",
            resend_from="no-reply@panpacificu.edu.ph",
            smtp_host="",
            smtp_from="",
        )
        with patch.object(mailer.httpx, "post", side_effect=fake_post):
            mailer.deliver_any(
                "zyren.ynalvez.ihs@panpacificu.edu.ph",
                "Approved scholars sent to Finance",
                "Attached.",
                settings,
                [
                    {
                        "filename": "approved-scholars.xlsx",
                        "content": b"PK\x03\x04workbook",
                        "mime": applications.XLSX_MIME,
                    }
                ],
            )
        payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.resend.com/emails")
        self.assertEqual(payload["to"], ["zyren.ynalvez.ihs@panpacificu.edu.ph"])
        self.assertEqual(payload["attachments"][0]["filename"], "approved-scholars.xlsx")
        self.assertEqual(
            base64.b64decode(payload["attachments"][0]["content"]), b"PK\x03\x04workbook"
        )

    def test_render_message_replaces_ephemeral_vercel_deployment_url_with_production_url(self):
        from types import SimpleNamespace

        from backend.app import mailer

        settings = SimpleNamespace(
            public_base_url="scholarship-website-rgxas7eun-acme-a06f.vercel.app"
        )
        env = {
            "VERCEL_PROJECT_PRODUCTION_URL": "scholarship-website.vercel.app",
            "VERCEL_URL": "scholarship-website-abc123def-acme-a06f.vercel.app",
        }
        with (
            patch.object(mailer, "get_settings", return_value=settings),
            patch.dict(os.environ, env, clear=False),
        ):
            rendered = mailer.render_message("Your application APP-00006 was approved.")

        self.assertIn(
            "Sign in to the scholarship portal: https://scholarship-website.vercel.app",
            rendered,
        )
        self.assertNotIn("rgxas7eun", rendered)

    def test_render_message_uses_production_url_when_public_base_url_is_empty(self):
        from types import SimpleNamespace

        from backend.app import mailer

        settings = SimpleNamespace(public_base_url="")
        with (
            patch.object(mailer, "get_settings", return_value=settings),
            patch.dict(
                os.environ,
                {"VERCEL_PROJECT_PRODUCTION_URL": "scholarship-website.vercel.app"},
                clear=False,
            ),
        ):
            rendered = mailer.render_message("Your application APP-00006 was approved.")

        self.assertIn(
            "Sign in to the scholarship portal: https://scholarship-website.vercel.app",
            rendered,
        )

    def test_render_message_preserves_custom_and_branch_urls_with_scheme(self):
        from types import SimpleNamespace

        from backend.app import mailer

        for configured, expected in (
            ("scholarships.panpacificu.edu.ph", "https://scholarships.panpacificu.edu.ph"),
            (
                "https://scholarship-website-git-feature01-acme-a06f.vercel.app/",
                "https://scholarship-website-git-feature01-acme-a06f.vercel.app",
            ),
        ):
            settings = SimpleNamespace(public_base_url=configured)
            with (
                patch.object(mailer, "get_settings", return_value=settings),
                patch.dict(
                    os.environ,
                    {"VERCEL_PROJECT_PRODUCTION_URL": "scholarship-website.vercel.app"},
                    clear=False,
                ),
            ):
                rendered = mailer.render_message("Approved.")
            self.assertIn(f"Sign in to the scholarship portal: {expected}", rendered)

    def test_request_middleware_captures_non_ephemeral_origin_for_email_links(self):
        from types import SimpleNamespace

        from backend.app import mailer

        captured = {}
        settings = SimpleNamespace(
            public_base_url="https://scholarship-website-rgxas7eun-acme-a06f.vercel.app"
        )

        @app.get("/api/_test_portal_link")
        def _probe():
            captured["rendered"] = mailer.render_message("Approved.")
            return {"ok": True}

        try:
            with (
                TestClient(app) as client,
                patch.object(mailer, "get_settings", return_value=settings),
                patch.dict(
                    os.environ,
                    {
                        "VERCEL_PROJECT_PRODUCTION_URL": "",
                        "VERCEL_BRANCH_URL": "",
                        "VERCEL_URL": "",
                    },
                    clear=False,
                ),
            ):
                response = client.get(
                    "/api/_test_portal_link",
                    headers={
                        "x-forwarded-host": "scholarship-website.vercel.app",
                        "x-forwarded-proto": "https",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    "Sign in to the scholarship portal: https://scholarship-website.vercel.app",
                    captured["rendered"],
                )
                # Request context is cleared after the response completes.
                self.assertEqual(mailer._request_base_url.get(), "")
        finally:
            app.router.routes[:] = [
                route for route in app.router.routes if getattr(route, "path", None) != "/api/_test_portal_link"
            ]

    def test_staff_can_edit_discount_once_endorsed_in_current_term(self):
        conn = Mock()
        user = {"id": uuid4(), "full_name": "Ralph Anderson Diolazo", "role": "staff"}
        for status in ("Endorsed by Staff", "Approved by President"):
            conn.reset_mock()
            row = {
                "id": uuid4(),
                "code": "APP-00011",
                "status": status,
                "finance_sent_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
                "changed_after_finance": False,
                "owner_id": uuid4(),
                "student_name": "Mar",
                "student_email": "mar.ecoast@panpacificu.edu.ph",
            }
            history = []
            with (
                patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
                patch.object(applications, "current_user", return_value=user) as require_user,
                patch.object(applications, "locked_application", return_value=row),
                patch.object(applications, "ensure_editable"),
                patch.object(
                    applications,
                    "add_history",
                    side_effect=lambda c, app_id, st, ev, actor, remarks="": history.append((st, ev, remarks)),
                ),
                patch.object(applications, "flag_changed_after_finance") as flag_mock,
                patch.object(applications, "notify") as notify_mock,
                patch.object(applications, "queue_email") as email_mock,
                patch.object(applications, "load_application", return_value=row),
                patch.object(applications, "application_out", return_value={"id": str(row["id"]), "discountPercent": 75, "status": status}),
            ):
                result = applications.update_discount(str(row["id"]), DiscountIn(discountPercent=75), Mock())
            self.assertEqual(require_user.call_args.args[2:], ("staff", "admin", "super_admin"))
            self.assertEqual(result["discountPercent"], 75)
            update_call = next(
                call for call in conn.execute.call_args_list if "update applications set discount_percent" in call.args[0]
            )
            self.assertEqual(update_call.args[1], (75, row["id"]))
            self.assertEqual(history, [(status, "discount_changed", "Tuition fee discount set to 75%.")])
            flag_mock.assert_not_called()
            notify_mock.assert_not_called()
            email_mock.assert_not_called()

        # Pre-endorsement and rejected statuses cannot edit discount; past term is rejected as 403.
        for blocked_status in ("Submitted", "Under Evaluation", "Rejected"):
            row = {"id": uuid4(), "status": blocked_status}
            with (
                patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
                patch.object(applications, "current_user", return_value=user),
                patch.object(applications, "locked_application", return_value=row),
                patch.object(applications, "ensure_editable"),
            ):
                with self.assertRaises(HTTPException) as caught:
                    applications.update_discount(str(row["id"]), DiscountIn(discountPercent=50), Mock())
                self.assertEqual(caught.exception.status_code, 400)

        past_row = {"id": uuid4(), "status": "Endorsed by Staff"}
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=past_row),
            patch.object(applications, "is_past", return_value=True),
        ):
            with self.assertRaises(HTTPException) as caught:
                applications.update_discount(str(past_row["id"]), DiscountIn(discountPercent=50), Mock())
            self.assertEqual(caught.exception.status_code, 403)

    def test_encoded_discount_survives_president_approval_and_notifies_on_final_approval(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00011",
            "status": "Endorsed by Staff",
            "scholarship_type": "Entrance Exam Scholarship",
            "owner_id": uuid4(),
            "student_name": "Mar",
            "student_email": "mar.ecoast@panpacificu.edu.ph",
            "discount_percent": 75,
            "changed_after_finance": False,
            "finance_sent_at": None,
        }
        president = {"id": uuid4(), "full_name": "Director One", "role": "president"}
        approvals_after_staff = {"approvals": {"staff": {"by": "Ralph"}}}
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=president),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[approvals_after_staff, approvals_after_staff]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify"),
            patch.object(applications, "add_history"),
            patch.object(applications, "audit"),
            patch.object(applications, "role_ids", return_value=[]),
        ):
            applications.update_status(str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=None), Mock())
        pres_update = next(call for call in conn.execute.call_args_list if "update applications" in call.args[0])
        self.assertEqual(pres_update.args[1][0], "Approved by President")
        self.assertEqual(pres_update.args[1][3], 75)

        conn.reset_mock()
        row["status"] = "Approved by President"
        exec_user = {"id": uuid4(), "full_name": "President One", "role": "executive_president"}
        approvals_after_pres = {"approvals": {"staff": {"by": "Ralph"}, "president": {"by": "Director One"}}}
        notified = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=exec_user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "application_out", side_effect=[approvals_after_pres, approvals_after_pres, approvals_after_pres]),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append((kind, msg))),
            patch.object(applications, "add_history"),
            patch.object(applications, "queue_email"),
            patch.object(applications, "role_ids", return_value=[]),
            patch.object(applications, "audit"),
            patch.object(applications, "send_scholars_to_finance", return_value=None),
        ):
            applications.update_status(str(row["id"]), StatusIn(status="Approved", remarks="", discountPercent=None), Mock())
        self.assertTrue(any(kind == "student" and "75% tuition fee discount" in msg for kind, msg in notified))

    def test_update_discount_on_sent_to_finance_flags_reapproval_and_notifies_student(self):
        conn = Mock()
        row = {
            "id": uuid4(),
            "code": "APP-00011",
            "status": "Sent to Finance",
            "finance_sent_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "changed_after_finance": False,
            "owner_id": uuid4(),
            "student_name": "Mar",
            "student_email": "mar.ecoast@panpacificu.edu.ph",
        }
        user = {"id": uuid4(), "full_name": "Ralph Anderson Diolazo", "role": "staff"}
        notified = []
        emails = []
        with (
            patch.object(applications, "transaction", side_effect=lambda: transaction(conn)),
            patch.object(applications, "current_user", return_value=user),
            patch.object(applications, "locked_application", return_value=row),
            patch.object(applications, "ensure_editable"),
            patch.object(applications, "add_history"),
            patch.object(applications, "flag_changed_after_finance", return_value=True) as flag_mock,
            patch.object(applications, "notify", side_effect=lambda c, ids, app_id, msg, kind="student": notified.append(msg)),
            patch.object(applications, "queue_email", side_effect=lambda *args, **kwargs: emails.append(args[3])),
            patch.object(applications, "load_application", return_value=row),
            patch.object(applications, "application_out", return_value={"id": str(row["id"]), "discountPercent": 50}),
        ):
            applications.update_discount(str(row["id"]), DiscountIn(discountPercent=50), Mock())
        flag_mock.assert_called_once()
        self.assertTrue(any("50%" in msg for msg in notified))
        self.assertTrue(emails)


if __name__ == "__main__":
    unittest.main()
