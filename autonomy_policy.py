"""JARVIS Build 13.11 - politica real de Autonomia e Presenca.

Os percentuais controlam quanto trabalho o agente pode encadear, verificar, repetir
e quanto o JARVIS pode se manifestar proativamente. O modo direto evita confirmações
para ações comuns; somente operações de alto impacto ficam fora do fluxo automático.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


def snap_percent(value, default: int = 60) -> int:
    try:
        value = int(round(float(value) / 20.0) * 20)
    except Exception:
        value = int(default)
    return max(20, min(100, value))


LEGACY_AUTONOMY = {20: "manual", 40: "assistido", 60: "assistido", 80: "autonomo", 100: "autonomo"}
LEGACY_PRESENCE = {20: "discreto", 40: "assistente", 60: "assistente", 80: "jarvis", 100: "jarvis"}
LEGACY_TO_AUTONOMY = {"manual": 20, "assistido": 60, "autonomo": 80}
LEGACY_TO_PRESENCE = {"discreto": 20, "assistente": 60, "jarvis": 80}


@dataclass(frozen=True)
class AgentPolicy:
    autonomy_percent: int
    presence_percent: int
    max_steps: int
    retry_budget: int
    allow_goal_execution: bool
    allow_low_risk_unverified_continue: bool
    allow_safe_rule_execution: bool
    allow_behavior_suggestions: bool
    allow_proactive_notices: bool
    allow_spoken_proactive: bool
    min_proactive_severity: str
    label: str

    @property
    def autonomy_level(self) -> str:
        return LEGACY_AUTONOMY[self.autonomy_percent]

    @property
    def presence_level(self) -> str:
        return LEGACY_PRESENCE[self.presence_percent]

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["autonomy_level"] = self.autonomy_level
        data["presence_level"] = self.presence_level
        return data


_AUTONOMY_PROFILE = {
    20: dict(max_steps=1, retry_budget=0, allow_goal_execution=False, allow_low_risk_unverified_continue=False),
    40: dict(max_steps=2, retry_budget=0, allow_goal_execution=True, allow_low_risk_unverified_continue=False),
    60: dict(max_steps=4, retry_budget=1, allow_goal_execution=True, allow_low_risk_unverified_continue=False),
    80: dict(max_steps=6, retry_budget=1, allow_goal_execution=True, allow_low_risk_unverified_continue=True),
    100: dict(max_steps=8, retry_budget=2, allow_goal_execution=True, allow_low_risk_unverified_continue=True),
}

_PRESENCE_PROFILE = {
    20: dict(allow_safe_rule_execution=True, allow_behavior_suggestions=False, allow_proactive_notices=False, allow_spoken_proactive=False, min_proactive_severity="critical"),
    40: dict(allow_safe_rule_execution=True, allow_behavior_suggestions=False, allow_proactive_notices=True, allow_spoken_proactive=False, min_proactive_severity="critical"),
    60: dict(allow_safe_rule_execution=True, allow_behavior_suggestions=True, allow_proactive_notices=True, allow_spoken_proactive=False, min_proactive_severity="warning"),
    80: dict(allow_safe_rule_execution=True, allow_behavior_suggestions=True, allow_proactive_notices=True, allow_spoken_proactive=True, min_proactive_severity="critical"),
    100: dict(allow_safe_rule_execution=True, allow_behavior_suggestions=True, allow_proactive_notices=True, allow_spoken_proactive=True, min_proactive_severity="warning"),
}


def make_policy(autonomy_percent=60, presence_percent=60) -> AgentPolicy:
    a = snap_percent(autonomy_percent)
    p = snap_percent(presence_percent)
    spec = {**_AUTONOMY_PROFILE[a], **_PRESENCE_PROFILE[p]}
    label = {20: "basico", 40: "baixo", 60: "medio", 80: "alto", 100: "extra_alto"}[a]
    return AgentPolicy(a, p, label=label, **spec)


def percent_from_legacy_autonomy(level: str, default: int = 60) -> int:
    return LEGACY_TO_AUTONOMY.get(str(level or "").strip().lower(), snap_percent(default))


def percent_from_legacy_presence(level: str, default: int = 60) -> int:
    return LEGACY_TO_PRESENCE.get(str(level or "").strip().lower(), snap_percent(default))


__all__ = [
    "AgentPolicy", "make_policy", "snap_percent", "LEGACY_AUTONOMY", "LEGACY_PRESENCE",
    "percent_from_legacy_autonomy", "percent_from_legacy_presence",
]
