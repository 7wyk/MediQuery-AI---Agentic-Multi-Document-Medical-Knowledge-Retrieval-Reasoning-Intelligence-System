"""Import legacy SQLite user records into the new cloud schema.

What is migrated:
  * users (email, password hash, full name, created_at) - the `role` column is
    intentionally discarded because roles no longer exist.
  * query history for matching users (optional, --with-history).

What is NOT migrated:
  * uploaded files (they lived on local disk and are re-uploaded to Supabase
    Storage by the user),
  * Pinecone vectors (the embedding provider and dimensions changed; documents
    must be re-indexed after re-upload).

Usage (from backend/):

    python scripts/import_legacy_sqlite.py --sqlite ./mediquery.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.analytics import QueryLog  # noqa: E402
from app.models.user import User  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="./mediquery.db", help="Path to the legacy SQLite file")
    parser.add_argument("--with-history", action="store_true", help="Also copy query history")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    legacy_path = Path(args.sqlite)
    if not legacy_path.exists():
        raise SystemExit(f"Legacy database not found: {legacy_path}")

    source = sqlite3.connect(legacy_path)
    source.row_factory = sqlite3.Row

    users = source.execute(
        "SELECT id, email, hashed_password, full_name, created_at FROM users"
    ).fetchall()
    print(f"Found {len(users)} legacy users")

    id_map: dict[int, int] = {}
    created = 0
    skipped = 0

    with SessionLocal() as db:
        for row in users:
            email = (row["email"] or "").lower().strip()
            if not email:
                skipped += 1
                continue
            existing = db.query(User).filter(User.email == email).first()
            if existing is not None:
                id_map[row["id"]] = existing.id
                skipped += 1
                continue
            if args.dry_run:
                created += 1
                continue
            user = User(
                email=email,
                hashed_password=row["hashed_password"],
                full_name=row["full_name"] or email.split("@")[0],
                is_active=True,
            )
            db.add(user)
            db.flush()
            id_map[row["id"]] = user.id
            created += 1
        if not args.dry_run:
            db.commit()

        if args.with_history and id_map:
            try:
                logs = source.execute(
                    "SELECT user_id, question, answer, response_time, token_count, language, timestamp "
                    "FROM query_logs"
                ).fetchall()
            except sqlite3.Error as exc:
                print(f"Query history not copied: {exc}")
                logs = []
            copied = 0
            for row in logs:
                new_id = id_map.get(row["user_id"])
                if not new_id:
                    continue
                if args.dry_run:
                    copied += 1
                    continue
                timestamp = row["timestamp"]
                entry = QueryLog(
                    user_id=new_id,
                    question=row["question"],
                    answer=row["answer"],
                    response_time=row["response_time"],
                    token_count=row["token_count"],
                    language=row["language"] or "en",
                    mode="standard",
                )
                if timestamp:
                    try:
                        entry.timestamp = datetime.fromisoformat(str(timestamp))
                    except ValueError:
                        pass
                db.add(entry)
                copied += 1
            if not args.dry_run:
                db.commit()
            print(f"Query history rows copied: {copied}")

    print(f"Users created: {created}; already present/skipped: {skipped}")
    if args.dry_run:
        print("Dry run - no changes were written.")


if __name__ == "__main__":
    main()
