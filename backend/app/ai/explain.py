"""Plain-Arabic notifications for project events.

Gemini writes the sentence. Its output is used only if:
  1. it validates against the schema,
  2. it contains Arabic text,
  3. every number in it appears in the facts the engine supplied.
Otherwise the fixed Arabic template for that event is used. Nothing is invented.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from app.ai.gemini import GeminiClient
from app.models import Notification, ProjectRecord

EventKind = Literal["inspection_rejected", "inspection_approved", "change_approved"]

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")

TEMPLATES_AR: dict[str, str] = {
    "inspection_rejected": (
        "تم رفض فحص الأعمال رقم {inspection_id}. لا يمكن المتابعة قبل تصحيح الأعمال "
        "وموافقة المهندس على الإعادة."
    ),
    "inspection_approved": (
        "تمت الموافقة على الفحص رقم {inspection_id}، ويمكن المتابعة في الأعمال التالية."
    ),
    "change_approved": (
        "تمت الموافقة على تعديل بتكلفة {cost_sar} ريال"
        "{days_clause}."
    ),
}
_DAYS_CLAUSE_AR = " وتأخير الجدول {days} يوم"


class ArabicNotice(BaseModel):
    text_ar: str


PROMPT = """Write one or two sentences in plain Modern Standard Arabic for a first-time Saudi homeowner.
No jargon. Use only the facts below. Do not add numbers, dates or names that are not in the facts.

Event: {kind}
Facts: {facts}
"""


def _numbers(text: str) -> set[str]:
    normalised = text.translate(_ARABIC_DIGITS)
    return {n.replace(",", "") for n in _NUMBER.findall(normalised)}


def _facts_text(facts: dict[str, str | int | float]) -> str:
    return " ".join(str(v) for v in facts.values()).replace(",", "")


def _accept(text: str, facts: dict[str, str | int | float]) -> bool:
    if not text.strip() or len(text) > 400 or not _ARABIC_LETTER.search(text):
        return False
    allowed = _facts_text(facts)
    return all(n in allowed for n in _numbers(text))


def _render(kind: str, facts: dict[str, str | int | float]) -> str:
    template = TEMPLATES_AR[kind]
    if kind == "change_approved":
        days = int(facts.get("days", 0))
        clause = _DAYS_CLAUSE_AR.format(days=days) if days else ""
        return template.format(cost_sar=f"{int(facts['cost_sar']):,}", days_clause=clause)
    return template.format(**facts)


def explain(kind: EventKind, facts: dict[str, str | int | float], llm: GeminiClient, *, event_id: str) -> Notification:
    prompt = PROMPT.format(kind=kind, facts="; ".join(f"{k}: {v}" for k, v in facts.items()))
    notice = llm.structured(
        prompt=prompt,
        schema=ArabicNotice,
        mock=lambda: ArabicNotice(text_ar=""),  # mock mode uses the template, deliberately
    )
    if notice is not None and _accept(notice.text_ar, facts):
        return Notification(id=event_id, kind=kind, text_ar=notice.text_ar.strip(), source="gemini", facts=facts)
    source = "template"
    return Notification(id=event_id, kind=kind, text_ar=_render(kind, facts), source=source, facts=facts)


def events_for(record: ProjectRecord) -> list[tuple[str, EventKind, dict[str, str | int | float]]]:
    """Events the engine has already decided, in a stable order."""
    out: list[tuple[str, EventKind, dict[str, str | int | float]]] = []
    for ins in record.inspections:
        if not ins.history:
            continue
        last = ins.history[-1]
        if last.status == "rejected":
            facts: dict[str, str | int | float] = {
                "inspection_id": ins.id,
                "reason": last.reason or "",
            }
            out.append((f"N-{ins.id}-rejected", "inspection_rejected", facts))
        elif last.status == "approved":
            out.append((f"N-{ins.id}-approved", "inspection_approved", {"inspection_id": ins.id}))
    for c in record.changes:
        if c.forecast or not c.approved_by:
            continue
        facts = {"cost_sar": c.cost_sar, "days": c.days, "title": c.title}
        out.append((f"N-{c.id}-approved", "change_approved", facts))
    return out

