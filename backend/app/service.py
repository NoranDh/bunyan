"""Glue between the store, the engine and the API. No calculations of its own."""

from __future__ import annotations

from collections.abc import Sequence

from app.engine.control import compute_dashboard
from app.engine.estimate import estimate
from app.engine.schedule import build_schedule
from app.models import (
    Dashboard,
    Estimate,
    ProjectInput,
    ProjectRecord,
    ScheduleResult,
    TaskTemplate,
)
from app.seed_loader import AHMED_ID, load_ahmed
from app.store import ProjectStore


def make_record(project_id: str, name: str, inp: ProjectInput, *, illustrative: bool = False) -> ProjectRecord:
    return ProjectRecord(
        id=project_id,
        name=name,
        input=inp,
        estimate=estimate(inp),
        illustrative=illustrative,
    )


def ahmed_record() -> ProjectRecord:
    seed = load_ahmed()
    record = make_record(seed.project_id, seed.name, seed.project, illustrative=True)
    record.changes = seed.changes
    record.inspections = seed.inspections
    record.payments = seed.payments
    record.commitments = seed.commitments
    record.task_progress_pct = seed.task_progress_pct
    record.status_day = seed.status_day
    return record


def schedule_for(record: ProjectRecord, template: Sequence[TaskTemplate]) -> ScheduleResult:
    return build_schedule(template, record.input.built_up_area_m2, record.changes)


def dashboard_for(
    record: ProjectRecord,
    template: Sequence[TaskTemplate],
    status_day: int | None = None,
) -> Dashboard:
    return compute_dashboard(
        estimate=record.estimate,
        schedule=schedule_for(record, template),
        status_day=record.status_day if status_day is None else status_day,
        actual_pct_by_task=record.task_progress_pct,
        payments=record.payments,
        commitments=record.commitments,
        changes=record.changes,
        inspections=record.inspections,
    )


def estimate_only(inp: ProjectInput) -> Estimate:
    return estimate(inp)


def seed_ahmed(store: ProjectStore, *, only_if_missing: bool = True) -> bool:
    """Load Ahmed's villa at its month-8 state. Returns True if it was written."""
    if only_if_missing and store.get_project(AHMED_ID) is not None:
        return False
    store.save_project(ahmed_record())
    return True
