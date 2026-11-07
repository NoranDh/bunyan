"""Intake: free text (and optionally a spec PDF) -> ProjectInput fields + missing information.

Division of labour:
- Gemini reads the text and says which documents the user mentioned.
- Python decides what is missing (fixed checklist), what the engine still needs, and runs the estimate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.ai.gemini import GeminiClient
from app.engine.estimate import estimate
from app.models import IntakeResult, MissingInfo, ProjectInput

# Documents that must be checked on every intake (CLAUDE.md). The seed's three
# intake blockers/highs are soil, electrical load schedule and windows.
CHECKLIST: tuple[tuple[str, str, str, str, str], ...] = (
    # key, Arabic label, severity, why it matters
    ("soil_investigation", "تقرير فحص التربة", "blocker",
     "Foundation design and bearing capacity depend on the soil report."),
    ("electrical_load_schedule", "جدول الأحمال الكهربائية", "blocker",
     "The electrical scope and supply connection cannot be priced without it."),
    ("window_door_specs", "مواصفات النوافذ والأبواب", "high",
     "Windows and doors are priced from their specification; without it the price is only an allowance."),
    ("structural_drawings", "المخططات الإنشائية المعتمدة", "high",
     "Structural quantities (concrete and steel) are checked against approved drawings."),
    ("mep_drawings", "مخططات الكهروميكانيك", "high",
     "Plumbing, electrical and HVAC routes are needed before the MEP first fix."),
    ("building_permit_status", "حالة رخصة البناء", "high",
     "Site work cannot start before the building permit is issued."),
    ("finish_schedule", "جدول التشطيبات", "medium",
     "Finish choices set the architectural rates and the tiling and paint quantities."),
)
_KNOWN_KEYS = {key for key, *_ in CHECKLIST}
_REQUIRED_NUMBERS = ("built_up_area_m2", "plot_area_m2", "floors")


class ExtractedSpecs(BaseModel):
    """What Gemini may return. Every field is optional because the text may be silent."""

    built_up_area_m2: int | None = None
    plot_area_m2: int | None = None
    floors: int | None = Field(default=None, description="Above-ground levels, ground = 1")
    has_roof_annex: bool | None = None
    has_basement: bool | None = None
    finish_level: Literal["economy", "standard", "premium"] | None = None
    city: str | None = None
    budget_incl_vat_sar: int | None = None
    documents_mentioned: list[str] = Field(
        default_factory=list,
        description=f"Only these keys, if the text says the document exists: {sorted(_KNOWN_KEYS)}",
    )


INTAKE_PROMPT = """You extract building specifications from a Saudi homeowner's description.
Return only the JSON fields requested. Use null when the text does not say.
Convert Arabic-Indic digits and spoken amounts (for example "٢٫٧ مليون" = 2700000) to integers.
Do not estimate or invent values. Put a document key in documents_mentioned only if the text
says that document already exists. Allowed keys: {keys}.

Text:
{text}
"""


def _mock_intake(text: str) -> ExtractedSpecs:
    """Fixture for the reference sentence used in the demo; anything else extracts nothing."""
    if "600" in text or "٦٠٠" in text:
        return ExtractedSpecs(
            built_up_area_m2=600,
            plot_area_m2=500,
            floors=2,
            has_roof_annex=True,
            finish_level="standard",
            city="Jeddah",
            budget_incl_vat_sar=2_700_000,
            documents_mentioned=[],
        )
    return ExtractedSpecs()


def run_intake(text: str, llm: GeminiClient, pdf: bytes | None = None) -> IntakeResult:
    extracted = llm.structured(
        prompt=INTAKE_PROMPT.format(keys=sorted(_KNOWN_KEYS), text=text.strip()),
        schema=ExtractedSpecs,
        mock=lambda: _mock_intake(text),
        pdf=pdf,
    )
    note: str | None = None
    if extracted is None:
        extracted = ExtractedSpecs()
        note = "AI is unavailable. Enter the values in the form; the checklist still applies."
        source = "unavailable"
    else:
        source = "mock" if llm.mode == "mock" else "gemini"

    documents = {d for d in extracted.documents_mentioned if d in _KNOWN_KEYS}
    missing_info = [
        MissingInfo(item=key, item_ar=label, why_it_matters=why, severity=severity)  # type: ignore[arg-type]
        for key, label, severity, why in CHECKLIST
        if key not in documents
    ]

    missing_fields = [name for name in _REQUIRED_NUMBERS if getattr(extracted, name) is None]
    assumed: list[str] = []
    project_input: ProjectInput | None = None
    result_estimate = None

    if not missing_fields:
        if extracted.finish_level is None:
            assumed.append("finish_level = standard")
        if extracted.has_roof_annex is None:
            assumed.append("has_roof_annex = true (reference villa has a roof annex)")
        if extracted.has_basement is None:
            assumed.append("has_basement = false")
        if extracted.city is None:
            assumed.append("city = Jeddah")
        try:
            project_input = ProjectInput(
                built_up_area_m2=extracted.built_up_area_m2,  # type: ignore[arg-type]
                plot_area_m2=extracted.plot_area_m2,  # type: ignore[arg-type]
                floors=extracted.floors,  # type: ignore[arg-type]
                has_roof_annex=True if extracted.has_roof_annex is None else extracted.has_roof_annex,
                has_basement=bool(extracted.has_basement),
                finish_level=extracted.finish_level or "standard",
                city=extracted.city or "Jeddah",
                budget_incl_vat_sar=extracted.budget_incl_vat_sar,
            )
            result_estimate = estimate(project_input)
        except (ValidationError, ValueError) as exc:
            note = f"The values need a check: {exc}"

    return IntakeResult(
        source=source,
        extracted=extracted.model_dump(exclude_none=True),
        missing_fields=missing_fields,
        assumed_defaults=assumed,
        missing_info=missing_info,
        project_input=project_input,
        estimate=result_estimate,
        note=note,
    )
