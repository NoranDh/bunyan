"""Glue between the store, the engine and the API. No calculations of its own."""

from __future__ import annotations

from collections.abc import Sequence

from app.engine.budget import next_option
from app.engine.control import compute_dashboard
from app.engine.estimate import estimate
from app.engine.schedule import build_schedule
from app.models import (
    BudgetDecision,
    BudgetProposal,
    Dashboard,
    Estimate,
    PermitItem,
    PermitView,
    ProjectInput,
    ProjectRecord,
    ScheduleResult,
    TaskTemplate,
)
from app.seed_loader import AHMED_ID, load_ahmed
from app.store import ProjectStore


class BudgetStateError(ValueError):
    """The budget cannot move that way, for example rejecting after it was accepted."""


def make_record(project_id: str, name: str, inp: ProjectInput, *, illustrative: bool = False) -> ProjectRecord:
    est = estimate(inp)
    return ProjectRecord(
        id=project_id,
        name=name,
        input=inp,
        estimate=est,
        budget=BudgetProposal(status="proposed", proposed_budget_sar=est.proposed_budget_sar),
        illustrative=illustrative,
    )


def ahmed_record() -> ProjectRecord:
    seed = load_ahmed()
    record = make_record(seed.project_id, seed.name, seed.project, illustrative=True)
    # The seed project is already under way, so its budget was accepted at signing.
    record.budget = BudgetProposal(
        status="accepted",
        proposed_budget_sar=record.estimate.proposed_budget_sar,
        accepted_budget_sar=record.estimate.proposed_budget_sar,
    )
    record.changes = seed.changes
    record.inspections = seed.inspections
    record.payments = seed.payments
    record.commitments = seed.commitments
    record.task_progress_pct = seed.task_progress_pct
    record.status_day = seed.status_day
    return record


def accept_budget(record: ProjectRecord) -> BudgetDecision:
    if record.budget.status == "accepted":
        raise BudgetStateError("The budget is already accepted.")
    amount = record.estimate.proposed_budget_sar
    record.budget = BudgetProposal(
        status="accepted",
        proposed_budget_sar=amount,
        accepted_budget_sar=amount,
        rejections=record.budget.rejections,
        last_change=record.budget.last_change,
    )
    return BudgetDecision(budget=record.budget, estimate=record.estimate)


def reject_budget(record: ProjectRecord) -> BudgetDecision:
    """Move to the next cheaper option and propose its budget. Raises ValueError when none is left."""
    if record.budget.status == "accepted":
        raise BudgetStateError("The budget is already accepted and cannot be rejected.")
    cheaper, change = next_option(record.input)
    new_estimate = estimate(cheaper)
    record.input = cheaper
    record.estimate = new_estimate
    record.budget = BudgetProposal(
        status="proposed",
        proposed_budget_sar=new_estimate.proposed_budget_sar,
        rejections=record.budget.rejections + 1,
        last_change=[change],
    )
    return BudgetDecision(budget=record.budget, estimate=record.estimate)


def permit_views(record: ProjectRecord, permits: Sequence[PermitItem]) -> list[PermitView]:
    """Each permit step with the baseline cost of its allowance and the documents uploaded so far."""
    views: list[PermitView] = []
    for p in permits:
        allowances = [a for a in record.estimate.allowances if a.permit_id == p.id]
        views.append(
            PermitView(
                **p.model_dump(),
                baseline_cost_sar=sum(a.baseline_sar for a in allowances) if allowances else None,
                uploaded=[d for d in record.documents if d.permit_id == p.id],
            )
        )
    return views


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
