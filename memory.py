"""Memoire persistante de Jarvis (SQLite locale, dossier data/, jamais versionne).

Tables : journal des interactions, faits retenus, corrections apprises (phrase -> phrase voulue).
"""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "jarvis.db"
RETENTION_DAYS = 180

UNDONE = -2  # valeur de `feedback` pour une interaction deja annulee


class Memory:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions(
                    id INTEGER PRIMARY KEY, ts REAL, heard TEXT, rewritten TEXT, handled_by TEXT,
                    actions TEXT, reply TEXT, ok INTEGER, feedback INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS facts(
                    id INTEGER PRIMARY KEY, ts REAL, key TEXT, text TEXT);
                CREATE TABLE IF NOT EXISTS aliases(
                    phrase TEXT PRIMARY KEY, target TEXT, ts REAL, uses INTEGER DEFAULT 0);
                """
            )

    def _run(self, sql: str, args: tuple = ()) -> list:
        with self._lock, self._db:
            return self._db.execute(sql, args).fetchall()

    # --- interactions ---
    def log_interaction(self, heard: str, rewritten: str, handled_by: str, actions: list, reply: str) -> int:
        ok = 1 if all(a.get("ok") for a in actions) else 0
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO interactions(ts, heard, rewritten, handled_by, actions, reply, ok) VALUES(?,?,?,?,?,?,?)",
                (time.time(), heard, rewritten, handled_by, json.dumps(actions, ensure_ascii=False), reply, ok))
            return cur.lastrowid

    def set_feedback(self, interaction_id: int, value: int) -> None:
        self._run("UPDATE interactions SET feedback=? WHERE id=?", (value, interaction_id))

    def last_interactions(self, n: int = 1, with_actions: bool = False, skip_undone: bool = True) -> list:
        sql = "SELECT id, heard, rewritten, handled_by, actions, reply, ok, feedback, ts FROM interactions"
        cond = []
        if with_actions:
            cond.append("actions != '[]'")
        if skip_undone:
            cond.append(f"feedback != {UNDONE}")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        rows = self._run(sql + " ORDER BY id DESC LIMIT ?", (n,))
        return [dict(id=r[0], heard=r[1], rewritten=r[2], handled_by=r[3], actions=json.loads(r[4]),
                     reply=r[5], ok=bool(r[6]), feedback=r[7], ts=r[8]) for r in rows]

    def interactions_before(self, interaction_id: int, tool: str, action: str, n: int = 1) -> list:
        rows = self._run("SELECT id, actions FROM interactions WHERE id < ? AND actions LIKE ? ORDER BY id DESC LIMIT 50",
                         (interaction_id, f'%"{action}"%'))
        out = []
        for rid, acts in rows:
            for a in json.loads(acts):
                if a.get("tool") == tool and a.get("args", {}).get("action") == action and a.get("ok"):
                    out.append(a)
        return out[:n]

    def recent_turns(self, n: int = 6, max_age_hours: float = 12) -> list:
        """Derniers echanges recents (les vieux echanges hors sujet ou parasites ne polluent pas la conversation)."""
        rows = self._run("SELECT heard, reply FROM interactions WHERE reply != '' AND ts > ? AND handled_by != 'meta' "
                         "ORDER BY id DESC LIMIT ?", (time.time() - max_age_hours * 3600, n))
        return list(reversed(rows))

    def all_actions(self) -> list:
        rows = self._run("SELECT actions, ok, feedback, handled_by FROM interactions")
        return [(json.loads(a), ok, fb, by) for a, ok, fb, by in rows]

    def count(self) -> int:
        return self._run("SELECT COUNT(*) FROM interactions")[0][0]

    # --- faits ---
    def add_fact(self, text: str, key: Optional[str] = None) -> None:
        if key:
            self._run("DELETE FROM facts WHERE key=?", (key,))
        elif self._run("SELECT 1 FROM facts WHERE text=?", (text,)):
            return
        self._run("INSERT INTO facts(ts, key, text) VALUES(?,?,?)", (time.time(), key, text))

    def facts(self) -> list:
        return [dict(key=k, text=t) for k, t in self._run("SELECT key, text FROM facts ORDER BY id")]

    def forget_facts(self, needle: str) -> int:
        n = len(self._run("SELECT 1 FROM facts WHERE lower(text) LIKE ?", (f"%{needle.lower()}%",)))
        self._run("DELETE FROM facts WHERE lower(text) LIKE ?", (f"%{needle.lower()}%",))
        return n

    def name(self) -> Optional[str]:
        rows = self._run("SELECT text FROM facts WHERE key='name'")
        return rows[0][0] if rows else None

    # --- corrections apprises ---
    def add_alias(self, phrase: str, target: str) -> None:
        self._run("INSERT INTO aliases(phrase, target, ts, uses) VALUES(?,?,?,0) "
                  "ON CONFLICT(phrase) DO UPDATE SET target=excluded.target, ts=excluded.ts", (phrase, target, time.time()))

    def get_alias(self, phrase: str) -> Optional[str]:
        rows = self._run("SELECT target FROM aliases WHERE phrase=?", (phrase,))
        if rows:
            self._run("UPDATE aliases SET uses = uses + 1 WHERE phrase=?", (phrase,))
            return rows[0][0]
        return None

    def aliases(self) -> list:
        return [dict(phrase=p, target=t, uses=u) for p, t, u in
                self._run("SELECT phrase, target, uses FROM aliases ORDER BY ts DESC")]

    def delete_last_alias(self) -> Optional[dict]:
        rows = self._run("SELECT phrase, target FROM aliases ORDER BY ts DESC LIMIT 1")
        if not rows:
            return None
        self._run("DELETE FROM aliases WHERE phrase=?", (rows[0][0],))
        return dict(phrase=rows[0][0], target=rows[0][1])

    # --- entretien ---
    def prune(self) -> None:
        self._run("DELETE FROM interactions WHERE ts < ?", (time.time() - RETENTION_DAYS * 86400,))

    def forget_everything(self) -> None:
        with self._lock, self._db:
            self._db.executescript("DELETE FROM interactions; DELETE FROM facts; DELETE FROM aliases;")
