"""Schedule tests: baseline, critical path, slips and scaling."""

from __future__ import annotations

import pytest

from app.engine.schedule import build_schedule, construction_scale
from app.models import ChangeEvent, TaskTemplate
from app.seed_loader import load_schedule_template


@pytest.fixture(scope="module")
def template() -> list[TaskTemplate]:
    return load_schedule_template()


def test_baseline_handover_is_end_of_month_14(template) -> None:
    result = build_schedule(template, 600)
    assert result.baseline_handover_day == 456
    assert result.forecast_handover_day == 456
    assert result.slip_days == 0


def test_critical_path_matches_seed_except_two_known_gaps(template) -> None:
    result = build_schedule(template, 600)
    seed_critical = {t.id for t in template if t.critical}
    computed = set(result.critical_path)
    # T17 and T20 feed the pressure-test hold point T21 with fixed gaps (+28 and +10 days),
    # so the engine treats them as tight. Engineers should confirm whether T21 can move.
    assert computed - seed_critical == {"T17", "T20"}
    assert seed_critical - computed == set()


def test_hold_point_is_marked(template) -> None:
    result = build_schedule(template, 600)
    holds = {t.id for t in result.tasks if t.is_hold_point}
    assert holds == {"T21"}


def test_approved_change_slips_handover_seven_days(template) -> None:
    change = ChangeEvent(
        id="CH-01", month=2, type="change_request", title="Revised foundation detail",
        cost_sar=18_000, days=7, approved_by="engineer", affects_task_id="T08",
    )
    result = build_schedule(template, 600, [change])
    assert result.forecast_handover_day == 463
    assert result.slip_days == 7


def test_forecast_item_does_not_move_schedule(template) -> None:
    risk = ChangeEvent(
        id="CH-02", month=8, type="risk_forecast", title="Risks", cost_sar=76_000,
        days=7, affects_task_id="T08", forecast=True,
    )
    assert build_schedule(template, 600, [risk]).slip_days == 0


def test_bigger_villa_stretches_construction_not_pre_construction(template) -> None:
    base = build_schedule(template, 600)
    big = build_schedule(template, 800)
    assert construction_scale(800) == pytest.approx((800 / 600) ** 0.5)
    assert big.forecast_handover_day > base.forecast_handover_day
    base_pre = {t.id: t.start_day for t in base.tasks if t.phase == "pre"}
    big_pre = {t.id: t.start_day for t in big.tasks if t.phase == "pre"}
    assert base_pre == big_pre


def test_unknown_dependency_is_rejected() -> None:
    bad = [TaskTemplate(id="A", phase="site", name="A", start_day=30, end_day=40, depends_on=["NOPE"])]
    with pytest.raises(ValueError, match="unknown task"):
        build_schedule(bad, 600)


def test_cycle_is_rejected() -> None:
    cyc = [
        TaskTemplate(id="A", phase="site", name="A", start_day=30, end_day=40, depends_on=["B"]),
        TaskTemplate(id="B", phase="site", name="B", start_day=40, end_day=50, depends_on=["A"]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        build_schedule(cyc, 600)
