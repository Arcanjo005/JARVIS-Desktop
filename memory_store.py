"""
JARVIS - Memória Persistente Local
================================

Banco SQLite local para:
- salvar todas as conversas;
- restaurar a última conversa ao abrir o JARVIS;
- manter múltiplas sessões;
- recuperar trechos antigos relevantes;
- guardar memórias persistentes do usuário;
- funcionar sem serviços externos.

Banco:
    data/jarvis_memory.db
"""

import os
import re
import sqlite3
import threading
import hashlib
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class MemoryStore:
    DB_VERSION = 3

    def __init__(self, logger=None, db_path: Optional[str] = None):
        self.logger = logger
        self._lock = threading.RLock()
        self.recovery_notice = ""

        if db_path:
            self.db_path = db_path
        else:
            app_dir = os.environ.get("JARVIS_APP_DIR") or os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(app_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            canonical = os.path.join(data_dir, "jarvis_memory.db")
            legacy = os.path.join(data_dir, "zero_memory.db")
            # Migração não destrutiva: preserva o banco antigo como legado e
            # passa a trabalhar no banco JARVIS.
            if not os.path.exists(canonical) and os.path.exists(legacy):
                try:
                    shutil.copy2(legacy, canonical)
                except Exception:
                    canonical = legacy
            self.db_path = canonical

        self._ephemeral = str(self.db_path) == ":memory:"
        if not self._ephemeral:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._prepare_database_health()
        self.conn = self._open_connection()

        try:
            self._configure()
            self._create_schema()
        except sqlite3.DatabaseError as exc:
            # Se a corrupção só aparecer ao tocar no schema, preserva o banco e
            # recria uma base limpa. Memória nunca derruba a interface/TTS.
            try:
                self.conn.close()
            except Exception:
                pass
            if not self._ephemeral:
                self._quarantine_corrupt_database(f"schema: {exc}")
            self.conn = self._open_connection()
            self._configure()
            self._create_schema()

    # =========================================================
    # BANCO
    # =========================================================

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "MEMORY")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _open_connection(self):
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=15
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _quick_check_path(self, path: str) -> tuple[bool, str]:
        if not os.path.isfile(path):
            return True, "novo"
        conn = None
        try:
            # mode=ro evita qualquer escrita durante o diagnóstico.
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            row = conn.execute("PRAGMA quick_check").fetchone()
            text = str(row[0] if row else "sem resultado")
            return text.lower() == "ok", text
        except Exception as exc:
            return False, str(exc)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def _corrupt_recovery_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        root = Path(self.db_path).parent / "recovery"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"jarvis_memory_corrupt_{stamp}.db"

    def _try_recover_database(self, source: Path, destination: Path) -> bool:
        """Tenta recuperação conservadora via iterdump; só aceita quick_check=ok."""
        source_conn = dest_conn = None
        try:
            source_conn = sqlite3.connect(str(source), timeout=5)
            dump = "\n".join(source_conn.iterdump())
            if not dump.strip():
                return False
            if destination.exists():
                destination.unlink()
            dest_conn = sqlite3.connect(str(destination), timeout=5)
            dest_conn.executescript(dump)
            dest_conn.commit()
            dest_conn.close()
            dest_conn = None
            ok, _ = self._quick_check_path(str(destination))
            return bool(ok)
        except Exception:
            return False
        finally:
            for conn in (source_conn, dest_conn):
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

    def _quarantine_corrupt_database(self, reason: str) -> Optional[str]:
        source = Path(self.db_path)
        if not source.exists():
            return None
        preserved = self._corrupt_recovery_path()
        candidate = preserved.with_suffix(".recovered.db")

        # Recupera para um arquivo separado e, em seguida, MOVE o banco original
        # para a área de recuperação. Não cria cópia diária nem duplicata prévia.
        recovered = self._try_recover_database(source, candidate)

        original_location = preserved
        active_path = source
        moved = False
        try:
            os.replace(source, preserved)
            moved = True
        except Exception:
            # Se o Windows negar o rename, o original permanece intocado.
            original_location = source
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            active_path = source.with_name(f"{source.stem}_fresh_{stamp}{source.suffix}")
            self.db_path = str(active_path)

        # Sidecars pertencem ao original. Só os movemos quando o próprio banco
        # também foi movido; no fallback eles ficam intocados ao lado dele.
        if moved:
            for suffix in ("-wal", "-shm"):
                side = Path(str(source) + suffix)
                if side.exists():
                    try:
                        os.replace(side, Path(str(preserved) + suffix))
                    except Exception:
                        pass

        if recovered and candidate.exists():
            os.replace(candidate, active_path)
            self.recovery_notice = f"Banco corrompido preservado em {original_location}; dados recuperados quando possível."
            self._log("warning", f"Memória SQLite recuperada. Motivo: {reason}. Original: {original_location}")
        else:
            try:
                candidate.unlink(missing_ok=True)
            except Exception:
                pass
            self.recovery_notice = f"Banco corrompido preservado em {original_location}; uma base nova foi criada."
            self._log("warning", f"Memória SQLite reiniciada com segurança. Motivo: {reason}. Original: {original_location}")
        return str(original_location)

    def _prepare_database_health(self):
        if not os.path.isfile(self.db_path):
            return
        ok, detail = self._quick_check_path(self.db_path)
        if ok:
            return
        self._quarantine_corrupt_database(detail)

    def _configure(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=15000")
            self.conn.commit()

    def _create_schema(self):
        with self._lock:
            cur = self.conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT 'Nova conversa',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_user INTEGER NOT NULL DEFAULT 0,
                    is_jarvis INTEGER NOT NULL DEFAULT 0,
                    is_system INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, id)
            """)

            # Histórico legado continua válido, mas a identidade exibida passa
            # a ser unicamente JARVIS.
            try:
                cur.execute("UPDATE messages SET sender='JARVIS' WHERE is_jarvis=1 AND UPPER(sender)='ZERO'")
            except Exception:
                pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    source_message_id INTEGER,
                    importance REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS profile_facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    source_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cur.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('db_version', ?)",
                (str(self.DB_VERSION),)
            )

            # FTS5 para recuperação rápida. Se o Python/SQLite não tiver
            # FTS5, o sistema continua usando busca local por palavras.
            try:
                cur.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                    USING fts5(
                        message,
                        sender UNINDEXED,
                        conversation_id UNINDEXED,
                        message_id UNINDEXED
                    )
                """)
                self.fts_available = True
            except Exception:
                self.fts_available = False

            self.conn.commit()

    def close(self):
        with self._lock:
            try:
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass

    # =========================================================
    # SETTINGS
    # =========================================================

    def set_setting(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
                (key, str(value))
            )
            self.conn.commit()

    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,)
            ).fetchone()
        return row["value"] if row else default

    # =========================================================
    # CONVERSAS
    # =========================================================

    def create_conversation(self, title: str = "Nova conversa") -> int:
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO conversations(title, created_at, updated_at)
                VALUES(?, ?, ?)
                """,
                (title, now, now)
            )
            conversation_id = int(cur.lastrowid)
            self.conn.commit()

        self.set_setting("active_conversation_id", str(conversation_id))
        return conversation_id

    def get_or_create_active_conversation(self) -> int:
        stored = self.get_setting("active_conversation_id")

        if stored:
            try:
                conversation_id = int(stored)
                with self._lock:
                    row = self.conn.execute(
                        """
                        SELECT id FROM conversations
                        WHERE id = ? AND archived = 0
                        """,
                        (conversation_id,)
                    ).fetchone()

                if row:
                    return conversation_id
            except Exception:
                pass

        # Se não houver sessão ativa válida, retoma a conversa mais recente.
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id FROM conversations
                WHERE archived = 0
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

        if row:
            conversation_id = int(row["id"])
            self.set_setting("active_conversation_id", str(conversation_id))
            return conversation_id

        return self.create_conversation()

    def get_conversation_title(self, conversation_id: int) -> str:
        with self._lock:
            row = self.conn.execute(
                "SELECT title FROM conversations WHERE id = ?",
                (conversation_id,)
            ).fetchone()

        return row["title"] if row else "Nova conversa"

    def list_conversations(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.archived = 0
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.id DESC
                LIMIT ?
                """,
                (int(limit),)
            ).fetchall()

        return [dict(row) for row in rows]

    def switch_conversation(self, conversation_id: int) -> bool:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id FROM conversations
                WHERE id = ? AND archived = 0
                """,
                (int(conversation_id),)
            ).fetchone()

        if not row:
            return False

        self.set_setting("active_conversation_id", str(int(conversation_id)))
        return True

    # =========================================================
    # MENSAGENS
    # =========================================================

    def save_message(
        self,
        conversation_id: int,
        sender: str,
        message: str,
        is_user: bool = False,
        is_jarvis: bool = False,
        is_system: bool = False
    ) -> Optional[int]:
        text = (message or "").strip()

        if not text:
            return None

        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO messages(
                    conversation_id,
                    sender,
                    message,
                    is_user,
                    is_jarvis,
                    is_system,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(conversation_id),
                    sender,
                    text,
                    int(bool(is_user)),
                    int(bool(is_jarvis)),
                    int(bool(is_system)),
                    now
                )
            )

            message_id = int(cur.lastrowid)

            self.conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, int(conversation_id))
            )

            # Gera título a partir da primeira mensagem real do usuário.
            if is_user:
                row = self.conn.execute(
                    "SELECT title FROM conversations WHERE id = ?",
                    (int(conversation_id),)
                ).fetchone()

                if row and row["title"] == "Nova conversa":
                    title = self._make_title(text)
                    self.conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title, int(conversation_id))
                    )

            if getattr(self, "fts_available", False):
                try:
                    self.conn.execute(
                        """
                        INSERT INTO messages_fts(
                            message,
                            sender,
                            conversation_id,
                            message_id
                        )
                        VALUES(?, ?, ?, ?)
                        """,
                        (
                            text,
                            sender,
                            str(conversation_id),
                            str(message_id)
                        )
                    )
                except Exception:
                    pass

            self.conn.commit()

        if is_user:
            self._extract_memory_from_user_message(
                text,
                source_message_id=message_id
            )

        return message_id

    def load_messages(
        self,
        conversation_id: int,
        limit: int = 500
    ) -> List[Dict]:
        limit = max(1, min(int(limit), 5000))

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT *
                FROM (
                    SELECT
                        id,
                        sender,
                        message,
                        is_user,
                        is_jarvis,
                        is_system,
                        created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (int(conversation_id), limit)
            ).fetchall()

        result = []

        for row in rows:
            result.append({
                "id": row["id"],
                "sender": row["sender"],
                "message": row["message"],
                "timestamp": row["created_at"],
                "is_user": bool(row["is_user"]),
                "is_jarvis": bool(row["is_jarvis"]),
                "is_system": bool(row["is_system"]),
            })

        return result

    def recent_context(
        self,
        conversation_id: int,
        limit: int = 24
    ) -> List[Dict]:
        return self.load_messages(conversation_id, limit=limit)

    # =========================================================
    # MEMÓRIA DE LONGO PRAZO
    # =========================================================

    def set_profile_fact(
        self,
        key: str,
        value: str,
        source_message_id: Optional[int] = None
    ) -> bool:
        """Salva um fato global que sobrevive à troca/exclusão de chats."""
        key = (key or "").strip().lower()
        value = " ".join((value or "").split()).strip()

        if not key or not value:
            return False

        now = datetime.now().isoformat(timespec="seconds")

        labels = {
            "name": "Nome do usuário",
            "preferred_browser": "Navegador principal do usuário",
        }
        label = labels.get(key, key.replace("_", " ").title())

        with self._lock:
            existing = self.conn.execute(
                "SELECT created_at FROM profile_facts WHERE key = ?",
                (key,)
            ).fetchone()

            created_at = existing["created_at"] if existing else now

            self.conn.execute(
                """
                INSERT INTO profile_facts(
                    key, value, source_message_id, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    source_message_id = excluded.source_message_id,
                    updated_at = excluded.updated_at
                """,
                (key, value, source_message_id, created_at, now)
            )

            fingerprint = f"profile:{key}"
            content = f"{label}: {value}"

            self.conn.execute(
                """
                INSERT INTO memories(
                    fingerprint, content, source_message_id,
                    importance, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint)
                DO UPDATE SET
                    content = excluded.content,
                    source_message_id = excluded.source_message_id,
                    importance = excluded.importance,
                    updated_at = excluded.updated_at
                """,
                (
                    fingerprint,
                    content,
                    source_message_id,
                    10.0,
                    created_at,
                    now
                )
            )

            self.conn.commit()

        return True

    def get_profile_facts(self) -> Dict[str, str]:
        """Retorna o perfil global persistente."""
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT key, value
                FROM profile_facts
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return {
            str(row["key"]): str(row["value"])
            for row in rows
        }

    def delete_profile_fact(self, key: str) -> bool:
        key = (key or "").strip().lower()

        if not key:
            return False

        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM profile_facts WHERE key = ?",
                (key,)
            )
            self.conn.execute(
                "DELETE FROM memories WHERE fingerprint = ?",
                (f"profile:{key}",)
            )
            self.conn.commit()

        return cur.rowcount > 0

    def _extract_profile_facts(
        self,
        text: str,
        source_message_id: Optional[int] = None
    ):
        """Extrai identidade/preferências globais do usuário."""
        raw = " ".join((text or "").split()).strip()

        if not raw:
            return

        name_patterns = [
            re.compile(
                r"\bmeu nome (?:é|e)\s+"
                r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{1,60}?)"
                r"(?=\s+(?:e\s+)?(?:eu\s+)?"
                r"(?:trabalho|moro|uso|tenho|prefiro)\b|[.!?,]|$)",
                re.I
            ),
            re.compile(
                r"\b(?:eu\s+)?me chamo\s+"
                r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{1,60}?)"
                r"(?=[.!?,]|$)",
                re.I
            ),
            re.compile(
                r"\b(?:salv[ae]|guarde|grave|memorize)\s+"
                r"(?:o\s+)?meu nome(?:\s+como)?\s+"
                r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{1,60}?)"
                r"(?=[.!?,]|$)",
                re.I
            ),
        ]

        for pattern in name_patterns:
            match = pattern.search(raw)
            if match:
                name = " ".join(
                    match.group(1).split()
                ).strip(" .,!?:;")

                if 1 < len(name) <= 60:
                    self.set_profile_fact(
                        "name",
                        name,
                        source_message_id
                    )
                    break

        browser_match = re.search(
            r"\bmeu navegador(?: principal)? (?:é|e)\s+"
            r"(.+?)(?=[.!?,]|$)",
            raw,
            flags=re.I
        )

        if browser_match:
            browser = " ".join(
                browser_match.group(1).split()
            ).strip(" .,!?:;")

            if browser:
                self.set_profile_fact(
                    "preferred_browser",
                    browser,
                    source_message_id
                )

    def _extract_memory_from_user_message(
        self,
        message: str,
        source_message_id: Optional[int] = None
    ):
        """
        Guarda automaticamente frases que parecem conter preferências,
        identidade, objetivos ou regras persistentes.

        Não tenta "reescrever" o que o usuário disse: guarda a frase original.
        """
        text = " ".join((message or "").split()).strip()

        self._extract_profile_facts(
            text,
            source_message_id=source_message_id
        )

        if len(text) < 8 or len(text) > 1000:
            return

        lower = text.lower()

        memory_markers = [
            "meu nome é",
            "me chamo ",
            "eu sou ",
            "eu trabalho ",
            "trabalho com ",
            "eu uso ",
            "eu tenho ",
            "eu prefiro ",
            "prefiro que ",
            "eu gosto ",
            "eu não gosto ",
            "quero que você ",
            "quero que o zero ",
            "sempre ",
            "nunca ",
            "nas próximas ",
            "daqui pra frente",
            "lembre que ",
            "lembra que ",
            "minha ",
            "meu projeto",
        ]

        if not any(marker in lower for marker in memory_markers):
            return

        fingerprint = hashlib.sha256(
            lower.encode("utf-8", errors="ignore")
        ).hexdigest()

        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO memories(
                    fingerprint,
                    content,
                    source_message_id,
                    importance,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint)
                DO UPDATE SET updated_at = excluded.updated_at
                """,
                (
                    fingerprint,
                    text,
                    source_message_id,
                    1.0,
                    now,
                    now
                )
            )
            self.conn.commit()

    def get_relevant_memories(
        self,
        query: str,
        current_conversation_id: Optional[int] = None,
        limit: int = 10
    ) -> List[str]:
        """
        Combina:
        1. memórias persistentes explícitas;
        2. mensagens antigas semanticamente aproximadas por palavras-chave/FTS.

        Tudo funciona localmente, sem embeddings pagos.
        """
        limit = max(1, min(int(limit), 20))
        results = []
        seen = set()

        # Perfil global entra SEMPRE no contexto.
        profile = self.get_profile_facts()

        profile_labels = {
            "name": "Nome do usuário",
            "preferred_browser": "Navegador principal do usuário",
        }

        for key, value in profile.items():
            label = profile_labels.get(
                key,
                key.replace("_", " ").title()
            )
            content = f"{label}: {value}"

            if content not in seen:
                seen.add(content)
                results.append(content)

            if len(results) >= limit:
                return results

        # Memórias explícitas, sem duplicar as cópias do perfil.
        with self._lock:
            memory_rows = self.conn.execute(
                """
                SELECT content
                FROM memories
                WHERE fingerprint NOT LIKE 'profile:%'
                ORDER BY importance DESC, updated_at DESC, id DESC
                LIMIT 30
                """
            ).fetchall()

        query_tokens = self._tokens(query)

        scored_memories = []
        for row in memory_rows:
            content = row["content"]
            score = self._relevance_score(query_tokens, content)
            # Memória explícita merece um pequeno bônus.
            scored_memories.append((score + 0.25, content))

        scored_memories.sort(key=lambda item: item[0], reverse=True)

        for score, content in scored_memories:
            if content not in seen and (score > 0.25 or len(results) < 3):
                seen.add(content)
                results.append(content)
                if len(results) >= limit:
                    return results

        # Busca FTS em todo o histórico.
        historical = self._search_history(query, limit=limit * 3)

        for item in historical:
            content = f"{item['sender']}: {item['message']}"
            if content not in seen:
                seen.add(content)
                results.append(content)

            if len(results) >= limit:
                break

        return results

    def _search_history(self, query: str, limit: int = 20) -> List[Dict]:
        tokens = [
            token for token in self._tokens(query)
            if len(token) >= 3 and token not in self._stopwords()
        ]

        # Tenta FTS5 primeiro.
        if getattr(self, "fts_available", False) and tokens:
            try:
                fts_query = " OR ".join(
                    f'"{token.replace(chr(34), "")}"'
                    for token in tokens[:8]
                )

                with self._lock:
                    rows = self.conn.execute(
                        """
                        SELECT
                            message,
                            sender,
                            conversation_id,
                            message_id,
                            bm25(messages_fts) AS rank
                        FROM messages_fts
                        WHERE messages_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (fts_query, int(limit))
                    ).fetchall()

                if rows:
                    return [
                        {
                            "message": row["message"],
                            "sender": row["sender"],
                            "conversation_id": row["conversation_id"],
                            "message_id": row["message_id"],
                        }
                        for row in rows
                    ]
            except Exception:
                pass

        # Fallback: varre uma janela recente maior e pontua localmente.
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, conversation_id, sender, message
                FROM messages
                ORDER BY id DESC
                LIMIT 2000
                """
            ).fetchall()

        scored = []

        for row in rows:
            score = self._relevance_score(set(tokens), row["message"])
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            {
                "message": row["message"],
                "sender": row["sender"],
                "conversation_id": row["conversation_id"],
                "message_id": row["id"],
            }
            for score, row in scored[:limit]
        ]

    def create_reminder(self, task: str, due_at) -> int:
        if hasattr(due_at, "isoformat"):
            due_text = due_at.isoformat(timespec="seconds")
        else:
            due_text = str(due_at)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO reminders(task, due_at, status, created_at) VALUES(?, ?, 'pending', ?)",
                ((task or "Lembrete").strip(), due_text, now)
            )
            reminder_id = int(cur.lastrowid)
            self.conn.commit()
        return reminder_id

    def list_pending_reminders(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at ASC LIMIT ?",
                (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def due_reminders(self) -> List[Dict]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
                (now,)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_done(self, reminder_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE reminders SET status = 'done' WHERE id = ?",
                (int(reminder_id),)
            )
            self.conn.commit()

    def search_messages(self, query: str, limit: int = 30) -> List[Dict]:
        """Busca texto em todo o histórico e retorna conversa/data/remetente."""
        query = (query or "").strip()
        if not query:
            return []
        raw = self._search_history(query, limit=max(limit * 2, 30))
        result = []
        seen = set()
        for item in raw:
            mid = item.get("message_id")
            if mid in seen:
                continue
            seen.add(mid)
            with self._lock:
                row = self.conn.execute(
                    """
                    SELECT m.id, m.conversation_id, m.sender, m.message, m.created_at,
                           c.title AS conversation_title
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.id = ?
                    """,
                    (int(mid),)
                ).fetchone()
            if row:
                result.append(dict(row))
            if len(result) >= limit:
                break
        return result

    def delete_conversation(self, conversation_id: int) -> bool:
        """Apaga uma conversa e suas mensagens, mantendo outras sessões."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ?",
                (int(conversation_id),)
            ).fetchall()
            message_ids = [int(r["id"]) for r in rows]
            self.conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (int(conversation_id),)
            )
            if getattr(self, "fts_available", False) and message_ids:
                for mid in message_ids:
                    try:
                        self.conn.execute(
                            "DELETE FROM messages_fts WHERE message_id = ?",
                            (str(mid),)
                        )
                    except Exception:
                        pass
            self.conn.commit()
        active = self.get_setting("active_conversation_id")
        if active == str(conversation_id):
            self.set_setting("active_conversation_id", "")
        return True

    def rename_conversation(self, conversation_id: int, new_title: str) -> bool:
        """Renomeia uma conversa existente."""
        title = " ".join((new_title or "").split()).strip()

        if not title:
            return False

        if len(title) > 80:
            title = title[:80].rstrip()

        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ? AND archived = 0
                """,
                (title, now, int(conversation_id))
            )
            self.conn.commit()
            return cur.rowcount > 0

    def list_memories(self, limit: int = 100) -> List[Dict]:
        """Lista memórias persistentes para gerenciamento na interface."""
        limit = max(1, min(int(limit), 500))

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT
                    id,
                    content,
                    source_message_id,
                    importance,
                    created_at,
                    updated_at
                FROM memories
                ORDER BY importance DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        """Apaga memória e sincroniza fatos de perfil."""
        with self._lock:
            row = self.conn.execute(
                "SELECT fingerprint FROM memories WHERE id = ?",
                (int(memory_id),)
            ).fetchone()

            if not row:
                return False

            fingerprint = str(row["fingerprint"])

            if fingerprint.startswith("profile:"):
                profile_key = fingerprint.split(":", 1)[1]
                self.conn.execute(
                    "DELETE FROM profile_facts WHERE key = ?",
                    (profile_key,)
                )

            cur = self.conn.execute(
                "DELETE FROM memories WHERE id = ?",
                (int(memory_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0

    def clear_long_term_memories(self) -> int:
        """Apaga somente memórias extraídas; não apaga o histórico do chat."""
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
            count = int(row["n"] if row else 0)
            self.conn.execute("DELETE FROM memories")
            self.conn.execute("DELETE FROM profile_facts")
            self.conn.commit()
        return count

    def memory_stats(self) -> Dict:
        with self._lock:
            conversations = self.conn.execute("SELECT COUNT(*) AS n FROM conversations WHERE archived = 0").fetchone()["n"]
            messages = self.conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            memories = self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
            profile_facts = self.conn.execute(
                "SELECT COUNT(*) AS n FROM profile_facts"
            ).fetchone()["n"]
        return {
            "conversations": int(conversations),
            "messages": int(messages),
            "memories": int(memories),
            "profile_facts": int(profile_facts),
            "db_path": self.db_path,
        }

    # =========================================================
    # AUXILIARES
    # =========================================================

    def _make_title(self, text: str) -> str:
        clean = " ".join(text.split()).strip()

        if len(clean) <= 52:
            return clean

        return clean[:49].rstrip() + "..."

    def _tokens(self, text: str):
        return set(
            re.findall(
                r"[a-zA-ZÀ-ÿ0-9_]{2,}",
                (text or "").lower()
            )
        )

    def _relevance_score(self, query_tokens, content: str) -> float:
        if not query_tokens:
            return 0.0

        content_tokens = self._tokens(content)

        if not content_tokens:
            return 0.0

        overlap = len(query_tokens & content_tokens)

        if overlap == 0:
            return 0.0

        return overlap / max(1, len(query_tokens))

    def _stopwords(self):
        return {
            "que", "para", "com", "uma", "uns", "das", "dos",
            "isso", "esse", "essa", "aqui", "como", "mais", "menos",
            "ele", "ela", "voce", "você", "zero", "jarvis", "meu",
            "minha", "seu", "sua", "por", "pra", "pro", "de", "da",
            "do", "em", "no", "na", "nos", "nas", "um", "uma"
        }
