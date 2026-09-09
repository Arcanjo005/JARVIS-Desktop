from __future__ import annotations

"""Memoria comportamental V2 local e conservadora.

Registra somente metadados: transicoes de apps, comandos verificados e preferencias
de player por faixa de horario. Nunca salva audio, tela, teclas ou texto livre.
Padroes viram sugestoes; nunca sao executados automaticamente sem regra explicita.
"""

import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional


class BehaviorMemory:
    MIN_PATTERN_COUNT = 5
    MIN_ACTION_COUNT = 4
    SUGGEST_COOLDOWN_DAYS = 10

    def __init__(self, project_dir: str | Path, logger=None):
        self.project_dir = Path(project_dir)
        self.logger = logger
        data = self.project_dir / "data"
        data.mkdir(parents=True, exist_ok=True)
        self.db_path = data / "jarvis_behavior.db"
        self._lock = threading.RLock()
        self._recent_apps = deque(maxlen=3)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=3.0)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_transitions (
                    from_app TEXT NOT NULL,
                    to_app TEXT NOT NULL,
                    hour_bucket INTEGER NOT NULL,
                    weekday_group INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_suggested REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (from_app, to_app, hour_bucket, weekday_group)
                );
                CREATE INDEX IF NOT EXISTS idx_behavior_count
                    ON app_transitions(count DESC, last_seen DESC);

                CREATE TABLE IF NOT EXISTS app_sequences (
                    app_a TEXT NOT NULL,
                    app_b TEXT NOT NULL,
                    app_c TEXT NOT NULL,
                    hour_bucket INTEGER NOT NULL,
                    weekday_group INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_suggested REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (app_a, app_b, app_c, hour_bucket, weekday_group)
                );
                CREATE INDEX IF NOT EXISTS idx_behavior_seq_count
                    ON app_sequences(count DESC, last_seen DESC);

                CREATE TABLE IF NOT EXISTS action_patterns (
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    context_app TEXT NOT NULL,
                    hour_bucket INTEGER NOT NULL,
                    weekday_group INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_suggested REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (action,target,context_app,hour_bucket,weekday_group)
                );
                CREATE INDEX IF NOT EXISTS idx_behavior_action_count
                    ON action_patterns(count DESC,last_seen DESC);
                """
            )
            self.conn.commit()

    @staticmethod
    def _clean_app(value: str) -> str:
        app = " ".join(str(value or "").split()).strip()[:100]
        if app.lower() in {"", "desktop", "program manager", "jarvis", "jarvis.exe", "python", "pythonw"}:
            return ""
        return app

    @staticmethod
    def _clean_token(value: str, limit: int = 100) -> str:
        return " ".join(str(value or "").split()).strip()[:limit]

    @staticmethod
    def _bucket(ts: Optional[float] = None) -> tuple[int, int]:
        lt = time.localtime(float(ts or time.time()))
        return int(lt.tm_hour // 4), 0 if lt.tm_wday < 5 else 1

    def _maybe_suggest(self, table: str, where: tuple, row: sqlite3.Row, now: float, threshold: int) -> bool:
        if not row or int(row["count"]) < threshold:
            return False
        cooldown = self.SUGGEST_COOLDOWN_DAYS * 86400.0
        if now - float(row["last_suggested"] or 0) < cooldown:
            return False
        if table == "app_transitions":
            self.conn.execute(
                "UPDATE app_transitions SET last_suggested=? WHERE from_app=? AND to_app=? AND hour_bucket=? AND weekday_group=?",
                (now, *where),
            )
        elif table == "app_sequences":
            self.conn.execute(
                "UPDATE app_sequences SET last_suggested=? WHERE app_a=? AND app_b=? AND app_c=? AND hour_bucket=? AND weekday_group=?",
                (now, *where),
            )
        else:
            self.conn.execute(
                "UPDATE action_patterns SET last_suggested=? WHERE action=? AND target=? AND context_app=? AND hour_bucket=? AND weekday_group=?",
                (now, *where),
            )
        self.conn.commit()
        return True

    def observe_transition(self, from_app: str, to_app: str, ts: Optional[float] = None) -> Optional[Dict]:
        source = self._clean_app(from_app)
        target = self._clean_app(to_app)
        if not source or not target or source.lower() == target.lower():
            return None
        now = float(ts or time.time())
        hour_bucket, weekday_group = self._bucket(now)
        suggestion = None
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO app_transitions
                    (from_app,to_app,hour_bucket,weekday_group,count,first_seen,last_seen,last_suggested)
                VALUES (?,?,?,?,1,?,?,0)
                ON CONFLICT(from_app,to_app,hour_bucket,weekday_group)
                DO UPDATE SET count=count+1,last_seen=excluded.last_seen
                """,
                (source, target, hour_bucket, weekday_group, now, now),
            )
            row = self.conn.execute(
                "SELECT * FROM app_transitions WHERE from_app=? AND to_app=? AND hour_bucket=? AND weekday_group=?",
                (source, target, hour_bucket, weekday_group),
            ).fetchone()
            self.conn.commit()
            if self._maybe_suggest("app_transitions", (source, target, hour_bucket, weekday_group), row, now, self.MIN_PATTERN_COUNT):
                suggestion = {"kind": "transition", "from_app": source, "to_app": target, "count": int(row["count"]), "hour_bucket": hour_bucket, "weekend": bool(weekday_group)}

            # Sequencia de 3 apps: A -> B -> C.
            if not self._recent_apps or self._recent_apps[-1].lower() != source.lower():
                self._recent_apps.append(source)
            self._recent_apps.append(target)
            if len(self._recent_apps) == 3:
                a, b, c = tuple(self._recent_apps)
                if len({a.lower(), b.lower(), c.lower()}) >= 2:
                    self.conn.execute(
                        """
                        INSERT INTO app_sequences(app_a,app_b,app_c,hour_bucket,weekday_group,count,first_seen,last_seen,last_suggested)
                        VALUES (?,?,?,?,?,1,?,?,0)
                        ON CONFLICT(app_a,app_b,app_c,hour_bucket,weekday_group)
                        DO UPDATE SET count=count+1,last_seen=excluded.last_seen
                        """,
                        (a, b, c, hour_bucket, weekday_group, now, now),
                    )
                    seq = self.conn.execute(
                        "SELECT * FROM app_sequences WHERE app_a=? AND app_b=? AND app_c=? AND hour_bucket=? AND weekday_group=?",
                        (a, b, c, hour_bucket, weekday_group),
                    ).fetchone()
                    self.conn.commit()
                    if suggestion is None and self._maybe_suggest("app_sequences", (a, b, c, hour_bucket, weekday_group), seq, now, self.MIN_PATTERN_COUNT):
                        suggestion = {"kind": "sequence", "apps": [a, b, c], "count": int(seq["count"]), "hour_bucket": hour_bucket, "weekend": bool(weekday_group)}
        return suggestion

    def observe_action(self, action: str, target: str = "", context_app: str = "", ts: Optional[float] = None) -> Optional[Dict]:
        action = self._clean_token(str(action or "").upper(), 60)
        target = self._clean_token(target, 100)
        context_app = self._clean_app(context_app)
        if not action or action in {"CONVERSATION", "SOCIAL_CHAT", "USER_SUCCESS", "USER_CORRECTION"}:
            return None
        # Não aprende conteúdo potencialmente sensível.
        if action in {"DELETE", "POWER", "PASSWORD", "PAYMENT", "INSTALL"}:
            return None
        now = float(ts or time.time())
        hour_bucket, weekday_group = self._bucket(now)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO action_patterns(action,target,context_app,hour_bucket,weekday_group,count,first_seen,last_seen,last_suggested)
                VALUES (?,?,?,?,?,1,?,?,0)
                ON CONFLICT(action,target,context_app,hour_bucket,weekday_group)
                DO UPDATE SET count=count+1,last_seen=excluded.last_seen
                """,
                (action, target, context_app, hour_bucket, weekday_group, now, now),
            )
            row = self.conn.execute(
                "SELECT * FROM action_patterns WHERE action=? AND target=? AND context_app=? AND hour_bucket=? AND weekday_group=?",
                (action, target, context_app, hour_bucket, weekday_group),
            ).fetchone()
            self.conn.commit()
            if self._maybe_suggest("action_patterns", (action, target, context_app, hour_bucket, weekday_group), row, now, self.MIN_ACTION_COUNT):
                return {"kind": "action", "action": action, "target": target, "context_app": context_app, "count": int(row["count"]), "hour_bucket": hour_bucket, "weekend": bool(weekday_group)}
        return None

    def top_patterns(self, limit: int = 8) -> List[Dict]:
        limit = max(1, min(int(limit), 30))
        with self._lock:
            rows = self.conn.execute(
                """SELECT from_app,to_app,hour_bucket,weekday_group,count,last_seen
                   FROM app_transitions WHERE count>=?
                   ORDER BY count DESC,last_seen DESC LIMIT ?""",
                (self.MIN_PATTERN_COUNT, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def top_sequences(self, limit: int = 6) -> List[Dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT app_a,app_b,app_c,count,hour_bucket,weekday_group,last_seen FROM app_sequences WHERE count>=? ORDER BY count DESC,last_seen DESC LIMIT ?",
                (self.MIN_PATTERN_COUNT, max(1, min(int(limit), 20))),
            ).fetchall()
        return [dict(row) for row in rows]

    def top_actions(self, limit: int = 8) -> List[Dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT action,target,context_app,count,hour_bucket,weekday_group,last_seen FROM action_patterns WHERE count>=? ORDER BY count DESC,last_seen DESC LIMIT ?",
                (self.MIN_ACTION_COUNT, max(1, min(int(limit), 30))),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> Dict:
        with self._lock:
            trans = self.conn.execute("SELECT COUNT(*) AS patterns, COALESCE(SUM(count),0) AS observations FROM app_transitions").fetchone()
            seq = self.conn.execute("SELECT COUNT(*) AS patterns, COALESCE(SUM(count),0) AS observations FROM app_sequences").fetchone()
            act = self.conn.execute("SELECT COUNT(*) AS patterns, COALESCE(SUM(count),0) AS observations FROM action_patterns").fetchone()
        return {
            "patterns": int(trans["patterns"]), "observations": int(trans["observations"]),
            "sequences": int(seq["patterns"]), "action_patterns": int(act["patterns"]),
            "db": str(self.db_path), "version": 2,
        }

    def close(self):
        with self._lock:
            try: self.conn.close()
            except Exception: pass


__all__ = ["BehaviorMemory"]
