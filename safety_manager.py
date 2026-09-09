"""
JARVIS - controle de impacto para ações locais.

Modo direto:
- ações comuns e reversíveis executam sem confirmação;
- fechar apps, suspender e mover arquivos/pastas para a Lixeira são diretos;
- somente energia irreversível e esvaziar a Lixeira exigem confirmação;
- caminhos críticos do Windows e do próprio JARVIS continuam protegidos.
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Dict, Optional


class SafetyManager:
    YES_WORDS = {
        "sim",
        "confirmo",
        "confirma",
        "confirmar",
        "pode",
        "pode sim",
        "faça",
        "faz",
        "execute",
        "executa",
    }

    NO_WORDS = {
        "não",
        "nao",
        "cancela",
        "cancelar",
        "não faça",
        "nao faca",
        "deixa",
        "deixa pra lá",
        "deixa pra la",
    }

    def __init__(
        self,
        project_dir: str,
        logger=None
    ):
        self.project_dir = Path(
            project_dir
        ).resolve()
        self.logger = logger

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize(
            "NFKD",
            str(value or "")
        )
        value = "".join(
            c for c in value
            if not unicodedata.combining(c)
        )
        value = value.lower()
        value = re.sub(
            r"\s+",
            " ",
            value
        )
        return value.strip()

    def confirmation_answer(
        self,
        text: str
    ) -> Optional[bool]:
        value = self._normalize(
            text
        ).strip(" .,!?:;")

        yes = {
            self._normalize(v)
            for v in self.YES_WORDS
        }
        no = {
            self._normalize(v)
            for v in self.NO_WORDS
        }

        if value in yes:
            return True

        if value in no:
            return False

        return None

    def classify(
        self,
        command: str
    ) -> Dict:
        value = self._normalize(
            command
        )

        critical_patterns = [
            (
                r"\b(deslig|shutdown|reinici|restart|reboot)\w*",
                "energia do sistema"
            ),
            (
                r"\b(limpar|esvaziar)\w*.*\blixeira\b",
                "esvaziar a lixeira"
            ),
            (
                r"\b(apag|delete|delet|exclu|remov)\w*.*\b(?:permanentemente|definitivamente|sem\s+lixeira)\b",
                "exclusão permanente"
            ),
        ]

        for pattern, reason in critical_patterns:
            if re.search(
                pattern,
                value,
                flags=re.I
            ):
                return {
                    "level": "critical",
                    "requires_confirmation": True,
                    "reason": reason,
                }

        # Modo direto: fechar apps, suspender e mandar arquivo/pasta para a
        # Lixeira são tratados como ações comuns. O método de exclusão ainda
        # bloqueia caminhos críticos antes de chamar Send2Trash.
        return {
            "level": "direct",
            "requires_confirmation": False,
            "reason": "",
        }

    def _expand_path(
        self,
        raw_path: str
    ) -> Path:
        raw = str(
            raw_path or ""
        ).strip().strip(
            "\"'"
        )

        user = Path.home()

        aliases = {
            "desktop": user / "Desktop",
            "area de trabalho": user / "Desktop",
            "área de trabalho": user / "Desktop",
            "downloads": user / "Downloads",
            "documentos": user / "Documents",
            "documents": user / "Documents",
            "imagens": user / "Pictures",
            "pictures": user / "Pictures",
        }

        normalized = self._normalize(
            raw
        )

        for prefix, base in aliases.items():
            norm_prefix = self._normalize(
                prefix
            )

            if (
                normalized == norm_prefix
                or normalized.startswith(
                    norm_prefix + " "
                )
            ):
                remainder = raw[
                    len(prefix):
                ].strip(
                    " \\/"
                )

                return (
                    base / remainder
                    if remainder
                    else base
                ).expanduser().resolve()

        path = Path(
            os.path.expandvars(
                os.path.expanduser(
                    raw
                )
            )
        )

        if not path.is_absolute():
            path = (
                user / path
            )

        return path.resolve()

    def _is_protected(
        self,
        path: Path
    ) -> bool:
        path = path.resolve()

        protected = {
            Path(
                os.environ.get(
                    "SystemRoot",
                    r"C:\Windows"
                )
            ).resolve(),
            Path(
                os.environ.get(
                    "ProgramFiles",
                    r"C:\Program Files"
                )
            ).resolve(),
            Path(
                os.environ.get(
                    "ProgramFiles(x86)",
                    r"C:\Program Files (x86)"
                )
            ).resolve(),
            Path.home().resolve(),
            self.project_dir.resolve(),
        }

        # Raiz de qualquer drive.
        if path.parent == path:
            return True

        for item in protected:
            if path == item:
                return True

        # Descendentes das pastas de sistema e do projeto também são críticos.
        # A pasta HOME em si é protegida, mas seus filhos (Desktop, Downloads,
        # Documents etc.) continuam disponíveis para o modo direto.
        system_roots = {
            Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve(),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
            self.project_dir.resolve(),
        }
        for item in system_roots:
            try:
                path.relative_to(item)
                return True
            except ValueError:
                pass

        return False

    def empty_recycle_bin(self) -> str:
        """Esvazia a Lixeira usando o cmdlet nativo do PowerShell."""
        if os.name != "nt":
            return "Esvaziar Lixeira está disponível apenas no Windows."

        try:
            creationflags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )

            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "Clear-RecycleBin -Force -ErrorAction Stop",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=creationflags,
            )

            if result.returncode != 0:
                detail = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or "erro desconhecido"
                )
                return (
                    f"Não consegui esvaziar a Lixeira: {detail}"
                )

            return "✓ Lixeira esvaziada."

        except Exception as exc:
            return (
                f"Não consegui esvaziar a Lixeira: {exc}"
            )

    def safe_delete_to_recycle_bin(
        self,
        raw_path: str
    ) -> str:
        try:
            path = self._expand_path(
                raw_path
            )

            if not path.exists():
                return (
                    f"Não encontrei: {path}"
                )

            if self._is_protected(
                path
            ):
                return (
                    "Bloqueei a exclusão porque esse caminho "
                    "é protegido pelo JARVIS."
                )

            from send2trash import send2trash

            send2trash(
                str(path)
            )

            return (
                f"✓ Movido para a Lixeira: {path.name}."
            )

        except Exception as exc:
            return (
                f"Não consegui mover para a Lixeira: {exc}"
            )
