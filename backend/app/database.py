import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite holds metadata and statuses only; document evidence lives in Neo4j."""

    def __init__(self, path: Path):
        self.path = path
        with self.connect() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, document_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assessments (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def get(self, table: str, record_id: str):
        assert table in {"documents", "jobs", "assessments"}
        with self.connect() as con:
            row = con.execute(f"SELECT payload FROM {table} WHERE id=?", (record_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str):
        assert table in {"documents", "jobs", "assessments"}
        with self.connect() as con:
            rows = con.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def save(self, table: str, payload: dict):
        assert table in {"documents", "jobs", "assessments"}
        payload = {**payload, "updated_at": now()}
        with self.connect() as con:
            if table == "documents":
                con.execute("INSERT OR REPLACE INTO documents VALUES (?,?)",
                            (payload["id"], json.dumps(payload)))
            elif table == "jobs":
                con.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)",
                            (payload["id"], payload["document_id"], payload["status"], json.dumps(payload)))
            else:
                con.execute("INSERT OR REPLACE INTO assessments VALUES (?,?,?)",
                            (payload["id"], payload["status"], json.dumps(payload)))
        return payload

    def claim_assessment(self, record_id: str):
        with self.connect() as con:
            row = con.execute("SELECT payload FROM assessments WHERE id=? AND status='paused'",
                              (record_id,)).fetchone()
            if not row:
                return None
            item = json.loads(row[0])
            item.update(status="running", step="Resuming assessment", updated_at=now())
            changed = con.execute(
                "UPDATE assessments SET status='running', payload=? WHERE id=? AND status='paused'",
                (json.dumps(item), record_id),
            ).rowcount
        return item if changed else None
