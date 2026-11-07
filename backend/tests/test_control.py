"""Month-8 snapshot tests (seed/project_ahmed.json). The seed is the acceptance criteria."""

from __future__ import annotations

import pytest

from app.seed_loader import load_schedule_template
from app.service import ahmed_record, dashboard_for


@pytest.fixture(scope="module")
def dash():
    return dashboard_for(ahmed_record(), load_schedule_template())


def test_physical_progress_is_58_percent(dash) -> None:
    assert round(dash.actual_progress_pct) == 58


def test_planned_progress_from_baseline_is_66_8_not_61(dash) -> None:
    # The seed snapshot says 61%. The baseline schedule with these work-package windows
    # gives 66.8% at day 274, and no cost-weighting we tried reproduces 61%. We report the
    # computed number rather than tuning it. See the summary for the decision.
    assert dash.planned_progress_pct == pytest.approx(66.78, abs=0.01)


def test_paid_committed_remaining(dash) -> None:
    assert dash.paid_sar == 1_150_000
    assert dash.committed_unpaid_sar == 640_000
    assert dash.remaining_uncommitted_sar == 420_000


def test_forecast_is_2_210_000(dash) -> None:
    assert dash.work_packages_baseline_sar == 2_100_000
    assert dash.approved_changes_sar == 34_000
    assert dash.risk_forecast_sar == 76_000
    assert dash.forecast_final_cost_sar == 2_210_000


def test_budget_and_forecast_gap(dash) -> None:
    assert dash.budget_excl_vat_sar == 2_310_000
    assert dash.forecast_vs_budget_sar == 100_000


def test_contingency_ledger_matches_seed(dash) -> None:
    assert dash.contingency_start_sar == 210_000
    assert [e.balance_after_sar for e in dash.contingency_ledger] == [192_000, 188_000, 176_000, 100_000]
    assert dash.contingency_left_sar == 100_000


def test_handover_slips_seven_days(dash) -> None:
    assert dash.baseline_handover_day == 456
    assert dash.forecast_handover_day == 463
    assert dash.handover_slip_days == 7


def test_rejected_then_approved_plumbing_inspection(dash) -> None:
    ins = next(i for i in dash.inspections if i.id == "HP-PLB-01")
    assert [e.status for e in ins.history] == ["submitted", "rejected", "approved"]
    assert ins.status == "approved"
    assert ins.history[1].reason == "Joint detail does not match approved design"
