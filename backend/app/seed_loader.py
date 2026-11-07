"""Loads seed/*.json into the models. The only module that reads seed files.

Run `python -m app.seed_loader` from backend/ to load Ahmed's villa (month-8 state)
into the configured store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.models import (
    ChangeEvent,
    Commitment,
    Inspection,
    InspectionEvent,
    Payment,
    PermitItem,
    ProjectInput,
    TaskTemplate,
)

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
AHMED_ID = "ahmed-jeddah-villa"


def _read(name: str) -> dict:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def load_schedule_template() -> list[TaskTemplate]:
    return [TaskTemplate(**t) for t in _read("schedule_tasks.json")["tasks"]]


def load_permits() -> list[PermitItem]:
    return [PermitItem(**item) for item in _read("permits_checklist.json")["items"]]


@dataclass(frozen=True)
class AhmedSeed:
    project_id: str
    name: str
    project: ProjectInput
    changes: list[ChangeEvent]
    inspections: list[Inspection]
    payments: list[Payment]
    commitments: list[Commitment]
    task_progress_pct: dict[str, float]
    status_day: int
    physical_progress_pct: int
    planned_progress_pct: int


def load_ahmed() -> AhmedSeed:
    raw = _read("project_ahmed.json")
    p = raw["project"]
    project = ProjectInput(
        built_up_area_m2=p["built_up_area_m2"],
        plot_area_m2=p["plot_area_m2"],
        floors=p["floors"],
        has_roof_annex=p["has_roof_annex"],
        has_basement=p["has_basement"],
        finish_level=p["finish_level"],
        city=p["city"],
        budget_incl_vat_sar=p["budget_incl_vat_sar"],
    )
    changes = []
    for i, c in enumerate(raw["change_log"], start=1):
        changes.append(
            ChangeEvent(
                id=f"CH-{i:02d}",
                month=c["month"],
                type=c["type"],
                title=c["title"],
                cost_sar=c.get("cost_sar", 0),
                days=c.get("days", 0),
                days_avoided=c.get("days_avoided", 0),
                approved_by=c.get("approved_by"),
                affects_task_id=c.get("affects_task_id"),
                forecast=c.get("forecast", False),
            )
        )
    inspections = []
    for ins in raw["inspections"]:
        inspections.append(
            Inspection(
                id=ins["id"],
                month=ins["month"],
                task_id=ins["task_id"],
                title=ins["title"],
                history=[InspectionEvent(**event) for event in ins["status_history"]],
            )
        )
    progress = raw["task_progress_pct"]
    snapshot = raw["month8_snapshot"]
    return AhmedSeed(
        project_id=AHMED_ID,
        name="Ahmed's villa, Jeddah (illustrative)",
        project=project,
        changes=changes,
        inspections=inspections,
        payments=[Payment(**x) for x in raw["payments"]],
        commitments=[Commitment(**x) for x in raw["commitments"]],
        task_progress_pct=dict(progress["values"]),
        status_day=progress["status_day"],
        physical_progress_pct=snapshot["physical_progress_pct"],
        planned_progress_pct=snapshot["planned_progress_pct"],
    )


if __name__ == "__main__":  # pragma: no cover - exercised manually
    from app.service import seed_ahmed
    from app.store import get_store

    store = get_store()
    written = seed_ahmed(store, only_if_missing=False)
    print(f"Seeded {AHMED_ID} into {type(store).__name__}: {'written' if written else 'skipped'}")
