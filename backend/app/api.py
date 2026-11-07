"""HTTP routes under /api. Thin: validate, call the engine or store, return models."""

from __future__ import annotations

from functools import lru_cache
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from app.ai.explain import events_for, explain
from app.ai.gemini import get_llm
from app.ai.intake import run_intake
from app.ai.quote_compare import compare_quote, extract_quote
from app.engine.estimate import estimate
from app.models import (
    ChangeCreate,
    ChangeEvent,
    Commitment,
    CommitmentCreate,
    Dashboard,
    Estimate,
    Inspection,
    InspectionEvent,
    IntakeResult,
    InspectionStatusUpdate,
    PermitItem,
    Payment,
    PaymentCreate,
    ProjectCreate,
    ProjectInput,
    ProjectRecord,
    Notification,
    ProjectSummary,
    QuoteComparison,
    ScheduleResult,
    TaskProgressResult,
    TaskProgressUpdate,
    TaskTemplate,
)
from app.seed_loader import load_permits, load_schedule_template
from app.service import dashboard_for, make_record, schedule_for
from app.store import ProjectStore

router = APIRouter(prefix="/api")

MAX_PDF_BYTES = 10 * 1024 * 1024


async def _read_pdf(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    if upload.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload a PDF file")
    data = await upload.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF is larger than 10 MB")
    return data

# Allowed inspection moves. "approved" is final; a rejected item can be resubmitted.
_ALLOWED_NEXT: dict[str | None, set[str]] = {
    None: {"submitted"},
    "submitted": {"rejected", "approved"},
    "rejected": {"submitted"},
    "approved": set(),
}
_REQUIRED_BY: dict[str, str] = {"submitted": "contractor", "rejected": "engineer", "approved": "engineer"}


@lru_cache(maxsize=1)
def _template() -> list[TaskTemplate]:
    return load_schedule_template()


def get_store(request: Request) -> ProjectStore:
    return request.app.state.store


def _load(store: ProjectStore, project_id: str) -> ProjectRecord:
    record = store.get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return record


def _engine_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/estimate", response_model=Estimate)
def post_estimate(body: ProjectInput) -> Estimate:
    """Stateless estimate. Nothing is saved."""
    try:
        return estimate(body)
    except ValueError as exc:
        raise _engine_error(exc) from exc


@router.post("/projects", status_code=201, response_model=ProjectRecord)
def create_project(body: ProjectCreate, store: ProjectStore = Depends(get_store)) -> ProjectRecord:
    """Save an estimate as a project, with its baseline schedule computed on read."""
    project_id = f"proj-{uuid4().hex[:8]}"
    try:
        record = make_record(project_id, body.name, body.input)
    except ValueError as exc:
        raise _engine_error(exc) from exc
    store.save_project(record)
    return record


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(store: ProjectStore = Depends(get_store)) -> list[ProjectSummary]:
    return [
        ProjectSummary(
            id=r.id,
            name=r.name,
            city=r.input.city,
            built_up_area_m2=r.input.built_up_area_m2,
            total_incl_vat_sar=r.estimate.total_incl_vat_sar,
            illustrative=r.illustrative,
        )
        for r in store.list_projects()
    ]


@router.get("/projects/{project_id}", response_model=ProjectRecord)
def get_project(project_id: str, store: ProjectStore = Depends(get_store)) -> ProjectRecord:
    return _load(store, project_id)


@router.get("/projects/{project_id}/schedule", response_model=ScheduleResult)
def get_schedule(project_id: str, store: ProjectStore = Depends(get_store)) -> ScheduleResult:
    return schedule_for(_load(store, project_id), _template())


@router.get("/projects/{project_id}/dashboard", response_model=Dashboard)
def get_dashboard(
    project_id: str,
    status_day: int | None = Query(default=None, ge=0, le=2000),
    store: ProjectStore = Depends(get_store),
) -> Dashboard:
    return dashboard_for(_load(store, project_id), _template(), status_day)


@router.get("/projects/{project_id}/permits", response_model=list[PermitItem])
def get_permits(project_id: str, store: ProjectStore = Depends(get_store)) -> list[PermitItem]:
    _load(store, project_id)  # 404 if the project does not exist
    return load_permits()


@router.post("/projects/{project_id}/changes", status_code=201, response_model=ChangeEvent)
def add_change(
    project_id: str,
    body: ChangeCreate,
    store: ProjectStore = Depends(get_store),
) -> ChangeEvent:
    record = _load(store, project_id)
    if body.affects_task_id and body.affects_task_id not in {t.id for t in _template()}:
        raise HTTPException(status_code=422, detail=f"Unknown task {body.affects_task_id}")
    next_number = max((int(c.id.split("-")[1]) for c in record.changes), default=0) + 1
    change = ChangeEvent(id=f"CH-{next_number:02d}", **body.model_dump())
    record.changes.append(change)
    store.save_project(record)
    return change


@router.post(
    "/projects/{project_id}/inspections/{inspection_id}/status",
    response_model=Inspection,
)
def update_inspection(
    project_id: str,
    inspection_id: str,
    body: InspectionStatusUpdate,
    store: ProjectStore = Depends(get_store),
) -> Inspection:
    record = _load(store, project_id)
    inspection = next((i for i in record.inspections if i.id == inspection_id), None)
    if inspection is None:
        raise HTTPException(status_code=404, detail=f"Inspection {inspection_id} not found")

    current = inspection.history[-1].status if inspection.history else None
    if body.status not in _ALLOWED_NEXT[current]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move inspection from {current or 'new'} to {body.status}",
        )
    if body.by != _REQUIRED_BY[body.status]:
        raise HTTPException(
            status_code=422,
            detail=f"A {body.status} inspection must be recorded by the {_REQUIRED_BY[body.status]}",
        )
    if body.status == "rejected" and not body.reason:
        raise HTTPException(status_code=422, detail="A rejection needs a reason")

    inspection.history.append(InspectionEvent(**body.model_dump()))
    store.save_project(record)
    return inspection


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskProgressResult)
def update_task_progress(
    project_id: str,
    task_id: str,
    body: TaskProgressUpdate,
    store: ProjectStore = Depends(get_store),
) -> TaskProgressResult:
    record = _load(store, project_id)
    if task_id not in {t.id for t in _template()}:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    record.task_progress_pct[task_id] = body.percent_complete
    store.save_project(record)
    return TaskProgressResult(task_id=task_id, percent_complete=body.percent_complete)


# ---- AI-assisted routes (Phase 5). Language tasks only; numbers come from the engine. ----

@router.post("/intake", response_model=IntakeResult)
async def post_intake(
    text: str = Form(default=""),
    spec_pdf: UploadFile | None = File(default=None),
) -> IntakeResult:
    """Free text and/or a spec PDF -> proposed ProjectInput, missing information, and an estimate if complete."""
    if not text.strip() and spec_pdf is None:
        raise HTTPException(status_code=422, detail="Describe the villa or upload a spec PDF")
    pdf = await _read_pdf(spec_pdf)
    return run_intake(text, get_llm(), pdf)


@router.post("/projects/{project_id}/quotes/compare", response_model=QuoteComparison)
async def post_quote_compare(
    project_id: str,
    text: str = Form(default=""),
    quote_pdf: UploadFile | None = File(default=None),
    store: ProjectStore = Depends(get_store),
) -> QuoteComparison:
    record = _load(store, project_id)
    if not text.strip() and quote_pdf is None:
        raise HTTPException(status_code=422, detail="Paste the quote or upload a PDF")
    pdf = await _read_pdf(quote_pdf)
    bom = record.estimate.bom_lines
    extract, source = extract_quote(text, bom, get_llm(), pdf)
    return compare_quote(extract, bom, source=source)


@router.get("/projects/{project_id}/notifications", response_model=list[Notification])
def get_notifications(project_id: str, store: ProjectStore = Depends(get_store)) -> list[Notification]:
    record = _load(store, project_id)
    llm = get_llm()
    return [explain(kind, facts, llm, event_id=eid) for eid, kind, facts in events_for(record)]


def _next_id(prefix: str, existing: list[str]) -> str:
    numbers = [int(i.split("-")[1]) for i in existing if i.startswith(prefix + "-")]
    return f"{prefix}-{max(numbers, default=0) + 1:02d}"


@router.post("/projects/{project_id}/payments", status_code=201, response_model=Payment)
def add_payment(project_id: str, body: PaymentCreate, store: ProjectStore = Depends(get_store)) -> Payment:
    """Record money actually paid (for example, an approved interim payment certificate)."""
    record = _load(store, project_id)
    payment = Payment(id=_next_id("PAY", [p.id for p in record.payments]), **body.model_dump())
    record.payments.append(payment)
    store.save_project(record)
    return payment


@router.post("/projects/{project_id}/commitments", status_code=201, response_model=Commitment)
def add_commitment(project_id: str, body: CommitmentCreate, store: ProjectStore = Depends(get_store)) -> Commitment:
    """Record money agreed but not yet paid (for example, a signed subcontract)."""
    record = _load(store, project_id)
    commitment = Commitment(id=_next_id("COM", [c.id for c in record.commitments]), **body.model_dump())
    record.commitments.append(commitment)
    store.save_project(record)
    return commitment
