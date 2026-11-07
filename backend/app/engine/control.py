"""Cost and progress control (EVM-lite). Pure functions, no I/O.

- Planned %  : baseline schedule, cost-weighted by work package, at the status day.
- Actual %   : per-task % complete, cost-weighted the same way.
- Money      : paid, committed-but-unpaid, remaining uncommitted.
- Forecast   : baseline work packages + approved changes + risk forecast.
- Contingency: starts at the engine's contingency and is drawn by every change with a cost.
- Handover   : forecast finish against baseline finish (from engine/schedule.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.models import (
    ChangeEvent,
    Commitment,
    ContingencyEntry,
    Dashboard,
    Estimate,
    Inspection,
    Payment,
    ScheduledTask,
    ScheduleResult,
)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def planned_fraction(task: ScheduledTask, status_day: int) -> float:
    """Share of a task planned to be done at status_day, from baseline dates."""
    start, end = task.baseline_start_day, task.baseline_end_day
    if end <= start:  # milestone or hold point: done once its day arrives
        return 1.0 if status_day >= start else 0.0
    return _clamp01((status_day - start) / (end - start))


def _weighted_progress_by_wp(
    tasks: Sequence[ScheduledTask],
    fraction: Mapping[str, float],
    budgets: Mapping[str, int],
) -> float:
    """Cost-weighted % complete across work packages. Weight = baseline duration within a package."""
    total_budget = sum(budgets.values())
    if total_budget <= 0:
        return 0.0
    earned = 0.0
    for wp_id, budget in budgets.items():
        in_wp = [t for t in tasks if t.work_package_id == wp_id]
        weight = sum(max(t.baseline_end_day - t.baseline_start_day, 0) for t in in_wp)
        if weight == 0:
            continue
        done = sum(
            max(t.baseline_end_day - t.baseline_start_day, 0) * fraction.get(t.id, 0.0)
            for t in in_wp
        ) / weight
        earned += budget * done
    return 100.0 * earned / total_budget


def progress(
    schedule: ScheduleResult,
    estimate: Estimate,
    status_day: int,
    actual_pct_by_task: Mapping[str, float],
) -> tuple[float, float]:
    """Return (planned %, actual %) at status_day."""
    budgets = {wp.id: wp.budget_sar for wp in estimate.work_packages}
    planned_frac = {t.id: planned_fraction(t, status_day) for t in schedule.tasks}
    actual_frac = {tid: _clamp01(pct / 100.0) for tid, pct in actual_pct_by_task.items()}
    planned = _weighted_progress_by_wp(schedule.tasks, planned_frac, budgets)
    actual = _weighted_progress_by_wp(schedule.tasks, actual_frac, budgets)
    return round(planned, 2), round(actual, 2)


def contingency_ledger(start_sar: int, changes: Sequence[ChangeEvent]) -> list[ContingencyEntry]:
    """Every change with a cost draws on contingency, in month order."""
    entries: list[ContingencyEntry] = []
    balance = start_sar
    for c in sorted(changes, key=lambda x: x.month):
        if c.cost_sar <= 0:
            continue
        balance -= c.cost_sar
        entries.append(ContingencyEntry(label=c.title, amount_sar=c.cost_sar, balance_after_sar=balance))
    return entries


def compute_dashboard(
    *,
    estimate: Estimate,
    schedule: ScheduleResult,
    status_day: int,
    actual_pct_by_task: Mapping[str, float],
    payments: Sequence[Payment],
    commitments: Sequence[Commitment],
    changes: Sequence[ChangeEvent],
    inspections: Sequence[Inspection],
) -> Dashboard:
    planned_pct, actual_pct = progress(schedule, estimate, status_day, actual_pct_by_task)

    wp_baseline = estimate.work_packages_total_sar
    budget_excl_vat = estimate.subtotal_excl_vat_sar
    approved_changes = sum(c.cost_sar for c in changes if not c.forecast and c.approved_by)
    risk_forecast = sum(c.cost_sar for c in changes if c.forecast)
    forecast_final = wp_baseline + approved_changes + risk_forecast

    paid = sum(p.amount_sar for p in payments)
    committed_unpaid = sum(c.amount_sar for c in commitments)
    remaining = forecast_final - paid - committed_unpaid

    ledger = contingency_ledger(estimate.contingency_sar, changes)
    contingency_left = ledger[-1].balance_after_sar if ledger else estimate.contingency_sar

    return Dashboard(
        status_day=status_day,
        planned_progress_pct=planned_pct,
        actual_progress_pct=actual_pct,
        budget_excl_vat_sar=budget_excl_vat,
        work_packages_baseline_sar=wp_baseline,
        approved_changes_sar=approved_changes,
        risk_forecast_sar=risk_forecast,
        forecast_final_cost_sar=forecast_final,
        forecast_vs_budget_sar=budget_excl_vat - forecast_final,
        paid_sar=paid,
        committed_unpaid_sar=committed_unpaid,
        remaining_uncommitted_sar=remaining,
        contingency_start_sar=estimate.contingency_sar,
        contingency_left_sar=contingency_left,
        contingency_ledger=ledger,
        baseline_handover_day=schedule.baseline_handover_day,
        forecast_handover_day=schedule.forecast_handover_day,
        handover_slip_days=schedule.slip_days,
        critical_path=schedule.critical_path,
        change_log=list(changes),
        inspections=list(inspections),
    )
