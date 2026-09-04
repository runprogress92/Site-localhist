"""Couche d'accès SQLite.

Un pool de connexions par thread (le serveur HTTP est multi-thread), le
schéma appliqué à la volée, et quelques utilitaires de requêtage qui
renvoient directement des dictionnaires prêts à sérialiser en JSON.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "athlytics.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_local = threading.local()
_db_path: Path = Path(os.environ.get("ATHLYTICS_DB", DEFAULT_DB))
_init_lock = threading.Lock()
_initialised = False


def set_db_path(path: str | Path) -> None:
    """Change la base utilisée par le processus (tests, base secondaire)."""
    global _db_path, _initialised
    _db_path = Path(path)
    _initialised = False
    close_thread_connection()


def db_path() -> Path:
    return _db_path


# --------------------------------------------------------------------- conn
def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 8000")
    conn.execute("PRAGMA cache_size = -32000")   # ~32 Mo de cache page
    conn.execute("PRAGMA temp_store = MEMORY")


def connection() -> sqlite3.Connection:
    """Connexion propre au thread courant (créée à la demande)."""
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == _db_path:
        return conn
    close_thread_connection()
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path), timeout=15, check_same_thread=False)
    _configure(conn)
    _local.conn = conn
    _local.path = _db_path
    return conn


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _local.conn = None
    _local.path = None


@contextmanager
def transaction():
    """Transaction explicite : commit en sortie, rollback sur exception."""
    conn = connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        # déjà dans une transaction : on se greffe dessus (savepoint)
        conn.execute("SAVEPOINT nested")
        try:
            yield conn
            conn.execute("RELEASE nested")
        except Exception:
            conn.execute("ROLLBACK TO nested")
            raise
        return
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(force: bool = False) -> None:
    """Applique le schéma (idempotent)."""
    global _initialised
    with _init_lock:
        if _initialised and not force:
            return
        conn = connection()
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (1,)
        )
        conn.commit()
        _initialised = True


# ------------------------------------------------------------------ requêtes
def query(sql: str, params: Sequence[Any] | dict = ()) -> list[dict]:
    cur = connection().execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def query_one(sql: str, params: Sequence[Any] | dict = ()) -> dict | None:
    cur = connection().execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def scalar(sql: str, params: Sequence[Any] | dict = (), default: Any = None) -> Any:
    cur = connection().execute(sql, params)
    row = cur.fetchone()
    cur.close()
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql: str, params: Sequence[Any] | dict = ()) -> sqlite3.Cursor:
    conn = connection()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    conn = connection()
    conn.executemany(sql, seq)
    conn.commit()


def insert(table: str, data: dict, replace: bool = False) -> int:
    """INSERT générique ; renvoie le rowid."""
    data = {k: v for k, v in data.items() if v is not None}
    if not data:
        raise ValueError("insert() appelé sans donnée")
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    cur = connection().execute(
        f"{verb} INTO {table} ({cols}) VALUES ({marks})", list(data.values())
    )
    connection().commit()
    return int(cur.lastrowid)


def upsert(table: str, data: dict, conflict: Sequence[str]) -> None:
    """INSERT ... ON CONFLICT(...) DO UPDATE, sur les colonnes fournies."""
    cols = list(data)
    updates = [c for c in cols if c not in conflict]
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT({', '.join(conflict)}) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in updates)
    )
    conn = connection()
    conn.execute(sql, [data[c] for c in cols])
    conn.commit()


def update(table: str, row_id: int, data: dict, key: str = "id") -> int:
    data = {k: v for k, v in data.items() if k != key}
    if not data:
        return 0
    sets = ", ".join(f"{c} = ?" for c in data)
    cur = connection().execute(
        f"UPDATE {table} SET {sets} WHERE {key} = ?", [*data.values(), row_id]
    )
    connection().commit()
    return cur.rowcount


def delete(table: str, row_id: int, key: str = "id") -> int:
    cur = connection().execute(f"DELETE FROM {table} WHERE {key} = ?", (row_id,))
    connection().commit()
    return cur.rowcount


# --------------------------------------------------------------- flux (blob)
def pack_stream(values: Sequence[Any]) -> bytes:
    """Sérialise une série temporelle : JSON compact + zlib (~8× plus petit).

    Les flottants sont arrondis au millième — au-delà, on stockerait du bruit
    de mesure et le JSON gonflerait de moitié. Les séries entières (cadence,
    fréquence cardiaque, temps) sautent l'arrondi : sur une séance longue,
    cela épargne plusieurs millions d'appels de fonction.
    """
    has_floats = any(isinstance(v, float) for v in values[:64])
    payload = json.dumps(
        [None if v is None else round(v, 3) for v in values] if has_floats
        else values,
        separators=(",", ":"),
    ).encode("utf-8")
    return zlib.compress(payload, 6)


def unpack_stream(blob: bytes) -> list:
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def save_streams(activity_id: int, streams: dict[str, Sequence[Any]],
                 sample_rate: float = 1.0) -> None:
    conn = connection()
    conn.execute("DELETE FROM activity_streams WHERE activity_id = ?", (activity_id,))
    rows = []
    for kind, values in streams.items():
        if not values:
            continue
        rows.append((activity_id, kind, sample_rate, len(values),
                     "zlib+json", pack_stream(values)))
    if rows:
        conn.executemany(
            "INSERT INTO activity_streams"
            " (activity_id, kind, sample_rate, n_samples, encoding, data)"
            " VALUES (?,?,?,?,?,?)",
            rows,
        )
        conn.execute("UPDATE activities SET has_streams = 1 WHERE id = ?", (activity_id,))
    conn.commit()


def load_streams(activity_id: int, kinds: Sequence[str] | None = None) -> dict[str, list]:
    sql = "SELECT kind, data FROM activity_streams WHERE activity_id = ?"
    params: list[Any] = [activity_id]
    if kinds:
        sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
        params.extend(kinds)
    return {r["kind"]: unpack_stream(r["data"]) for r in query(sql, params)}


# ------------------------------------------------------------------ settings
def get_setting(key: str, default: Any = None) -> Any:
    raw = scalar("SELECT value FROM settings WHERE key = ?", (key,))
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def set_setting(key: str, value: Any) -> None:
    upsert(
        "settings",
        {"key": key, "value": json.dumps(value, ensure_ascii=False),
         "updated_at": now_iso()},
        ["key"],
    )


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_stats() -> dict:
    """Statistiques de volumétrie pour la page Réglages."""
    tables = [
        "athletes", "activities", "activity_streams", "wellness",
        "daily_load", "best_efforts", "planned_workouts", "events",
        "lab_tests", "injuries", "alerts", "devices", "coach_notes",
    ]
    counts = {}
    for t in tables:
        try:
            counts[t] = scalar(f"SELECT COUNT(*) FROM {t}", default=0)
        except sqlite3.Error:
            counts[t] = 0
    size = _db_path.stat().st_size if _db_path.exists() else 0
    return {
        "path": str(_db_path),
        "size_bytes": size,
        "size_mb": round(size / 1_048_576, 2),
        "counts": counts,
        "sqlite_version": sqlite3.sqlite_version,
    }
