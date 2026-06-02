"""Tests for Second Brain builtin tool observability helpers."""

from __future__ import annotations

from opentelemetry.trace.status import StatusCode

from app.agent.tools.builtin._observability import (
    SECOND_BRAIN_ERROR,
    SECOND_BRAIN_OK,
    record_second_brain_tool_observation,
)
from app.core.metrics import REGISTRY


class StubSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.status_code: StatusCode | None = None
        self.status_description: str | None = None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def set_status(self, status) -> None:  # noqa: ANN001
        self.status_code = status.status_code
        self.status_description = status.description


def test_record_observation_sets_attrs_and_metrics_delta() -> None:
    span = StubSpan()
    before_calls = _counter_value(
        "openagentd_second_brain_tool_calls_total",
        tool="vault_write",
        status=SECOND_BRAIN_ERROR,
    )
    before_duration_count = _histogram_count(
        "openagentd_second_brain_tool_duration_seconds",
        tool="vault_write",
        status=SECOND_BRAIN_ERROR,
    )

    record_second_brain_tool_observation(
        tool="vault_write",
        outcome="duplicate",
        status=SECOND_BRAIN_ERROR,
        duration_seconds=0.25,
        attributes={
            "vault.folder": "20-topics",
            "vault.path": "20-topics/existing.md",
            "vault.tags_count": 2,
        },
        span=span,
    )

    assert span.attributes["openagentd.second_brain.tool"] == "vault_write"
    assert span.attributes["openagentd.second_brain.outcome"] == "duplicate"
    assert span.attributes["vault.folder"] == "20-topics"
    assert span.attributes["vault.tags_count"] == 2
    assert span.status_code == StatusCode.ERROR
    assert span.status_description == "duplicate"
    assert (
        _counter_value(
            "openagentd_second_brain_tool_calls_total",
            tool="vault_write",
            status=SECOND_BRAIN_ERROR,
        )
        - before_calls
        == 1
    )
    assert (
        _histogram_count(
            "openagentd_second_brain_tool_duration_seconds",
            tool="vault_write",
            status=SECOND_BRAIN_ERROR,
        )
        - before_duration_count
        == 1
    )


def test_record_observation_ok_does_not_mark_span_error() -> None:
    span = StubSpan()

    record_second_brain_tool_observation(
        tool="vault_search",
        outcome="no_results",
        status=SECOND_BRAIN_OK,
        duration_seconds=0.01,
        attributes={"vault.result_count": 0},
        span=span,
    )

    assert span.attributes["openagentd.second_brain.outcome"] == "no_results"
    assert span.status_code is None


def _counter_value(metric_name: str, **labels: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name != metric_name.removesuffix("_total"):
            continue
        for sample in metric.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return 0.0


def _histogram_count(metric_name: str, **labels: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name != metric_name:
            continue
        for sample in metric.samples:
            if sample.name == f"{metric_name}_count" and sample.labels == labels:
                return sample.value
    return 0.0
