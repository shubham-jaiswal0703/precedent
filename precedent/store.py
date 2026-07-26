"""Storage that survives a redeploy.

Everything the app persists (the catalog, case packs, contradictions, caches,
job state) is a JSON document under a name. Locally those are files, which is
convenient and reviewable in git. On ephemeral or multi-instance hosting they
vanish or diverge, so when DATABASE_URL is present the same documents live in a
single Postgres table instead.

One table with a JSONB column rather than a schema per feature: the access
pattern is genuinely document-shaped, and a hackathon does not need migrations
to prove the point. The interface is the same either way, so no calling code
knows which backend it is talking to.
"""
import json
import os
import threading
from typing import Any, Dict, Optional

from .config import DATA_DIR

_LOCK = threading.Lock()
_POOL: Optional[Any] = None
_BACKEND: Optional[str] = None

TABLE = "precedent_documents"


def backend() -> str:
    """'postgres' when DATABASE_URL is usable, otherwise 'files'."""
    global _BACKEND
    if _BACKEND:
        return _BACKEND
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        try:
            _connect(url)
            _BACKEND = "postgres"
            return _BACKEND
        except Exception as exc:  # a bad URL should degrade, not crash the app
            print(f"[store] Postgres unavailable ({type(exc).__name__}), using files: {exc}")
    _BACKEND = "files"
    return _BACKEND


def _connect(url: str):
    """Lazily create the connection pool and ensure the table exists."""
    global _POOL
    if _POOL is not None:
        return _POOL
    from psycopg_pool import ConnectionPool

    # Railway hands out postgres:// URLs; psycopg wants postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    pool = ConnectionPool(url, min_size=1, max_size=4, kwargs={"autocommit": True})
    with pool.connection() as conn:
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                   name TEXT PRIMARY KEY,
                   body JSONB NOT NULL,
                   updated TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
    _POOL = pool
    return _POOL


def _path(name: str):
    return DATA_DIR / f"{name}.json"


def read(name: str, default: Any = None) -> Any:
    """Load a document, or `default` when it has never been written."""
    if backend() == "postgres":
        try:
            with _POOL.connection() as conn:  # type: ignore[union-attr]
                row = conn.execute(f"SELECT body FROM {TABLE} WHERE name = %s", (name,)).fetchone()
            return row[0] if row else default
        except Exception:
            pass  # fall through to the file copy shipped with the image
    path = _path(name)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def write(name: str, body: Any) -> None:
    """Persist a document."""
    if backend() == "postgres":
        try:
            with _POOL.connection() as conn:  # type: ignore[union-attr]
                conn.execute(
                    f"""INSERT INTO {TABLE} (name, body, updated) VALUES (%s, %s, now())
                        ON CONFLICT (name) DO UPDATE SET body = EXCLUDED.body, updated = now()""",
                    (name, json.dumps(body)),
                )
            return
        except Exception as exc:
            print(f"[store] write to Postgres failed ({exc}), writing a file instead")
    with _LOCK:
        path = _path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2))


def stamp(name: str) -> float:
    """Change marker for a document, used to invalidate in-memory caches."""
    if backend() == "postgres":
        try:
            with _POOL.connection() as conn:  # type: ignore[union-attr]
                row = conn.execute(
                    f"SELECT extract(epoch from updated) FROM {TABLE} WHERE name = %s", (name,)
                ).fetchone()
            if row:
                return float(row[0])
        except Exception:
            pass
    try:
        return _path(name).stat().st_mtime
    except OSError:
        return 0.0


def seed_from_files(names: Dict[str, Any]) -> Dict[str, str]:
    """Copy the documents shipped in the image into Postgres on first boot.

    The repo carries a warm catalog and cache set, so a fresh database should
    start from that rather than from an empty library.
    """
    if backend() != "postgres":
        return {name: "files" for name in names}
    result: Dict[str, str] = {}
    for name, default in names.items():
        existing = None
        try:
            with _POOL.connection() as conn:  # type: ignore[union-attr]
                row = conn.execute(f"SELECT 1 FROM {TABLE} WHERE name = %s", (name,)).fetchone()
                existing = bool(row)
        except Exception:
            existing = None
        if existing:
            result[name] = "already in postgres"
            continue
        path = _path(name)
        if path.exists():
            try:
                write(name, json.loads(path.read_text()))
                result[name] = "seeded from file"
                continue
            except Exception:
                pass
        write(name, default)
        result[name] = "initialised empty"
    return result
