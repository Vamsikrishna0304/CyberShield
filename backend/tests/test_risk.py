from app.models.event import Event
from app.services.risk import assess_event


def make_event(**overrides: object) -> Event:
    values = {
        "event_time": "2026-01-01T00:00:00Z",
        "event_type": "authentication",
        "outcome": "success",
        "action": None,
        "destination_port": None,
    }
    values.update(overrides)
    return Event(**values)


def test_failed_authentication_is_medium_risk() -> None:
    assessment = assess_event(make_event(outcome="failure"))
    assert assessment.score == 30
    assert assessment.level == "medium"
    assert assessment.rules == ("failed_authentication",)


def test_risk_rules_are_additive_and_capped() -> None:
    assessment = assess_event(
        make_event(outcome="denied", action="delete", destination_port=22)
    )
    assert assessment.score == 85
    assert assessment.level == "critical"
    assert len(assessment.rules) == 3


def test_unmatched_event_is_informational() -> None:
    assessment = assess_event(make_event(event_type="network", outcome="success"))
    assert assessment.score == 0
    assert assessment.level == "informational"
