"""Budget accept/reject, permit baselines and document uploads."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.engine.budget import MIN_BUA_M2, next_option
from app.engine.estimate import estimate
from app.main import create_app
from app.models import ProjectInput
from app.store import MemoryStore

INPUT = {
    "built_up_area_m2": 600,
    "plot_area_m2": 500,
    "floors": 2,
    "finish_level": "premium",
    "has_basement": True,
}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app(MemoryStore())) as c:
        yield c


def _new_project(client: TestClient) -> str:
    r = client.post("/api/projects", json={"name": "Test villa", "input": INPUT})
    assert r.status_code == 201
    return r.json()["id"]


# ---- Engine -------------------------------------------------------------------

def test_each_rejection_is_strictly_cheaper() -> None:
    inp = ProjectInput(**INPUT)
    totals = [estimate(inp).proposed_budget_sar]
    for _ in range(12):
        inp, _change = next_option(inp)
        totals.append(estimate(inp).proposed_budget_sar)
    assert all(later < earlier for earlier, later in zip(totals, totals[1:]))


def test_levers_go_in_order_finish_then_basement_then_area() -> None:
    inp = ProjectInput(**INPUT)
    inp, change = next_option(inp)
    assert inp.finish_level == "standard" and "Finish" in change
    inp, change = next_option(inp)
    assert inp.finish_level == "economy"
    inp, change = next_option(inp)
    assert inp.has_basement is False and change == "Basement removed"
    inp, change = next_option(inp)
    assert inp.built_up_area_m2 == 570 and "570" in change


def test_no_cheaper_option_at_the_minimum() -> None:
    inp = ProjectInput(built_up_area_m2=MIN_BUA_M2, plot_area_m2=500, floors=2, finish_level="economy")
    with pytest.raises(ValueError, match="No cheaper option left"):
        next_option(inp)


# ---- Budget API -----------------------------------------------------------------

def test_new_project_proposes_a_budget(client: TestClient) -> None:
    pid = _new_project(client)
    budget = client.get(f"/api/projects/{pid}").json()["budget"]
    assert budget["status"] == "proposed"
    assert budget["rejections"] == 0
    assert budget["proposed_budget_sar"] > 0


def test_reject_reprices_on_a_cheaper_option(client: TestClient) -> None:
    pid = _new_project(client)
    before = client.get(f"/api/projects/{pid}").json()["budget"]["proposed_budget_sar"]
    r = client.post(f"/api/projects/{pid}/budget/reject")
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["rejections"] == 1
    assert body["budget"]["last_change"] == ["Finish premium → standard"]
    assert body["budget"]["proposed_budget_sar"] < before
    assert body["estimate"]["project"]["finish_level"] == "standard"


def test_accept_locks_the_budget(client: TestClient) -> None:
    pid = _new_project(client)
    r = client.post(f"/api/projects/{pid}/budget/accept")
    assert r.status_code == 200
    assert r.json()["budget"]["status"] == "accepted"
    assert r.json()["budget"]["accepted_budget_sar"] == r.json()["budget"]["proposed_budget_sar"]
    assert client.post(f"/api/projects/{pid}/budget/reject").status_code == 409
    assert client.post(f"/api/projects/{pid}/budget/accept").status_code == 409


def test_seeded_ahmed_budget_is_already_accepted(client: TestClient) -> None:
    body = client.get("/api/projects/ahmed-jeddah-villa").json()
    assert body["budget"]["status"] == "accepted"


# ---- Permits and documents ------------------------------------------------------

def test_permit_steps_carry_baseline_costs(client: TestClient) -> None:
    pid = _new_project(client)
    permits = {p["id"]: p for p in client.get(f"/api/projects/{pid}/permits").json()}
    assert permits["P03"]["baseline_cost_sar"] == 37_500  # building permit, midpoint of 15k–60k
    assert permits["P02"]["baseline_cost_sar"] == 16_500  # soil investigation, midpoint of 8k–25k
    assert permits["P04"]["baseline_cost_sar"] is None  # no allowance linked


def test_upload_document_against_a_permit(client: TestClient) -> None:
    pid = _new_project(client)
    r = client.post(
        f"/api/projects/{pid}/permits/P02/documents",
        files={"file": ("soil-report.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert r.status_code == 201
    assert r.json()["filename"] == "soil-report.pdf"
    permits = {p["id"]: p for p in client.get(f"/api/projects/{pid}/permits").json()}
    assert len(permits["P02"]["uploaded"]) == 1


def test_upload_rejects_wrong_type_and_unknown_permit(client: TestClient) -> None:
    pid = _new_project(client)
    bad_type = client.post(
        f"/api/projects/{pid}/permits/P02/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert bad_type.status_code == 415
    unknown = client.post(
        f"/api/projects/{pid}/permits/P99/documents",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    assert unknown.status_code == 404


def test_dashboard_reports_steps_and_work_packages(client: TestClient) -> None:
    d = client.get("/api/projects/ahmed-jeddah-villa/dashboard").json()
    assert d["steps_done"] == 11 and d["steps_total"] == 29
    assert d["work_packages_done"] == 2 and d["work_packages_total"] == 5
    assert len(d["work_package_progress"]) == 5
