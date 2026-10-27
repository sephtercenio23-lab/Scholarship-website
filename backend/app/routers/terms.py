from fastapi import APIRouter, HTTPException, Request

from ..catalog import SCHOLARSHIP_TYPES, TRIMESTERS, term_label
from ..common import (
    audit,
    ensure_current_term,
    load_terms,
    normalize_academic_year,
    parse_deadline_at,
    parse_uuid,
    scholarship_out,
    seed_scholarships,
    term_out,
    term_state,
)
from ..db import transaction
from ..deps import current_user
from ..schemas import ScholarshipsIn, TermIn
from ..security import bad_request, clean_text

router = APIRouter(prefix="/terms")


@router.get("")
def list_terms(request: Request):
    with transaction() as conn:
        current_user(conn, request)
        terms, _ = load_terms(conn)
        return terms


@router.get("/current")
def get_current_term(request: Request):
    with transaction() as conn:
        current_user(conn, request)
        current = ensure_current_term(conn)
        return term_out(current, current)


@router.put("/current")
def set_current_term(body: TermIn, request: Request):
    if body.trimester not in TRIMESTERS:
        raise bad_request("Please choose a trimester.")
    academic_year = normalize_academic_year(body.academicYear)
    with transaction() as conn:
        admin = current_user(conn, request, "admin")
        conn.execute("select pg_advisory_xact_lock(7001)")
        previous = ensure_current_term(conn)
        previous_label = term_label(previous["trimester"], previous["academic_year"])
        new_label = term_label(body.trimester, academic_year)
        if new_label == previous_label:
            raise bad_request(f"The system is already on {previous_label}. Nothing was changed.")
        target = conn.execute(
            "select * from academic_terms where trimester = %s and academic_year = %s",
            (body.trimester, academic_year),
        ).fetchone()
        if not target:
            target = conn.execute(
                "insert into academic_terms (trimester, academic_year) values (%s, %s) returning *",
                (body.trimester, academic_year),
            ).fetchone()
            carried = [
                scholarship_out(row)
                for row in conn.execute(
                    "select * from term_scholarships where term_id = %s order by sort_order",
                    (previous["id"],),
                )
            ]
            seed_scholarships(conn, target["id"], carried)
        archived = conn.execute(
            "select count(*) as total from applications where term_id = %s and deleted_at is null",
            (previous["id"],),
        ).fetchone()["total"]
        conn.execute("update academic_terms set is_current = false where is_current")
        conn.execute("update academic_terms set is_current = true where id = %s", (target["id"],))
        target = conn.execute("select * from academic_terms where id = %s", (target["id"],)).fetchone()
        audit(
            conn,
            admin,
            "term_changed",
            "term",
            target["id"],
            {"from": previous_label, "to": new_label, "archivedApplications": archived},
        )
        return {
            **term_out(target, target),
            "archived": archived,
            "previousLabel": previous_label,
        }


@router.put("/{term_id}/scholarships")
def save_scholarships(term_id: str, body: ScholarshipsIn, request: Request):
    target_id = parse_uuid(term_id)
    cleaned = []
    seen = set()
    for item in body.scholarships:
        if item.key not in SCHOLARSHIP_TYPES or item.key in seen:
            raise bad_request("One of the scholarships is not valid.")
        seen.add(item.key)
        if item.status not in ("Open", "Closed"):
            raise bad_request("Scholarship status must be Open or Closed.")
        eligibility = [" ".join(line.split()) for line in item.eligibility if line.strip()]
        if not eligibility:
            raise bad_request(f"Eligibility is required for {item.key}.")
        cleaned.append(
            (
                item.status,
                clean_text(item.benefit, "Benefit", 500),
                clean_text(item.deadline, "Deadline", 200),
                parse_deadline_at(item.deadlineAt),
                eligibility,
                item.key,
            )
        )
    with transaction() as conn:
        admin = current_user(conn, request, "admin")
        current = ensure_current_term(conn)
        term = conn.execute("select * from academic_terms where id = %s", (target_id,)).fetchone()
        if not term:
            raise HTTPException(status_code=404, detail="Term not found.")
        if term_state(term, current) == "Past":
            raise HTTPException(status_code=403, detail="Past term, read-only.")
        for status, benefit, deadline, deadline_at, eligibility, key in cleaned:
            conn.execute(
                """
                update term_scholarships
                set status = %s, benefit = %s, deadline = %s, deadline_at = %s, eligibility = %s
                where term_id = %s and scholarship_key = %s
                """,
                (status, benefit, deadline, deadline_at, eligibility, target_id, key),
            )
        audit(
            conn,
            admin,
            "scholarships_updated",
            "term",
            target_id,
            {
                "term": term_label(term["trimester"], term["academic_year"]),
                "count": len(cleaned),
                "scholarships": [item.key for item in body.scholarships],
            },
        )
        rows = conn.execute(
            "select * from term_scholarships where term_id = %s order by sort_order", (target_id,)
        ).fetchall()
        return [scholarship_out(row) for row in rows]
