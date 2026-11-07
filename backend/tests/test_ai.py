"""AI-assisted features. Mock mode for fixtures; a fake client for retry and guard behaviour.

No test here calls the real Gemini API.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.explain import TEMPLATES_AR, _accept, events_for, explain
from app.ai.gemini import GeminiClient
from app.ai.intake import ExtractedSpecs, run_intake
from app.ai.quote_compare import QuoteExtract, QuoteLineExtract, compare_quote
from app.engine.estimate import estimate
from app.main import create_app
from app.models import ProjectInput
from app.service import ahmed_record
from app.store import MemoryStore

DEMO_TEXT = "فيلا دورين وملحق ٦٠٠ متر في جدة، أرض ٥٠٠ متر، تشطيب عادي، الميزانية ٢٫٧ مليون"
ARABIC = "؀", "ۿ"


def has_arabic(text: str) -> bool:
    return any(ARABIC[0] <= ch <= ARABIC[1] for ch in text)


class FakeModels:
    """Stands in for client.models; returns scripted texts in order."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    def generate_content(self, **_: Any) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(text=self._texts.pop(0))


def fake_llm(texts: list[str]) -> tuple[GeminiClient, FakeModels]:
    llm = GeminiClient(mode="apikey", model="test-model", api_key="test-key")
    models = FakeModels(texts)
    llm._client = SimpleNamespace(models=models)
    return llm, models


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app(MemoryStore())) as c:
        yield c


# ---- Intake ------------------------------------------------------------------

def test_demo_sentence_fills_form_and_runs_engine() -> None:
    result = run_intake(DEMO_TEXT, GeminiClient(mode="mock", model=""))
    assert result.source == "mock"
    assert result.missing_fields == []
    assert result.project_input is not None
    assert result.project_input.built_up_area_m2 == 600
    assert result.estimate is not None
    assert result.estimate.total_incl_vat_sar == 2_656_500  # the engine computes this, not the model
    assert result.estimate.budget_fit.difference_sar == 43_500  # 2.7M minus 2,656,500


def test_demo_sentence_flags_soil_report_as_blocker() -> None:
    result = run_intake(DEMO_TEXT, GeminiClient(mode="mock", model=""))
    soil = next(m for m in result.missing_info if m.item == "soil_investigation")
    assert soil.severity == "blocker"
    blockers = [m.item for m in result.missing_info if m.severity == "blocker"]
    assert blockers == ["soil_investigation", "electrical_load_schedule"]


def test_mentioned_document_is_not_flagged() -> None:
    llm, _ = fake_llm([
        '{"built_up_area_m2": 600, "plot_area_m2": 500, "floors": 2, '
        '"documents_mentioned": ["soil_investigation"]}'
    ])
    result = run_intake("...", llm)
    assert "soil_investigation" not in {m.item for m in result.missing_info}


def test_missing_numbers_mean_no_estimate() -> None:
    result = run_intake("أريد فيلا صغيرة", GeminiClient(mode="mock", model=""))
    assert set(result.missing_fields) == {"built_up_area_m2", "plot_area_m2", "floors"}
    assert result.estimate is None and result.project_input is None


def test_unavailable_model_falls_back_without_network() -> None:
    llm = GeminiClient(mode="apikey", model="m", api_key=None)  # no key: must not call out
    result = run_intake(DEMO_TEXT, llm)
    assert result.source == "unavailable"
    assert result.estimate is None
    assert result.note is not None and "unavailable" in result.note


def test_invalid_output_is_retried_once_then_rejected() -> None:
    llm, models = fake_llm(["not json", '{"built_up_area_m2": "many"}'])
    assert llm.structured(prompt="p", schema=ExtractedSpecs, mock=ExtractedSpecs) is None
    assert models.calls == 2


def test_invalid_then_valid_recovers_on_retry() -> None:
    llm, models = fake_llm(["not json", '{"built_up_area_m2": 600, "plot_area_m2": 500, "floors": 2}'])
    got = llm.structured(prompt="p", schema=ExtractedSpecs, mock=ExtractedSpecs)
    assert got is not None and got.built_up_area_m2 == 600
    assert models.calls == 2


def test_intake_endpoint_accepts_text(client: TestClient) -> None:
    r = client.post("/api/intake", data={"text": DEMO_TEXT})
    assert r.status_code == 200
    assert r.json()["estimate"]["total_incl_vat_sar"] == 2_656_500


def test_intake_endpoint_requires_input(client: TestClient) -> None:
    assert client.post("/api/intake", data={"text": "  "}).status_code == 422


def test_intake_rejects_non_pdf_upload(client: TestClient) -> None:
    r = client.post("/api/intake", files={"spec_pdf": ("spec.txt", b"hello", "text/plain")})
    assert r.status_code == 415


# ---- Quote comparison --------------------------------------------------------

def test_quote_variances_and_scope_are_computed_in_python(client: TestClient) -> None:
    r = client.post("/api/projects/ahmed-jeddah-villa/quotes/compare", data={"text": "electrical quote"})
    assert r.status_code == 200
    body = r.json()
    cables = next(line for line in body["lines"] if line["matched_bom_id"] == "M28")
    assert cables["recomputed_amount_sar"] == 54_000
    assert cables["variance_sar"] == 4_500
    assert any(m["id"] == "M33" for m in body["missing_scope"])  # data cabling is not priced
    assert "Smart home automation (not in BOM)" in body["added_scope"]
    assert body["quote_total_sar"] == 185_900
    assert any("4,500 SAR" in q for q in body["questions"])  # 9% over the BOM line


def test_arithmetic_mismatch_is_flagged_and_recomputed() -> None:
    bom = estimate(ProjectInput(built_up_area_m2=600, plot_area_m2=500, floors=2)).bom_lines
    extract = QuoteExtract(lines=[QuoteLineExtract(description="Cables", qty=10, rate_sar=10,
                                                   amount_sar=150, matched_bom_id="M28")])
    result = compare_quote(extract, bom, source="mock")
    line = result.lines[0]
    assert line.arithmetic_ok is False
    assert line.quote_amount_sar == 100  # qty times rate, not the stated 150
    assert any("arithmetic" in q for q in result.questions)


def test_invented_bom_id_counts_as_unmatched() -> None:
    bom = estimate(ProjectInput(built_up_area_m2=600, plot_area_m2=500, floors=2)).bom_lines
    extract = QuoteExtract(lines=[QuoteLineExtract(description="Mystery", qty=1, rate_sar=5,
                                                   matched_bom_id="M99")])
    result = compare_quote(extract, bom, source="mock")
    assert result.lines[0].matched_bom_id is None
    assert result.added_scope == ["Mystery"]


# ---- Notifications -----------------------------------------------------------

def test_notifications_for_ahmed_are_templates_in_mock_mode(client: TestClient) -> None:
    items = client.get("/api/projects/ahmed-jeddah-villa/notifications").json()
    kinds = [n["kind"] for n in items]
    assert kinds.count("change_approved") == 3  # the forecast risk is not an approval
    assert "inspection_approved" in kinds
    assert all(n["source"] == "template" for n in items)
    assert all(has_arabic(n["text_ar"]) for n in items)


def test_rejected_inspection_produces_rejection_notice() -> None:
    record = ahmed_record()
    # Re-reject the seeded inspection so the latest state is "rejected".
    record.inspections[0].history.append(record.inspections[0].history[1])
    kinds = [kind for _, kind, _ in events_for(record)]
    assert "inspection_rejected" in kinds
    notice = explain("inspection_rejected", {"inspection_id": "HP-PLB-01", "reason": "x"},
                     GeminiClient(mode="mock", model=""), event_id="N")
    assert "HP-PLB-01" in notice.text_ar and has_arabic(notice.text_ar)


def test_gemini_text_with_invented_number_is_rejected() -> None:
    llm, _ = fake_llm(['{"text_ar": "تمت الموافقة على الفحص بعد 45 يوما"}'])
    note = explain("inspection_approved", {"inspection_id": "HP-PLB-01"}, llm, event_id="N")
    assert note.source == "template"


def test_gemini_text_using_only_facts_is_accepted() -> None:
    llm, _ = fake_llm(['{"text_ar": "تمت الموافقة على الفحص رقم HP-PLB-01 ويمكن المتابعة."}'])
    note = explain("inspection_approved", {"inspection_id": "HP-PLB-01"}, llm, event_id="N")
    assert note.source == "gemini"


def test_english_only_output_is_rejected() -> None:
    assert _accept("The inspection was approved", {"inspection_id": "X"}) is False


def test_every_template_has_arabic() -> None:
    for kind, text in TEMPLATES_AR.items():
        assert has_arabic(text), kind
