"""Engine tests. The seed data contract in CLAUDE.md is the acceptance criteria."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.engine.estimate import LABOR_FACTORS, estimate
from app.models import ProjectInput

SEED = Path(__file__).resolve().parents[2] / "seed"

AHMED = ProjectInput(
    built_up_area_m2=600,
    plot_area_m2=500,
    floors=2,
    has_roof_annex=True,
    has_basement=False,
    finish_level="standard",
    city="Jeddah",
    budget_incl_vat_sar=2_656_500,
)


@pytest.fixture(scope="module")
def ref() -> object:
    return estimate(AHMED)


def _seed_csv() -> list[dict[str, str]]:
    with open(SEED / "bom_reference_600m2.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _seed_wps() -> list[dict[str, object]]:
    return json.loads((SEED / "work_packages.json").read_text(encoding="utf-8"))["work_packages"]


# ---- Seed data contract (CLAUDE.md) ----------------------------------------

def test_bom_has_36_lines(ref) -> None:
    assert len(ref.bom_lines) == 36


def test_materials_total_matches_seed(ref) -> None:
    assert ref.materials_total_sar == 1_282_790


def test_every_line_matches_seed_csv(ref) -> None:
    seed = {row["id"]: row for row in _seed_csv()}
    for line in ref.bom_lines:
        row = seed[line.id]
        assert line.qty == pytest.approx(float(row["qty"]), abs=1e-6), line.id
        assert line.rate_sar == pytest.approx(float(row["rate_sar"]), abs=1e-6), line.id
        assert line.amount_sar == int(round(float(row["amount_sar"]))), line.id


def test_work_packages_match_seed(ref) -> None:
    seed = {w["id"]: w["budget_sar"] for w in _seed_wps()}
    for wp in ref.work_packages:
        assert wp.budget_sar == seed[wp.id], wp.id
    assert ref.work_packages_total_sar == 2_100_000


def test_contingency_vat_and_total_match_seed(ref) -> None:
    assert ref.contingency_sar == 210_000
    assert ref.subtotal_excl_vat_sar == 2_310_000
    assert ref.vat_sar == 346_500
    assert ref.total_incl_vat_sar == 2_656_500


def test_within_half_percent_of_seed_totals(ref) -> None:
    # The plan's acceptance wording. Our reference is exact, so this always holds.
    assert abs(ref.total_incl_vat_sar - 2_656_500) / 2_656_500 <= 0.005
    assert abs(ref.materials_total_sar - 1_282_790) / 1_282_790 <= 0.005


def test_labor_factors_reproduce_from_seed() -> None:
    materials = {
        "WP1_site_foundations": 124_150,
        "WP2_structure": 310_390,
        "WP3_mep": 388_600,
        "WP4_finishes": 394_550,
        "WP5_external": 65_100,
    }
    for w in _seed_wps():
        assert LABOR_FACTORS[w["id"]] == pytest.approx(w["budget_sar"] / materials[w["id"]])


def test_reference_has_no_fit_gap(ref) -> None:
    assert ref.budget_fit.status == "on_budget"
    assert ref.budget_fit.difference_sar == 0


# ---- Behaviour ---------------------------------------------------------------

def test_800m2_premium_costs_more_than_600m2_standard() -> None:
    big = AHMED.model_copy(update={"built_up_area_m2": 800, "finish_level": "premium"})
    assert estimate(big).total_incl_vat_sar > estimate(AHMED).total_incl_vat_sar


def test_finish_level_moves_total() -> None:
    eco = estimate(AHMED.model_copy(update={"finish_level": "economy"})).total_incl_vat_sar
    std = estimate(AHMED).total_incl_vat_sar
    pre = estimate(AHMED.model_copy(update={"finish_level": "premium"})).total_incl_vat_sar
    assert eco < std < pre


def test_basement_increases_cost() -> None:
    with_basement = estimate(AHMED.model_copy(update={"has_basement": True}))
    assert with_basement.total_incl_vat_sar > estimate(AHMED).total_incl_vat_sar


def test_steel_override_wins_and_moves_total() -> None:
    base = estimate(AHMED)
    overridden = estimate(AHMED.model_copy(update={"rate_overrides": {"M02": 4000.0}}))
    steel = next(line for line in overridden.bom_lines if line.id == "M02")
    assert steel.rate_sar == 4000.0
    assert steel.rate_overridden is True
    assert steel.amount_sar == 48 * 4000
    assert overridden.total_incl_vat_sar > base.total_incl_vat_sar


def test_unknown_override_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown BOM line"):
        estimate(AHMED.model_copy(update={"rate_overrides": {"M99": 1.0}}))


def test_footprint_larger_than_plot_is_rejected() -> None:
    too_big = AHMED.model_copy(update={"floors": 1, "plot_area_m2": 500})
    with pytest.raises(ValueError, match="does not fit"):
        estimate(too_big)


def test_budget_fit_reports_over_and_under() -> None:
    over = estimate(AHMED.model_copy(update={"budget_incl_vat_sar": 2_500_000}))
    under = estimate(AHMED.model_copy(update={"budget_incl_vat_sar": 2_900_000}))
    assert over.budget_fit.status == "over" and over.budget_fit.difference_sar == -156_500
    assert under.budget_fit.status == "under" and under.budget_fit.difference_sar == 243_500


def test_estimate_is_deterministic() -> None:
    assert estimate(AHMED) == estimate(AHMED)


def test_every_assumption_is_listed_as_a_string(ref) -> None:
    assert ref.assumptions
    assert all(isinstance(a, str) and a for a in ref.assumptions)
