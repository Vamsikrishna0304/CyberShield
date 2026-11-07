from dataclasses import dataclass

from app.models.event import Event

REMOTE_ADMIN_PORTS = {22, 3389, 445}
PRIVILEGED_ACTIONS = {"delete", "disable", "grant_admin", "privilege_escalation"}


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    level: str
    rules: tuple[str, ...]
    evidence: tuple[str, ...]


def assess_event(event: Event) -> RiskAssessment:
    score = 0
    rules: list[str] = []
    evidence: list[str] = []

    failed_auth = event.outcome.casefold() in {"failure", "failed", "denied"}
    authentication_event = "auth" in event.event_type.casefold()
    if failed_auth and authentication_event:
        score += 30
        rules.append("failed_authentication")
        evidence.append("Authentication event did not succeed")

    if (event.action or "").casefold() in PRIVILEGED_ACTIONS:
        score += 40
        rules.append("privileged_action")
        evidence.append(f"Sensitive action observed: {event.action}")

    if event.destination_port in REMOTE_ADMIN_PORTS:
        score += 15
        rules.append("remote_admin_port")
        evidence.append(f"Connection targeted remote-administration port {event.destination_port}")

    score = min(score, 100)
    if score >= 85:
        level = "critical"
    elif score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    elif score > 0:
        level = "low"
    else:
        level = "informational"

    return RiskAssessment(score, level, tuple(rules), tuple(evidence))
