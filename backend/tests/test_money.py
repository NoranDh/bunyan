"""POST endpoints for payments and commitments."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore

AHMED = "ahmed-jeddah-villa"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app(MemoryStore())) as c:
        yield c


def test_add_payment_updates_paid_total(client: TestClient) -> None:
    before = client.get(f"/api/projects/{AHMED}/dashboard").json()["paid_sar"]
    r = client.post(f"/api/projects/{AHMED}/payments",
                    json={"month": 8, "amount_sar": 50000, "description": "IPC 7"})
    assert r.status_code == 201
    assert r.json()["id"] == "PAY-07"  # seed has PAY-01 to PAY-06
    after = client.get(f"/api/projects/{AHMED}/dashboard").json()["paid_sar"]
    assert after == before + 50_000


def test_add_commitment_updates_committed_and_remaining(client: TestClient) -> None:
    before = client.get(f"/api/projects/{AHMED}/dashboard").json()
    r = client.post(f"/api/projects/{AHMED}/commitments",
                    json={"amount_sar": 30000, "description": "Paint subcontract"})
    assert r.status_code == 201
    assert r.json()["id"] == "COM-04"  # seed has COM-01 to COM-03
    after = client.get(f"/api/projects/{AHMED}/dashboard").json()
    assert after["committed_unpaid_sar"] == before["committed_unpaid_sar"] + 30_000
    assert after["remaining_uncommitted_sar"] == before["remaining_uncommitted_sar"] - 30_000


def test_payment_rejects_zero_or_negative_amount(client: TestClient) -> None:
    for amount in (0, -5):
        r = client.post(f"/api/projects/{AHMED}/payments",
                        json={"month": 1, "amount_sar": amount, "description": "x"})
        assert r.status_code == 422


def test_money_on_unknown_project_is_404(client: TestClient) -> None:
    assert client.post("/api/projects/nope/payments",
                       json={"month": 1, "amount_sar": 1, "description": "x"}).status_code == 404
    assert client.post("/api/projects/nope/commitments",
                       json={"amount_sar": 1, "description": "x"}).status_code == 404
