from __future__ import annotations

import json
import os
import re
import sqlite3
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class LearnedRoute:
    kind: str
    intent: str
    commands: tuple[str, ...]
    confidence: float
    successes: int
    failures: int


class ExperienceEngine:
    """Memoria operacional local, auditavel e reversivel do JARVIS.

    O motor nao altera codigo e nao executa ferramentas. Ele registra o que foi
    entendido/executado, consolida frases que tiveram sucesso verificavel e pode
    devolver apenas rotas exatas ja confiaveis. Generalizacoes continuam sob o
    Router/Entity Resolver para evitar transformar coincidencias em comandos.
    """

    SAFE_LEARN_PREFIXES = (
        "v8:social_chat",
        "v8:time",
        "v8:date",
        "v8:ram",
        "v8:cpu",
        "v8:active_window",
        "v8:open_windows",
        "v8:volume",
        "v8:microphone",
        "v8:monitors",
        "v8:capabilities",
        "v8:screenshot",
        "descreve ",
        "abre ",
        "abra ",
        "abrir ",
        "minimiza ",
        "minimize ",
        "maximiza ",
        "maximize ",
        "expande ",
        "restaura ",
        "move ",
        "mova ",
        "coloca ",
        "v8:open_site_in_app:",
        "v8:browser_search:",
        "v8:move_other:",
        "abra o site ",
    )
    BLOCKED_LEARN_TOKENS = (
        "fecha ", "feche ", "fechar ", "apaga", "delete", "exclu",
        "format", "shutdown", "desliga", "reinicia", "powershell", "cmd ",
    )
    CORRECTION_RE = re.compile(
        r"^(?:(?:nao|não)$|nao foi|não foi|nao funcionou|não funcionou|nao deu certo|não deu certo|"
        r"deu errado|isso nao funcionou|isso não funcionou|ta errado|tá errado|esta errado|está errado|errou|"
        r"quis dizer|eu quis dizer|na verdade|corrigindo|correcao|correção)\b",
        re.I,
    )

    def __init__(self, project_dir: str | Path, logger=None):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "jarvis_experience.db"
        legacy_db = self.data_dir / "zero_experience.db"
        if not self.db_path.exists() and legacy_db.exists():
            try:
                shutil.copy2(legacy_db, self.db_path)
            except Exception:
                self.db_path = legacy_db
        self._lock = threading.RLock()
        self._last_experience_by_conversation: dict[int, int] = {}
        self.repair_notice = ""
        self.conn = self._open_with_repair()

    @staticmethod
    def normalize(text: str) -> str:
        raw = unicodedata.normalize("NFKD", str(text or ""))
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).lower()
        raw = re.sub(r"[^a-z0-9% ]+", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=4.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _quarantine_corrupt_db(self) -> Optional[Path]:
        """Preserva o banco operacional corrompido e libera um banco novo.

        A memoria de conversa usa outro arquivo (jarvis_memory.db), portanto este
        reparo nao apaga conversas. WAL/SHM do banco quebrado tambem sao isolados.
        """
        if not self.db_path.exists():
            return None
        stamp = time.strftime("%Y%m%d_%H%M%S")
        quarantine = self.db_path.with_name(f"{self.db_path.stem}.corrupt_{stamp}{self.db_path.suffix}")
        try:
            os.replace(self.db_path, quarantine)
        except Exception:
            try:
                shutil.copy2(self.db_path, quarantine)
                self.db_path.unlink()
            except Exception:
                return None
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.db_path) + suffix)
            if sidecar.exists():
                try:
                    os.replace(sidecar, Path(str(quarantine) + suffix))
                except Exception:
                    try:
                        sidecar.unlink()
                    except Exception:
                        pass
        return quarantine

    def _open_with_repair(self):
        conn = None
        try:
            conn = self._connect()
            self.conn = conn
            self._configure()
            # quick_check detecta corrupcao antes de qualquer aprendizado novo.
            row = conn.execute("PRAGMA quick_check").fetchone()
            if row is not None and str(row[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"quick_check={row[0]}")
            self._init_schema()
            return conn
        except sqlite3.DatabaseError as exc:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            error_key = str(exc or "").lower()
            corruption_markers = (
                "malformed", "file is not a database", "database disk image",
                "database schema is corrupt", "quick_check=",
            )
            if not any(marker in error_key for marker in corruption_markers):
                raise
            quarantined = self._quarantine_corrupt_db()
            if quarantined is None:
                raise
            self.repair_notice = f"banco operacional corrompido preservado em {quarantined.name}; novo banco criado"
            if self.logger:
                try:
                    self.logger.warning(
                        f"Experience Engine autorreparado: {self.repair_notice}. Motivo: {exc}",
                        "EXPERIENCE",
                    )
                except Exception:
                    pass
            conn = self._connect()
            self.conn = conn
            self._configure()
            self._init_schema()
            return conn

    def _configure(self) -> None:
        with self._lock:
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    finished_at REAL,
                    conversation_id INTEGER,
                    source TEXT NOT NULL DEFAULT 'text',
                    input_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    route_kind TEXT,
                    intent TEXT,
                    commands_json TEXT NOT NULL DEFAULT '[]',
                    success INTEGER,
                    verified INTEGER,
                    corrected INTEGER NOT NULL DEFAULT 0,
                    error_reason TEXT,
                    duration_ms REAL
                );
                CREATE INDEX IF NOT EXISTS idx_experience_phrase
                    ON experiences(normalized_text, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_experience_intent
                    ON experiences(intent, created_at DESC);

                CREATE TABLE IF NOT EXISTS phrase_memory (
                    normalized_text TEXT PRIMARY KEY,
                    example_text TEXT NOT NULL,
                    route_kind TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    commands_json TEXT NOT NULL,
                    successes INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    verified_successes INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.50,
                    status TEXT NOT NULL DEFAULT 'observed',
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    conversation_id INTEGER,
                    experience_id INTEGER,
                    correction_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    FOREIGN KEY(experience_id) REFERENCES experiences(id)
                );
                """
            )
            self.conn.commit()

    @classmethod
    def _commands_safe_to_learn(cls, commands: Sequence[str]) -> bool:
        if not commands:
            return False
        for command in commands:
            key = cls.normalize(command)
            if any(token in key for token in cls.BLOCKED_LEARN_TOKENS):
                return False
            raw = str(command or "").strip().lower()
            if not any(raw.startswith(prefix) for prefix in cls.SAFE_LEARN_PREFIXES):
                return False
        return True

    def begin(
        self,
        input_text: str,
        *,
        source: str = "text",
        conversation_id: Optional[int] = None,
        route_kind: str = "",
        intent: str = "",
        commands: Optional[Iterable[str]] = None,
    ) -> int:
        commands_list = [str(x) for x in (commands or [])]
        now = time.time()
        normalized = self.normalize(input_text)
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO experiences(
                    created_at, conversation_id, source, input_text,
                    normalized_text, route_kind, intent, commands_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    int(conversation_id) if conversation_id else None,
                    str(source or "text"),
                    str(input_text or ""),
                    normalized,
                    str(route_kind or ""),
                    str(intent or ""),
                    json.dumps(commands_list, ensure_ascii=False),
                ),
            )
            experience_id = int(cur.lastrowid)
            self.conn.commit()
            if conversation_id:
                self._last_experience_by_conversation[int(conversation_id)] = experience_id
            return experience_id

    def finish(
        self,
        experience_id: Optional[int],
        *,
        success: Optional[bool],
        verified: Optional[bool],
        duration_ms: Optional[float] = None,
        error_reason: str = "",
    ) -> None:
        if not experience_id:
            return
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM experiences WHERE id=?", (int(experience_id),)
            ).fetchone()
            if not row:
                return
            self.conn.execute(
                """
                UPDATE experiences
                   SET finished_at=?, success=?, verified=?, error_reason=?, duration_ms=?
                 WHERE id=?
                """,
                (
                    time.time(),
                    None if success is None else int(bool(success)),
                    None if verified is None else int(bool(verified)),
                    str(error_reason or ""),
                    None if duration_ms is None else float(duration_ms),
                    int(experience_id),
                ),
            )
            self._update_phrase_memory(row, success=success, verified=verified)
            self.conn.commit()

    def _update_phrase_memory(self, row, *, success: Optional[bool], verified: Optional[bool]) -> None:
        normalized = str(row["normalized_text"] or "")
        intent = str(row["intent"] or "")
        kind = str(row["route_kind"] or "")
        try:
            commands = [str(x) for x in json.loads(row["commands_json"] or "[]")]
        except Exception:
            commands = []
        if not normalized or kind != "local" or not self._commands_safe_to_learn(commands):
            return

        now = time.time()
        current = self.conn.execute(
            "SELECT * FROM phrase_memory WHERE normalized_text=?", (normalized,)
        ).fetchone()
        same_route = bool(
            current
            and str(current["intent"] or "") == intent
            and str(current["commands_json"] or "") == json.dumps(commands, ensure_ascii=False)
        )

        if current and not same_route:
            # Conflito semantico: nunca promove silenciosamente duas interpretacoes
            # diferentes da mesma frase.
            failures = int(current["failures"] or 0) + 1
            confidence = max(0.10, float(current["confidence"] or 0.50) - 0.18)
            self.conn.execute(
                "UPDATE phrase_memory SET failures=?, confidence=?, status='conflicted', last_seen=? WHERE normalized_text=?",
                (failures, confidence, now, normalized),
            )
            return

        successes = int(current["successes"] or 0) if current else 0
        failures = int(current["failures"] or 0) if current else 0
        verified_successes = int(current["verified_successes"] or 0) if current else 0
        if success is True:
            successes += 1
            if verified is True:
                verified_successes += 1
        elif success is False:
            failures += 1

        # Beta conservadora: duas execucoes verificadas sem falha = trusted.
        evidence = verified_successes * 1.35 + max(successes - verified_successes, 0) * 0.35
        confidence = min(0.99, max(0.05, 0.50 + evidence * 0.16 - failures * 0.22))
        if failures and failures >= successes:
            status = "conflicted"
        elif verified_successes >= 2 and failures == 0 and confidence >= 0.86:
            status = "trusted"
        elif verified_successes >= 1:
            status = "candidate"
        else:
            status = "observed"

        payload = (
            str(row["input_text"] or normalized), kind, intent,
            json.dumps(commands, ensure_ascii=False), successes, failures,
            verified_successes, confidence, status,
            float(current["first_seen"]) if current else now, now, normalized,
        )
        self.conn.execute(
            """
            INSERT INTO phrase_memory(
                example_text, route_kind, intent, commands_json, successes,
                failures, verified_successes, confidence, status, first_seen,
                last_seen, normalized_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_text) DO UPDATE SET
                example_text=excluded.example_text,
                route_kind=excluded.route_kind,
                intent=excluded.intent,
                commands_json=excluded.commands_json,
                successes=excluded.successes,
                failures=excluded.failures,
                verified_successes=excluded.verified_successes,
                confidence=excluded.confidence,
                status=excluded.status,
                last_seen=excluded.last_seen
            """,
            payload,
        )

    def lookup(self, input_text: str) -> Optional[LearnedRoute]:
        normalized = self.normalize(input_text)
        if not normalized:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM phrase_memory WHERE normalized_text=?", (normalized,)
            ).fetchone()
        if not row or str(row["status"]) != "trusted" or float(row["confidence"] or 0) < 0.86:
            return None
        try:
            commands = tuple(str(x) for x in json.loads(row["commands_json"] or "[]"))
        except Exception:
            return None
        # A rota aprendida e usada apenas como fallback de uma unica acao.
        # Multi-planos continuam sempre no planner atual, que preserva dependencias.
        if len(commands) != 1 or not self._commands_safe_to_learn(commands):
            return None
        return LearnedRoute(
            kind=str(row["route_kind"]),
            intent=str(row["intent"]),
            commands=commands,
            confidence=float(row["confidence"]),
            successes=int(row["successes"]),
            failures=int(row["failures"]),
        )

    def maybe_record_correction(self, text: str, *, conversation_id: Optional[int] = None) -> bool:
        raw = str(text or "").strip()
        if not raw or not self.CORRECTION_RE.match(raw):
            return False
        experience_id = None
        if conversation_id:
            experience_id = self._last_experience_by_conversation.get(int(conversation_id))
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO corrections(created_at, conversation_id, experience_id, correction_text, normalized_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    int(conversation_id) if conversation_id else None,
                    experience_id,
                    raw,
                    self.normalize(raw),
                ),
            )
            if experience_id:
                # A correção do usuário tem prioridade sobre o verificador.
                # Marca a experiência anterior como falha e despromove a frase
                # aprendida correspondente, sem apagar o histórico.
                previous = self.conn.execute(
                    "SELECT normalized_text FROM experiences WHERE id=?", (experience_id,)
                ).fetchone()
                self.conn.execute(
                    """
                    UPDATE experiences
                       SET corrected=1, success=0, verified=0,
                           error_reason=CASE
                               WHEN error_reason IS NULL OR error_reason='' THEN 'user_correction'
                               ELSE error_reason || ';user_correction'
                           END
                     WHERE id=?
                    """,
                    (experience_id,),
                )
                if previous and previous["normalized_text"]:
                    normalized_prev = str(previous["normalized_text"])
                    row = self.conn.execute(
                        "SELECT * FROM phrase_memory WHERE normalized_text=?",
                        (normalized_prev,),
                    ).fetchone()
                    if row:
                        successes = max(0, int(row["successes"] or 0) - 1)
                        verified_successes = max(0, int(row["verified_successes"] or 0) - 1)
                        failures = int(row["failures"] or 0) + 1
                        confidence = max(0.05, float(row["confidence"] or 0.50) - 0.30)
                        self.conn.execute(
                            """
                            UPDATE phrase_memory
                               SET successes=?, verified_successes=?, failures=?,
                                   confidence=?, status='conflicted', last_seen=?
                             WHERE normalized_text=?
                            """,
                            (successes, verified_successes, failures, confidence, time.time(), normalized_prev),
                        )
            self.conn.commit()
        return True

    def stats(self) -> dict:
        with self._lock:
            total = int(self.conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0])
            corrections = int(self.conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0])
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM phrase_memory GROUP BY status"
            ).fetchall()
        states = {str(row["status"]): int(row["n"]) for row in rows}
        return {
            "experiences": total,
            "corrections": corrections,
            "phrases": sum(states.values()),
            "trusted": states.get("trusted", 0),
            "candidate": states.get("candidate", 0),
            "conflicted": states.get("conflicted", 0),
        }

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.commit()
            finally:
                self.conn.close()


__all__ = ["ExperienceEngine", "LearnedRoute"]
