"""
JARVIS - Gerenciamento de dispositivos de áudio do Windows.

Requer pycaw >= 20251023, versão que inclui SetDefaultDevice.
"""

from __future__ import annotations

import re
import unicodedata
import warnings
from difflib import SequenceMatcher
from typing import Dict, List, Optional


class AudioDeviceManager:
    def __init__(self, logger=None):
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
            r"[^a-z0-9]+",
            " ",
            value
        )
        return re.sub(
            r"\s+",
            " ",
            value
        ).strip()

    def _log(self, level: str, message: str):
        if not self.logger:
            return

        try:
            fn = getattr(
                self.logger,
                level,
                None
            )
            if callable(fn):
                try:
                    fn(
                        message,
                        "AUDIO"
                    )
                except TypeError:
                    fn(
                        message
                    )
        except Exception:
            pass

    def _imports(self):
        from pycaw.constants import (
            DEVICE_STATE,
            EDataFlow,
        )
        from pycaw.pycaw import (
            AudioUtilities,
        )

        return (
            DEVICE_STATE,
            EDataFlow,
            AudioUtilities,
        )

    def _devices(
        self,
        flow: str
    ) -> List:
        DEVICE_STATE, EDataFlow, AudioUtilities = (
            self._imports()
        )

        data_flow = (
            EDataFlow.eCapture.value
            if flow == "input"
            else EDataFlow.eRender.value
        )

        with warnings.catch_warnings():
            warnings.simplefilter(
                "ignore"
            )

            return list(
                AudioUtilities.GetAllDevices(
                    data_flow=data_flow,
                    device_state=DEVICE_STATE.ACTIVE.value,
                )
            )

    def list_devices(
        self,
        flow: str
    ) -> List[Dict]:
        devices = []

        for device in self._devices(
            flow
        ):
            try:
                devices.append({
                    "id": str(
                        device.id
                    ),
                    "name": str(
                        device.FriendlyName
                    ),
                })
            except Exception:
                continue

        return devices

    def _default_device(
        self,
        flow: str
    ) -> Optional[Dict]:
        _, _, AudioUtilities = (
            self._imports()
        )

        try:
            device = (
                AudioUtilities.GetMicrophone()
                if flow == "input"
                else AudioUtilities.GetSpeakers()
            )

            return {
                "id": str(
                    device.id
                ),
                "name": str(
                    device.FriendlyName
                ),
            }

        except Exception:
            return None

    def _aliases(
        self,
        query: str
    ) -> str:
        value = self._normalize(
            query
        )

        aliases = {
            "headset": [
                "headset",
                "headphone",
                "fone",
                "fone de ouvido",
            ],
            "speakers": [
                "speaker",
                "speakers",
                "alto falante",
                "alto falantes",
                "caixa",
                "caixas",
            ],
            "usb": [
                "usb",
                "microfone usb",
                "mic usb",
            ],
        }

        for canonical, words in aliases.items():
            if any(
                self._normalize(word)
                in value
                for word in words
            ):
                return canonical

        return value

    def _score(
        self,
        query: str,
        name: str
    ) -> float:
        q = self._normalize(
            query
        )
        n = self._normalize(
            name
        )

        alias = self._aliases(
            q
        )

        if not q or not n:
            return 0.0

        if q == n:
            return 1.0

        if q in n:
            return 0.96

        if alias == "headset":
            tokens = (
                "headset",
                "headphone",
                "fone",
            )
            if any(
                token in n
                for token in tokens
            ):
                return 0.93

        if alias == "speakers":
            tokens = (
                "speaker",
                "alto falante",
                "caixa",
            )
            if any(
                token in n
                for token in tokens
            ):
                return 0.93

        if alias == "usb" and "usb" in n:
            return 0.93

        q_tokens = set(
            q.split()
        )
        n_tokens = set(
            n.split()
        )

        overlap = (
            len(q_tokens & n_tokens)
            / max(
                1,
                len(q_tokens)
            )
        )

        ratio = SequenceMatcher(
            None,
            q,
            n
        ).ratio()

        return max(
            overlap * 0.90,
            ratio * 0.78
        )

    def _find(
        self,
        flow: str,
        query: str
    ):
        candidates = []

        for device in self._devices(
            flow
        ):
            try:
                name = str(
                    device.FriendlyName
                )
                score = self._score(
                    query,
                    name
                )

                if score >= 0.66:
                    candidates.append(
                        (
                            score,
                            device,
                            name
                        )
                    )
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        best = candidates[0]

        if (
            len(candidates) > 1
            and best[0] < 0.90
            and (
                best[0]
                - candidates[1][0]
            ) < 0.06
        ):
            return None

        return best

    def switch(
        self,
        flow: str,
        query: str
    ) -> Dict:
        try:
            _, _, AudioUtilities = (
                self._imports()
            )

            match = self._find(
                flow,
                query
            )

            if not match:
                names = [
                    item["name"]
                    for item in self.list_devices(
                        flow
                    )
                ]

                return {
                    "ok": False,
                    "message": (
                        "Não encontrei o dispositivo com segurança. "
                        "Disponíveis: "
                        + (
                            ", ".join(names)
                            if names
                            else "nenhum"
                        )
                    ),
                    "name": "",
                }

            _, device, name = match

            AudioUtilities.SetDefaultDevice(
                device.id
            )

            self._log(
                "info",
                f"Dispositivo padrão alterado ({flow}): {name}"
            )

            return {
                "ok": True,
                "message": (
                    f"✓ {'Microfone' if flow == 'input' else 'Saída de áudio'}: "
                    f"{name}."
                ),
                "name": name,
            }

        except Exception as exc:
            return {
                "ok": False,
                "message": (
                    f"Não consegui trocar o dispositivo de áudio: {exc}"
                ),
                "name": "",
            }

    def switch_output(
        self,
        query: str
    ) -> Dict:
        return self.switch(
            "output",
            query
        )

    def switch_input(
        self,
        query: str
    ) -> Dict:
        return self.switch(
            "input",
            query
        )

    def status(self) -> Dict:
        try:
            return {
                "ok": True,
                "output": self._default_device(
                    "output"
                ),
                "input": self._default_device(
                    "input"
                ),
                "outputs": self.list_devices(
                    "output"
                ),
                "inputs": self.list_devices(
                    "input"
                ),
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "output": None,
                "input": None,
                "outputs": [],
                "inputs": [],
            }
