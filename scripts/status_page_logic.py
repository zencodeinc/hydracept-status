"""Pure status-page state machine and display rules (probe + page honesty)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

UTC = timezone.utc

ComponentStatus = Literal["operational", "degraded", "down", "unknown"]
OverallStatus = Literal["operational", "degraded", "down", "unknown"]

CONSECUTIVE_FAILURES_FOR_DOWN = 3
DEFAULT_PROBE_INTERVAL_SECONDS = 300
STALE_AFTER_INTERVAL_MULTIPLIER = 3
DEFAULT_STALE_AFTER_SECONDS = DEFAULT_PROBE_INTERVAL_SECONDS * STALE_AFTER_INTERVAL_MULTIPLIER
HISTORY_DAYS = 90
MIN_SAMPLES_FOR_UPTIME = 144


@dataclass(frozen=True)
class ProbeOutcome:
    ok: bool
    detail: str


def derive_component_status(
    *,
    probe_ok: bool,
    consecutive_failures: int,
    failures_for_down: int = CONSECUTIVE_FAILURES_FOR_DOWN,
) -> tuple[ComponentStatus, int]:
    """Return (display_status, updated_consecutive_failures)."""
    if probe_ok:
        return "operational", 0
    failures = consecutive_failures + 1
    if failures >= failures_for_down:
        return "down", failures
    return "degraded", failures


def overall_from_components(
    component_statuses: dict[str, ComponentStatus],
    *,
    stale: bool,
) -> OverallStatus:
    if stale or not component_statuses:
        return "unknown"
    values = list(component_statuses.values())
    if any(s == "unknown" for s in values):
        return "unknown"
    if any(s == "down" for s in values):
        return "down"
    if any(s == "degraded" for s in values):
        return "degraded"
    return "operational"


def is_probe_stale(
    generated_at: str | None,
    *,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> bool:
    if not generated_at:
        return True
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = (now.astimezone(UTC) - parsed.astimezone(UTC)).total_seconds()
    return age > stale_after_seconds


def display_component_status(
    stored_status: ComponentStatus,
    *,
    stale: bool,
) -> ComponentStatus:
    """Page must never show operational when data is stale or stored status is not operational."""
    if stale:
        return "unknown"
    return stored_status


def assert_honest_display(stored: ComponentStatus, displayed: ComponentStatus) -> None:
    """Mutation guard: displayed status must not upgrade stored failure states."""
    rank = {"operational": 0, "degraded": 1, "down": 2, "unknown": 3}
    if rank[displayed] < rank.get(stored, 3):
        raise ValueError(f"display {displayed!r} upgrades stored {stored!r}")


def _today_utc(d: datetime | None = None) -> date:
    moment = d or datetime.now(tz=UTC)
    return moment.astimezone(UTC).date()


def roll_history_day(
    history: list[dict[str, Any]],
    *,
    day: date,
    sample_ok: bool,
    max_days: int = HISTORY_DAYS,
) -> list[dict[str, Any]]:
    """Append one probe sample to today's bucket; trim to max_days."""
    rows = [dict(row) for row in history if isinstance(row, dict)]
    key = day.isoformat()
    row = next((r for r in rows if r.get("date") == key), None)
    if row is None:
        row = {"date": key, "samples_ok": 0, "samples_total": 0, "uptime_ratio": 0.0}
        rows.append(row)
    row["samples_total"] = int(row.get("samples_total") or 0) + 1
    if sample_ok:
        row["samples_ok"] = int(row.get("samples_ok") or 0) + 1
    total = int(row["samples_total"])
    ok = int(row["samples_ok"])
    row["uptime_ratio"] = round(ok / total, 6) if total else 0.0
    rows.sort(key=lambda item: str(item.get("date") or ""))
    cutoff = day - timedelta(days=max_days - 1)
    trimmed = [r for r in rows if date.fromisoformat(str(r["date"])) >= cutoff]
    return trimmed


def total_history_samples(history: list[dict[str, Any]]) -> int:
    return sum(int(r.get("samples_total") or 0) for r in history if isinstance(r, dict))


def uptime_percent(history: list[dict[str, Any]], *, min_samples: int = MIN_SAMPLES_FOR_UPTIME) -> float | None:
    if not history:
        return None
    total = total_history_samples(history)
    if total < min_samples:
        return None
    ok = sum(int(r.get("samples_ok") or 0) for r in history if isinstance(r, dict))
    if total == 0:
        return None
    return round(100.0 * ok / total, 2)


def history_collecting(history: list[dict[str, Any]], *, min_samples: int = MIN_SAMPLES_FOR_UPTIME) -> bool:
    return total_history_samples(history) < min_samples
