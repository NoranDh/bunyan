"""Contractor quote vs BOM. Gemini matches lines and reads the quote; Python does all arithmetic.

- Gemini (extract_quote): reads the quote text/PDF into lines and proposes which BOM line each one matches.
- Python (compare_quote): recomputes qty × rate, checks the stated amount, computes variances,
  finds scope missing or added, and writes the questions to ask. No model output is used for numbers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.gemini import GeminiClient
from app.engine.estimate import sar_round  # same half-up rounding as the engine
from app.models import BOMLine, BOMRef, QuoteComparison, QuoteLineResult

VARIANCE_QUESTION_PCT = 5.0  # ask about any matched line more than 5% off its BOM amount
ARITHMETIC_TOLERANCE = 0.005  # stated amount may differ from qty × rate by 0.5%


class QuoteLineExtract(BaseModel):
    description: str
    qty: float | None = None
    unit: str | None = None
    rate_sar: float | None = None
    amount_sar: float | None = None
    matched_bom_id: str | None = Field(default=None, description="A BOM id from the list, or null")


class QuoteExtract(BaseModel):
    supplier: str | None = None
    lines: list[QuoteLineExtract] = Field(default_factory=list)


QUOTE_PROMPT = """Read this contractor quote. Return one entry per priced line with the description,
quantity, unit, rate and amount, as written. Convert Arabic-Indic digits to Western digits.
For each line, set matched_bom_id to the BOM id whose item it describes, or null if none fits.
Do not compute totals. Only use ids from this list:
{bom}

Quote:
{text}
"""


def _mock_quote() -> QuoteExtract:
    """Fixture: an electrical quote that is priced high on cables, misses data cabling and adds smart home."""
    return QuoteExtract(
        supplier="Mock Electrical Co. (fixture)",
        lines=[
            QuoteLineExtract(description="Power and lighting cables", qty=4500, unit="m",
                             rate_sar=12, amount_sar=54000, matched_bom_id="M28"),
            QuoteLineExtract(description="Conduits, fittings and boxes", qty=3500, unit="m",
                             rate_sar=5, amount_sar=17500, matched_bom_id="M29"),
            QuoteLineExtract(description="Distribution boards and breakers", qty=5, unit="set",
                             rate_sar=7500, amount_sar=37500, matched_bom_id="M30"),
            QuoteLineExtract(description="Switches, sockets and accessories", qty=200, unit="point",
                             rate_sar=85, amount_sar=17000, matched_bom_id="M31"),
            QuoteLineExtract(description="Lighting fixtures", qty=130, unit="pc",
                             rate_sar=230, amount_sar=29900, matched_bom_id="M32"),
            QuoteLineExtract(description="Smart home automation (not in BOM)", qty=1, unit="lot",
                             rate_sar=30000, amount_sar=30000, matched_bom_id=None),
        ],
    )


def extract_quote(
    text: str, bom: list[BOMLine], llm: GeminiClient, pdf: bytes | None = None
) -> tuple[QuoteExtract | None, str]:
    bom_list = "\n".join(f"{line.id}: {line.item} ({line.unit})" for line in bom)
    extract = llm.structured(
        prompt=QUOTE_PROMPT.format(bom=bom_list, text=text.strip()),
        schema=QuoteExtract,
        mock=_mock_quote,
        pdf=pdf,
    )
    source = "unavailable" if extract is None else ("mock" if llm.mode == "mock" else "gemini")
    return extract, source


def compare_quote(
    extract: QuoteExtract | None,
    bom: list[BOMLine],
    *,
    source: str,
) -> QuoteComparison:
    """Pure function: all numbers here come from Python arithmetic."""
    if extract is None:
        return QuoteComparison(
            source="unavailable", lines=[], quote_total_sar=0, matched_bom_total_sar=0,
            variance_sar=0, missing_scope=[], added_scope=[], questions=[],
            note="The quote could not be read. Compare it by hand against the BOM.",
        )

    by_id = {line.id: line for line in bom}
    seen: set[str] = set()
    results: list[QuoteLineResult] = []
    questions: list[str] = []
    added: list[str] = []

    for q in extract.lines:
        # An id the model invented (not in the BOM) simply counts as unmatched.
        bom_line = by_id.get(q.matched_bom_id) if q.matched_bom_id else None

        recomputed: int | None = None
        arithmetic_ok = True
        if q.qty is not None and q.rate_sar is not None:
            recomputed = sar_round(q.qty * q.rate_sar)
            if q.amount_sar is not None and abs(recomputed - q.amount_sar) > max(1, ARITHMETIC_TOLERANCE * recomputed):
                arithmetic_ok = False
                questions.append(f"Ask the contractor to check the arithmetic on '{q.description}'.")
        quote_amount = recomputed if recomputed is not None else sar_round(q.amount_sar or 0)

        bom_amount: int | None = None
        variance: int | None = None
        variance_pct: float | None = None
        if bom_line is not None:
            seen.add(bom_line.id)
            bom_amount = bom_line.amount_sar
            variance = quote_amount - bom_amount
            variance_pct = round(100.0 * variance / bom_amount, 1) if bom_amount else None
            if variance_pct is not None and abs(variance_pct) > VARIANCE_QUESTION_PCT:
                questions.append(
                    f"Ask the contractor to explain the {abs(variance):,} SAR difference on '{bom_line.item}'."
                )
        else:
            added.append(q.description)
            questions.append(f"Confirm whether '{q.description}' is in scope and whether it is priced elsewhere.")

        results.append(
            QuoteLineResult(
                description=q.description,
                matched_bom_id=bom_line.id if bom_line else None,
                quote_qty=q.qty,
                quote_rate_sar=q.rate_sar,
                quote_amount_sar=quote_amount,
                recomputed_amount_sar=recomputed,
                arithmetic_ok=arithmetic_ok,
                bom_amount_sar=bom_amount,
                variance_sar=variance,
                variance_pct=variance_pct,
            )
        )

    # Scope missing: BOM lines in the same categories as the matched lines that the quote did not price.
    matched_categories = {by_id[i].category for i in seen}
    missing = [
        BOMRef(id=line.id, item=line.item, category=line.category, amount_sar=line.amount_sar)
        for line in bom
        if line.category in matched_categories and line.id not in seen
    ]
    for m in missing:
        questions.append(f"Ask whether '{m.item}' is excluded or priced in another package.")

    quote_total = sum(r.quote_amount_sar for r in results)
    matched_total = sum(r.bom_amount_sar or 0 for r in results)
    matched_quote_total = sum(r.quote_amount_sar for r in results if r.bom_amount_sar is not None)

    return QuoteComparison(
        source=source,  # type: ignore[arg-type]
        supplier=extract.supplier,
        lines=results,
        quote_total_sar=quote_total,
        matched_bom_total_sar=matched_total,
        variance_sar=matched_quote_total - matched_total,
        missing_scope=missing,
        added_scope=added,
        questions=questions,
    )
