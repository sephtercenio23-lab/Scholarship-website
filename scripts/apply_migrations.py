"""Apply pending SQL migrations from supabase/migrations to the database.

Usage:
    python scripts/apply_migrations.py

Reads DATABASE_URL from the environment (or the .env file in the repository
root, same as the web app). Every migration file is applied once, in filename
order, inside its own transaction. Applied versions are recorded in
public.schema_migrations, so re-running the script only applies new files.

Note: supabase/schema.sql already includes everything in supabase/migrations,
so on databases created from the current schema every migration is recorded or
applied as a harmless no-op. Databases created from an older schema (for
example missing the president/executive_president/super_admin roles) will
receive the missing migration here.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from backend.app.config import load_env_file

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def main():
    load_env_file()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not set. Add it to the environment or the .env file.")
        sys.exit(1)
    if not MIGRATIONS_DIR.is_dir():
        print(f"Migrations folder not found: {MIGRATIONS_DIR}")
        sys.exit(1)

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return

    print(f"Applying migrations from {MIGRATIONS_DIR}")
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        conn.execute(
            """
            create table if not exists public.schema_migrations (
              version text primary key,
              applied_at timestamptz not null default now()
            )
            """
        )
        conn.commit()
        applied = {row[0] for row in conn.execute("select version from public.schema_migrations")}
        pending = [path for path in files if path.stem not in applied]
        if not pending:
            print("Database is up to date; nothing to apply.")
            return
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            try:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("insert into public.schema_migrations (version) values (%s)", (path.stem,))
            except Exception as exc:
                print(f"FAILED to apply {path.name}: {exc}")
                print("Fix the problem and re-run; already-applied migrations are skipped.")
                sys.exit(1)
            print(f"applied {path.name}")
    print(f"Done. {len(pending)} migration(s) applied.")


if __name__ == "__main__":
    main()
