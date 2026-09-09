"""GitHub Releases updater for JARVIS Desktop.

Public repositories need no GitHub token. Updates use the latest non-draft,
non-prerelease release and only accept a signed-by-hash installer asset.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
from packaging.version import InvalidVersion, Version

from secure_settings import settings_dir

GITHUB_API_VERSION = "2026-03-10"
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    installer_name: str
    download_url: str
    sha256: str
    size: int
    notes: str
    html_url: str


class GitHubReleaseUpdater:
    def __init__(self, app_dir=None, current_version="0.0.0", logger=None):
        self.app_dir = Path(app_dir or self._detect_app_dir()).resolve()
        self.current_version = str(current_version or "0.0.0").strip()
        self.logger = logger
        self.config = self._load_config()

    @staticmethod
    def _detect_app_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "UPDATE")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _load_config(self) -> dict:
        path = self.app_dir / "update_config.json"
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    @property
    def repository(self) -> str:
        return str(self.config.get("repository") or "").strip().strip("/")

    def is_configured(self) -> bool:
        repo = self.repository
        return bool(
            self.config.get("enabled", True)
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            and not repo.upper().startswith(("AUTO/", "SEU_USUARIO/"))
            and repo.upper() not in {"AUTO", "OWNER/REPO"}
        )

    def _headers(self) -> dict:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": f"JARVIS-Desktop/{self.current_version}",
        }

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        text = str(tag or "").strip()
        if text.lower().startswith("v"):
            text = text[1:]
        return text

    def _is_newer(self, candidate: str) -> bool:
        try:
            return Version(self._normalize_tag(candidate)) > Version(self._normalize_tag(self.current_version))
        except InvalidVersion:
            return False

    @staticmethod
    def _digest_from_asset(asset: dict) -> str:
        digest = str(asset.get("digest") or "").strip().lower()
        if digest.startswith("sha256:"):
            value = digest.split(":", 1)[1]
            if re.fullmatch(r"[0-9a-f]{64}", value):
                return value
        return ""

    def _read_companion_sha(self, assets: list, installer_name: str) -> str:
        wanted = installer_name + ".sha256"
        asset = next((item for item in assets if str(item.get("name")) == wanted), None)
        if not asset:
            return ""
        url = str(asset.get("browser_download_url") or "")
        if not url:
            return ""
        try:
            response = requests.get(url, headers={"User-Agent": self._headers()["User-Agent"]}, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            match = re.search(r"\b([0-9a-fA-F]{64})\b", response.text)
            return match.group(1).lower() if match else ""
        except Exception:
            return ""

    def check(self) -> Optional[UpdateInfo]:
        if not self.is_configured():
            return None
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        response = requests.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        release = response.json()
        tag = str(release.get("tag_name") or "")
        version = self._normalize_tag(tag)
        if not self._is_newer(version):
            return None

        assets = list(release.get("assets") or [])
        prefix = str(self.config.get("installer_asset_prefix") or "JARVIS_Setup_")
        candidates = [
            asset for asset in assets
            if str(asset.get("name") or "").lower().endswith(".exe")
            and str(asset.get("name") or "").startswith(prefix)
        ]
        if not candidates:
            self._log("warning", "Release nova encontrada, mas sem instalador JARVIS_Setup_*.exe.")
            return None
        installer = max(candidates, key=lambda item: int(item.get("size") or 0))
        installer_name = str(installer.get("name") or "")
        sha256 = self._digest_from_asset(installer) or self._read_companion_sha(assets, installer_name)
        if not sha256:
            self._log("warning", "Atualização ignorada porque o SHA-256 do instalador não está disponível.")
            return None
        return UpdateInfo(
            version=version,
            tag=tag,
            installer_name=installer_name,
            download_url=str(installer.get("browser_download_url") or ""),
            sha256=sha256,
            size=int(installer.get("size") or 0),
            notes=str(release.get("body") or "").strip(),
            html_url=str(release.get("html_url") or "").strip(),
        )

    def download(self, info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None) -> Path:
        update_dir = settings_dir() / "updates"
        update_dir.mkdir(parents=True, exist_ok=True)
        final_path = update_dir / info.installer_name
        fd, temp_name = tempfile.mkstemp(prefix="jarvis-update-", suffix=".part", dir=str(update_dir))
        os.close(fd)
        hasher = hashlib.sha256()
        downloaded = 0
        try:
            with requests.get(
                info.download_url,
                headers={"User-Agent": self._headers()["User-Agent"]},
                timeout=(10, 90),
                stream=True,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or info.size or 0)
                with open(temp_name, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
            actual = hasher.hexdigest().lower()
            if actual != info.sha256.lower():
                raise ValueError("SHA-256 da atualização não confere.")
            os.replace(temp_name, final_path)
            return final_path
        except Exception:
            try:
                os.unlink(temp_name)
            except Exception:
                pass
            raise

    def launch_installer(self, installer: Path, update: bool = True) -> bool:
        installer = Path(installer).resolve()
        if not installer.exists():
            raise FileNotFoundError(str(installer))
        args = [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS",
            f"/DIR={self.app_dir}",
        ]
        if update:
            args.append("/UPDATE=1")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(args, close_fds=True, creationflags=creationflags)
        return True


__all__ = ["GitHubReleaseUpdater", "UpdateInfo"]
