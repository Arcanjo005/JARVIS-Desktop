"""Developer-channel shell for the rebuilt Qt interface."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu, QMessageBox

from github_updater import GitHubReleaseUpdater
from gui_qt_reference_v2 import JarvisGUI as ReferenceQtGUI
from jarvis_qt_composer_patch import install_composer_polish
from jarvis_version import BUILD, CHANNEL, VERSION


class _UpdateSignals(QObject):
    checked = Signal(object)
    failed = Signal(str)
    applied = Signal()


class JarvisGUI(ReferenceQtGUI):
    """Qt reference shell with stable/beta/dev update controls."""

    def __init__(self, logger, actions, core):
        super().__init__(logger, actions, core)
        # Keep the visual inside the QPushButtons themselves. No QLabel or
        # overlay is placed above the controls, so the whole 46x46 area stays
        # clickable. The polish object also filters key events on QTextEdit so
        # Enter sends and Shift+Enter inserts a new line.
        self._composer_polish = install_composer_polish(self.composer)
        self.updater = GitHubReleaseUpdater(
            current_version=VERSION,
            current_build=BUILD,
            channel=CHANNEL,
            logger=logger,
        )
        self._update_signals = _UpdateSignals(self)
        self._update_signals.checked.connect(self._update_checked)
        self._update_signals.failed.connect(self._update_failed)
        self._update_signals.applied.connect(self._update_applied)
        self.update_button.clicked.connect(self._manual_update_check)
        self.settings_button.clicked.connect(self._open_update_channel_menu)
        self._refresh_update_tooltip()

    def _refresh_update_tooltip(self) -> None:
        self.update_button.setToolTip(
            f"Verificar atualização - {VERSION} / {BUILD} / {self.updater.channel}"
        )

    def _open_update_channel_menu(self) -> None:
        menu = QMenu(self)
        menu.setTitle("Canal de atualização")
        for channel, label in (
            ("stable", "Stable"),
            ("beta", "Beta"),
            ("dev", "Dev"),
        ):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.updater.channel == channel)
            action.triggered.connect(lambda checked=False, value=channel: self._set_update_channel(value))
        menu.addSeparator()
        info = menu.addAction(f"Instalado: {VERSION} / {BUILD}")
        info.setEnabled(False)
        menu.exec(self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft()))

    def _set_update_channel(self, channel: str) -> None:
        try:
            self.updater.set_channel(channel)
            self._refresh_update_tooltip()
            QMessageBox.information(
                self,
                "Canal de atualização",
                f"Canal alterado para {channel.upper()}.\n\nO botão Atualizar agora consulta esse canal.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Canal de atualização", str(exc))

    def _manual_update_check(self) -> None:
        if not self.update_button.isEnabled():
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("…")

        def worker():
            try:
                info = self.updater.check(force_repair=True)
                self._update_signals.checked.emit(info)
            except Exception as exc:
                self._update_signals.failed.emit(f"{type(exc).__name__}: {exc}")

        threading.Thread(target=worker, name="JARVIS-QT-UPDATE-CHECK", daemon=True).start()

    def _reset_update_button(self) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText("↻")
        self._refresh_update_tooltip()

    def _update_checked(self, info) -> None:
        if info is None:
            self._reset_update_button()
            QMessageBox.information(
                self,
                "JARVIS Update",
                f"Nenhuma atualização disponível no canal {self.updater.channel.upper()}.",
            )
            return
        if info.repair:
            title = "Reparar instalação"
            text = f"A build {info.version} / {info.build_id or BUILD} já está instalada. Reinstalar esta build?"
        else:
            title = "Atualização disponível"
            text = (
                f"Canal: {info.channel.upper()}\n"
                f"Versão: {info.version}\n"
                f"Build: {info.build_id or 'release'}\n\n"
                "Baixar, validar o SHA-256 e instalar agora?"
            )
        answer = QMessageBox.question(self, title, text)
        if answer != QMessageBox.StandardButton.Yes:
            self._reset_update_button()
            return

        def worker():
            try:
                package = self.updater.download(info)
                if info.is_hot:
                    self.updater.apply_hot_update(package, info)
                    self.updater.launch_hot_restart()
                else:
                    self.updater.launch_installer(package, update=True)
                self._update_signals.applied.emit()
            except Exception as exc:
                self._update_signals.failed.emit(f"{type(exc).__name__}: {exc}")

        threading.Thread(target=worker, name="JARVIS-QT-UPDATE-APPLY", daemon=True).start()

    def _update_failed(self, message: str) -> None:
        self._reset_update_button()
        QMessageBox.warning(self, "JARVIS Update", f"Não foi possível atualizar.\n\n{message}")

    def _update_applied(self) -> None:
        self._reset_update_button()
        QMessageBox.information(
            self,
            "JARVIS Update",
            "Atualização iniciada. O JARVIS será fechado pelo instalador e abrirá novamente ao concluir.",
        )


__all__ = ["JarvisGUI"]
