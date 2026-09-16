"""GitHub updater with stable/beta/dev channels for JARVIS Desktop.

Stable keeps using normal public releases. Beta/dev use a small signed-by-hash
manifest so a newer build can be offered even when the semantic version is the
same. The selected channel is stored per user under LocalAppData.
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
VALID_CHANNELS = {"stable", "beta", "dev"}


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
    kind: str = "installer"
    runtime_api: int = 0
    minimum_bootstrap: str = ""
    build_id: str = ""
    channel: str = "stable"
    repair: bool = False

    @property
    def asset_name(self) -> str:
        return self.installer_name

    @property
    def is_hot(self) -> bool:
        return self.kind == "hot"


class GitHubReleaseUpdater:
    def __init__(
        self,
        app_dir=None,
        current_version="0.0.0",
        logger=None,
        current_build="",
        channel="stable",
    ):
        self.app_dir = Path(app_dir or self._detect_app_dir()).resolve()
        self.current_version = str(current_version or "0.0.0").strip()
        self.current_build = str(current_build or "").strip()
        self.logger = logger
        self.config = self._load_config()
        self._channel = self._load_channel(channel)

    @staticmethod
    def _detect_app_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent)

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
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
        except Exception:
            pass
        return {}

    @property
    def repository(self) -> str:
        return str(self.config.get("repository") or "").strip().strip("/")

    @property
    def runtime_api(self) -> int:
        try:
            return int(self.config.get("runtime_api") or 0)
        except Exception:
            return 0

    @property
    def bootstrap_version(self) -> str:
        return str(self.config.get("bootstrap_version") or self.current_version or "0.0.0").strip()

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def channel_path(self) -> Path:
        return settings_dir() / "update_channel.json"

    def _load_channel(self, fallback: str) -> str:
        value = str(fallback or self.config.get("default_channel") or "stable").strip().lower()
        try:
            path = settings_dir() / "update_channel.json"
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                saved = str((payload or {}).get("channel") or "").strip().lower()
                if saved in VALID_CHANNELS:
                    value = saved
        except Exception:
            pass
        return value if value in VALID_CHANNELS else "stable"

    def set_channel(self, channel: str) -> str:
        value = str(channel or "").strip().lower()
        if value not in VALID_CHANNELS:
            raise ValueError(f"Canal de atualização inválido: {channel}")
        path = self.channel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"channel": value}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._channel = value
        self._log("info", f"Canal de atualização alterado para {value}.")
        return value

    def _channel_config(self, channel: str | None = None) -> dict:
        channels = self.config.get("channels") or {}
        if not isinstance(channels, dict):
            return {}
        payload = channels.get(str(channel or self.channel).lower()) or {}
        return payload if isinstance(payload, dict) else {}

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
            "User-Agent": f"JARVIS-Desktop/{self.current_version}-{self.current_build or 'unknown'}",
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

    def _should_offer(self, candidate_version: str, candidate_build: str, force_repair: bool) -> tuple[bool, bool]:
        try:
            candidate = Version(self._normalize_tag(candidate_version))
            current = Version(self._normalize_tag(self.current_version))
        except InvalidVersion:
            return False, False
        if candidate > current:
            return True, False
        if candidate < current:
            return False, False
        candidate_build = str(candidate_build or "").strip()
        if candidate_build and candidate_build != self.current_build:
            return True, False
        if force_repair:
            return True, True
        return False, False

    @staticmethod
    def _digest_from_asset(asset: dict) -> str:
        digest = str(asset.get("digest") or "").strip().lower()
        if digest.startswith("sha256:"):
            value = digest.split(":", 1)[1]
            if re.fullmatch(r"[0-9a-f]{64}", value):
                return value
        return ""

    def _download_small_text(self, asset: dict, max_bytes: int = 256 * 1024) -> str:
        url = str(asset.get("browser_download_url") or "")
        if not url:
            return ""
        response = requests.get(url, headers={"User-Agent": self._headers()["User-Agent"]}, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        raw = response.content
        if len(raw) > max_bytes:
            raise ValueError("Metadado de atualização grande demais.")
        return raw.decode("utf-8", errors="strict")

    def _read_companion_sha(self, assets: list, asset_name: str) -> str:
        wanted = asset_name + ".sha256"
        asset = next((item for item in assets if str(item.get("name")) == wanted), None)
        if not asset:
            return ""
        try:
            text = self._download_small_text(asset, max_bytes=16 * 1024)
            match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
            return match.group(1).lower() if match else ""
        except Exception:
            return ""

    def _asset_sha(self, assets: list, asset: dict) -> str:
        return self._digest_from_asset(asset) or self._read_companion_sha(assets, str(asset.get("name") or ""))

    def _read_hot_metadata(self, assets: list, hot_name: str) -> dict:
        stem = hot_name[:-4] if hot_name.lower().endswith(".zip") else hot_name
        wanted = stem + ".json"
        asset = next((item for item in assets if str(item.get("name") or "") == wanted), None)
        if not asset:
            return {}
        try:
            payload = json.loads(self._download_small_text(asset))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            self._log("warning", f"Metadado de hot update inválido: {exc}")
            return {}

    def _hot_candidate(self, release: dict, version: str) -> Optional[UpdateInfo]:
        if not bool(self.config.get("hot_updates_enabled", True)):
            return None
        assets = list(release.get("assets") or [])
        prefix = str(self.config.get("hot_update_asset_prefix") or "JARVIS_HotUpdate_")
        candidates = [asset for asset in assets if str(asset.get("name") or "").startswith(prefix) and str(asset.get("name") or "").lower().endswith(".zip")]
        if not candidates:
            return None
        hot = max(candidates, key=lambda item: int(item.get("size") or 0))
        hot_name = str(hot.get("name") or "")
        metadata = self._read_hot_metadata(assets, hot_name)
        try:
            metadata_version = str(metadata.get("version") or "").strip()
            runtime_api = int(metadata.get("runtime_api") or 0)
            minimum_bootstrap = str(metadata.get("minimum_bootstrap") or "").strip()
            if metadata_version != version or runtime_api <= 0 or runtime_api != self.runtime_api:
                return None
            if minimum_bootstrap and Version(self.bootstrap_version) < Version(minimum_bootstrap):
                return None
        except (InvalidVersion, ValueError, TypeError):
            return None
        sha256 = self._asset_sha(assets, hot)
        if not sha256:
            return None
        return UpdateInfo(version=version, tag=str(release.get("tag_name") or ""), installer_name=hot_name, download_url=str(hot.get("browser_download_url") or ""), sha256=sha256, size=int(hot.get("size") or 0), notes=str(release.get("body") or "").strip(), html_url=str(release.get("html_url") or "").strip(), kind="hot", runtime_api=runtime_api, minimum_bootstrap=minimum_bootstrap, channel="stable")

    def _installer_candidate(self, release: dict, version: str) -> Optional[UpdateInfo]:
        assets = list(release.get("assets") or [])
        prefix = str(self.config.get("installer_asset_prefix") or "JARVIS_Setup_")
        candidates = [asset for asset in assets if str(asset.get("name") or "").lower().endswith(".exe") and str(asset.get("name") or "").startswith(prefix)]
        if not candidates:
            return None
        installer = max(candidates, key=lambda item: int(item.get("size") or 0))
        installer_name = str(installer.get("name") or "")
        sha256 = self._asset_sha(assets, installer)
        if not sha256:
            return None
        return UpdateInfo(version=version, tag=str(release.get("tag_name") or ""), installer_name=installer_name, download_url=str(installer.get("browser_download_url") or ""), sha256=sha256, size=int(installer.get("size") or 0), notes=str(release.get("body") or "").strip(), html_url=str(release.get("html_url") or "").strip(), kind="installer", channel="stable")

    def _check_manifest(self, *, force_repair: bool = False) -> Optional[UpdateInfo]:
        cfg = self._channel_config()
        url = str(cfg.get("manifest_url") or "").strip()
        if not url:
            return None
        response = requests.get(url, headers={"User-Agent": self._headers()["User-Agent"]}, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        if len(response.content) > 128 * 1024:
            raise ValueError("Manifesto de atualização grande demais.")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("available") is False:
            return None
        channel = str(payload.get("channel") or "").strip().lower()
        if channel != self.channel:
            raise ValueError(f"Manifesto do canal {channel or '?'} recebido no canal {self.channel}.")
        version = str(payload.get("version") or "").strip()
        build_id = str(payload.get("build_id") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().lower()
        download_url = str(payload.get("download_url") or "").strip()
        installer_name = str(payload.get("installer_name") or "").strip()
        if not version or not build_id or not installer_name or not download_url:
            raise ValueError("Manifesto de atualização incompleto.")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Manifesto sem SHA-256 válido.")
        if not download_url.lower().startswith("https://"):
            raise ValueError("URL de atualização não segura.")
        offer, repair = self._should_offer(version, build_id, force_repair)
        if not offer:
            return None
        return UpdateInfo(
            version=version,
            build_id=build_id,
            channel=channel,
            tag=str(payload.get("tag") or ""),
            installer_name=installer_name,
            download_url=download_url,
            sha256=sha256,
            size=int(payload.get("size") or 0),
            notes=str(payload.get("notes") or "").strip(),
            html_url=str(payload.get("html_url") or "").strip(),
            repair=repair,
        )

    def check(self, force_repair: bool = False) -> Optional[UpdateInfo]:
        """Return an update for the selected channel.

        Dev/beta compare semantic version plus build_id, therefore 1.4.0 build
        105 can update 1.4.0 build 104. Manual checks may request a repair when
        both version and build already match.
        """
        if not self.is_configured():
            return None
        if self.channel in {"beta", "dev"}:
            return self._check_manifest(force_repair=force_repair)

        url = f"https://api.github.com/repos/{self.repository}/releases?per_page=20"
        response = requests.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        releases = payload if isinstance(payload, list) else []
        ranked = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            version = self._normalize_tag(str(release.get("tag_name") or ""))
            try:
                parsed = Version(version)
                current = Version(self._normalize_tag(self.current_version))
            except InvalidVersion:
                continue
            if parsed < current or (parsed == current and not force_repair):
                continue
            ranked.append((parsed, release, version, parsed == current))
        ranked.sort(key=lambda item: item[0], reverse=True)
        for _, release, version, same_version in ranked:
            hot = None if same_version else self._hot_candidate(release, version)
            if hot is not None:
                return hot
            installer = self._installer_candidate(release, version)
            if installer is not None:
                if same_version:
                    return UpdateInfo(**{**installer.__dict__, "repair": True})
                return installer
        return None

    def download(self, info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None) -> Path:
        update_dir = settings_dir() / "updates"
        update_dir.mkdir(parents=True, exist_ok=True)
        final_path = update_dir / info.installer_name
        fd, temp_name = tempfile.mkstemp(prefix="jarvis-update-", suffix=".part", dir=str(update_dir))
        os.close(fd)
        hasher = hashlib.sha256()
        downloaded = 0
        try:
            with requests.get(info.download_url, headers={"User-Agent": self._headers()["User-Agent"]}, timeout=(10, 120), stream=True, allow_redirects=True) as response:
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

    def apply_hot_update(self, package: Path, info: UpdateInfo) -> bool:
        if not info.is_hot:
            raise ValueError("A atualização selecionada não é um hot update.")
        from hot_update_runtime import HOT_RUNTIME_API, install_hot_package
        if info.runtime_api != HOT_RUNTIME_API:
            raise ValueError("Hot update incompatível com este JARVIS.exe.")
        install_hot_package(package, expected_version=info.version)
        return True

    def launch_hot_restart(self) -> bool:
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--restart-after-pid", str(os.getpid())]
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        else:
            command = [sys.executable, str(self.app_dir / "main.py"), "--restart-after-pid", str(os.getpid())]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(command, cwd=str(self.app_dir), close_fds=True, creationflags=creationflags, env=env)
        return True

    @staticmethod
    def _temporarily_reset_windows_dll_directory():
        if os.name != "nt" or not getattr(sys, "frozen", False):
            return lambda: None
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            bundled = str(getattr(sys, "_MEIPASS", "") or "")
            kernel32.SetDllDirectoryW(None)
            def restore():
                try:
                    kernel32.SetDllDirectoryW(bundled if bundled else None)
                except Exception:
                    pass
            return restore
        except Exception:
            return lambda: None

    def launch_installer(self, installer: Path, update: bool = True) -> bool:
        installer = Path(installer).resolve()
        if not installer.exists():
            raise FileNotFoundError(str(installer))
        args = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS", f"/DIR={self.app_dir}"]
        if update:
            args.append("/UPDATE=1")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        restore_dll_dir = self._temporarily_reset_windows_dll_directory()
        try:
            subprocess.Popen(args, close_fds=True, creationflags=creationflags, env=dict(os.environ))
        finally:
            restore_dll_dir()
        return True


__all__ = ["GitHubReleaseUpdater", "UpdateInfo", "VALID_CHANNELS"]
