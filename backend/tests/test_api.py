"""API tests through HTTP. Each test gets a fresh in-memory store, seeded like the real app."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore

AHMED = "ahmed-jeddah-villa"
INPUT = {
    "built_up_area_m2": 600,
    "plot_area_m2": 500,
    "floors": 2,
    "has_roof_annex": True,
    "has_basement": False,
    "finish_level": "standard",
    "city": "Jeddah",
}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app(MemoryStore())) as c:  # runs startup seeding
        yield c


def test_estimate_is_stateless_and_matches_seed(client: TestClient) -> None:
    r = client.post("/api/estimate", json=INPUT)
    assert r.status_code == 200
    body = r.json()
    assert body["total_incl_vat_sar"] == 2_656_500
    assert body["vat_sar"] == 346_500
    assert body["disclaimer"].startswith("estimate")
    assert len(body["bom_lines"]) == 36


def test_estimate_rejects_impossible_footprint(client: TestClient) -> None:
    r = client.post("/api/estimate", json={**INPUT, "floors": 1, "plot_area_m2": 500})
    assert r.status_code == 422
    assert "does not fit" in r.json()["detail"]


def test_estimate_rejects_bad_finish(client: TestClient) -> None:
    assert client.post("/api/estimate", json={**INPUT, "finish_level": "luxury"}).status_code == 422


def test_ahmed_is_seeded_on_startup(client: TestClient) -> None:
    r = client.get("/api/projects")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert AHMED in ids


def test_ahmed_dashboard_month_8(client: TestClient) -> None:
    r = client.get(f"/api/projects/{AHMED}/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert round(d["actual_progress_pct"]) == 58
    assert d["paid_sar"] == 1_150_000
    assert d["committed_unpaid_sar"] == 640_000
    assert d["remaining_uncommitted_sar"] == 424_200  # includes the 3% escalation on WP5
    assert d["forecast_final_cost_sar"] == 2_214_200
    assert d["contingency_left_sar"] == 100_420
    assert d["handover_slip_days"] == 7
    assert d["inspections"][0]["status"] == "approved"


def test_dashboard_accepts_status_day(client: TestClient) -> None:
    early = client.get(f"/api/projects/{AHMED}/dashboard?status_day=100").json()
    late = client.get(f"/api/projects/{AHMED}/dashboard?status_day=274").json()
    assert early["planned_progress_pct"] < late["planned_progress_pct"]


def test_schedule_endpoint(client: TestClient) -> None:
    r = client.get(f"/api/projects/{AHMED}/schedule")
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_handover_day"] == 463
    assert any(t["is_hold_point"] for t in body["tasks"])


def test_create_project_then_read_it(client: TestClient) -> None:
    r = client.post("/api/projects", json={"name": "Test villa", "input": INPUT})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["estimate"]["total_incl_vat_sar"] == 2_656_500
    dash = client.get(f"/api/projects/{pid}/dashboard").json()
    assert dash["forecast_handover_day"] == 456  # a new project has no changes yet


def test_adding_an_approved_change_moves_handover(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "Slip test", "input": INPUT}).json()["id"]
    change = {
        "month": 2, "type": "change_request", "title": "Revised foundation",
        "cost_sar": 18000, "days": 7, "approved_by": "engineer", "affects_task_id": "T08",
    }
    r = client.post(f"/api/projects/{pid}/changes", json=change)
    assert r.status_code == 201
    assert r.json()["id"] == "CH-01"
    dash = client.get(f"/api/projects/{pid}/dashboard").json()
    assert dash["handover_slip_days"] == 7


def test_change_on_unknown_task_is_rejected(client: TestClient) -> None:
    r = client.post(
        f"/api/projects/{AHMED}/changes",
        json={"month": 3, "type": "change_request", "title": "x", "affects_task_id": "T99"},
    )
    assert r.status_code == 422


def test_approved_inspection_cannot_change(client: TestClient) -> None:
    r = client.post(
        f"/api/projects/{AHMED}/inspections/HP-PLB-01/status",
        json={"status": "rejected", "by": "engineer", "reason": "again"},
    )
    assert r.status_code == 409


def test_unknown_inspection_is_404(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "No inspections", "input": INPUT}).json()["id"]
    assert client.post(f"/api/projects/{pid}/inspections/X/status", json={
        "status": "submitted", "by": "contractor"}).status_code == 404


def test_task_progress_update_changes_actual(client: TestClient) -> None:
    before = client.get(f"/api/projects/{AHMED}/dashboard").json()["actual_progress_pct"]
    r = client.patch(f"/api/projects/{AHMED}/tasks/T22", json={"percent_complete": 100})
    assert r.status_code == 200
    after = client.get(f"/api/projects/{AHMED}/dashboard").json()["actual_progress_pct"]
    assert after > before


def test_task_progress_rejects_out_of_range_and_unknown_task(client: TestClient) -> None:
    assert client.patch(f"/api/projects/{AHMED}/tasks/T22", json={"percent_complete": 101}).status_code == 422
    assert client.patch(f"/api/projects/{AHMED}/tasks/T99", json={"percent_complete": 5}).status_code == 404


def test_permits_are_listed(client: TestClient) -> None:
    items = client.get(f"/api/projects/{AHMED}/permits").json()
    assert len(items) == 6
    assert {i["blocks_task_id"] for i in items} >= {"T02", "T03", "T05", "T21"}


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/nope/dashboard").status_code == 404
