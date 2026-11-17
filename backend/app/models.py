"""Pydantic schemas shared by the engine, the store and the API.

Conventions (from CLAUDE.md):
- Money is integer SAR in storage. Rates are SAR excluding VAT.
- VAT is always reported separately from the pre-VAT subtotal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

FinishLevel = Literal["economy", "standard", "premium"]


class ProjectInput(BaseModel):
    """What the user tells us about the villa. Fed to engine/estimate.py."""

    built_up_area_m2: int = Field(gt=0, description="Built-up area (BUA), m²")
    plot_area_m2: int = Field(gt=0, description="Plot area, m²")
    floors: int = Field(ge=1, le=3, description="Above-ground floors (ground = 1)")
    has_roof_annex: bool = True
    has_basement: bool = False
    finish_level: FinishLevel = "standard"
    city: str = "Jeddah"
    duration_months: int = Field(default=12, ge=1, le=60, description="Build duration. Above 12 months, later work is escalated.")
    annual_inflation_pct: float = Field(default=0.03, ge=0, le=0.2, description="Yearly rise in material and labour prices (ASSUMPTION)")
    rate_overrides: dict[str, float] = Field(
        default_factory=dict,
        description="BOM line id -> SAR rate; an override wins over the reference rate.",
    )


class CalcStep(BaseModel):
    """One step of a calculation, shown as a row in the UI: what was done, with what, and the result."""

    label: str
    formula: str
    result: str
    source: str | None = None


class BOMLine(BaseModel):
    id: str
    category: str
    item: str
    unit: str
    qty: float
    rate_sar: float
    amount_sar: int
    rate_overridden: bool = False
    work_package_split: dict[str, float]
    calculation: list[CalcStep] = Field(default_factory=list)


class WorkPackageBudget(BaseModel):
    id: str
    name: str
    months: str
    materials_sar: int
    labor_factor: float
    budget_sar: int = Field(description="After escalation")
    escalation_years: int = 0
    escalation_sar: int = 0
    calculation: list[CalcStep] = Field(default_factory=list)


class AllowanceLine(BaseModel):
    """A cost outside the BOM (permits, soil, survey, utilities, fees). Baseline until real figures exist."""

    id: str
    item: str
    basis: Literal["fixed", "percent"]
    low_sar: int
    high_sar: int
    baseline_sar: int
    permit_id: str | None = None
    calculation: list[CalcStep] = Field(default_factory=list)


class BudgetProposal(BaseModel):
    """The estimator proposes a budget; the owner accepts it or rejects it for a cheaper option."""

    status: Literal["proposed", "accepted"]
    proposed_budget_sar: int = Field(description="Construction incl. VAT plus allowances")
    accepted_budget_sar: int | None = None
    rejections: int = 0
    last_change: list[str] = Field(default_factory=list, description="What the latest rejection cut")


class Estimate(BaseModel):
    project: ProjectInput
    bom_lines: list[BOMLine]
    work_packages: list[WorkPackageBudget]
    materials_total_sar: int
    work_packages_total_sar: int
    contingency_pct: float
    contingency_sar: int
    subtotal_excl_vat_sar: int
    vat_pct: float
    vat_sar: int
    total_incl_vat_sar: int
    cost_per_m2_excl_vat_sar: int
    allowances: list[AllowanceLine]
    allowances_total_sar: int = Field(description="Not VAT-bearing in this model (ASSUMPTION)")
    proposed_budget_sar: int = Field(description="total_incl_vat + allowances_total: the figure the owner accepts or rejects")
    totals_calculation: list[CalcStep] = Field(default_factory=list)
    assumptions: list[str]
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "estimate — requires review by a licensed engineering office"
    )


# ---- Schedule (Phase 2) ----------------------------------------------------

TaskType = Literal["task", "milestone", "hold_point"]


class TaskTemplate(BaseModel):
    """One row of the baseline schedule (seed/schedule_tasks.json). Day 0 = start of Month 0."""

    id: str
    phase: str
    name: str
    start_day: int
    end_day: int
    critical: bool = False
    depends_on: list[str] = Field(default_factory=list)
    type: TaskType = "task"


class ScheduledTask(BaseModel):
    id: str
    phase: str
    name: str
    type: TaskType
    baseline_start_day: int
    baseline_end_day: int
    start_day: int  # forecast start (after approved slips)
    end_day: int  # forecast end
    duration_days: int
    float_days: int
    is_critical: bool
    is_hold_point: bool
    depends_on: list[str]
    work_package_id: str | None = None


class ScheduleResult(BaseModel):
    tasks: list[ScheduledTask]
    critical_path: list[str]
    baseline_handover_day: int
    forecast_handover_day: int
    slip_days: int
    construction_scale: float = Field(description="(BUA ÷ 600)^0.5 applied to construction tasks")


# ---- Change log, money, inspections (Phase 2) -------------------------------

class ChangeEvent(BaseModel):
    id: str
    month: int
    type: Literal["change_request", "procurement_risk", "quote_variance", "risk_forecast"]
    title: str
    cost_sar: int = 0
    days: int = 0  # schedule slip caused by an approved change
    days_avoided: int = 0  # a risk that was handled and no longer slips the plan
    approved_by: str | None = None
    affects_task_id: str | None = None
    forecast: bool = False  # True for a forecast, not a decision that has been made


class Payment(BaseModel):
    id: str
    month: int
    amount_sar: int
    description: str


class Commitment(BaseModel):
    id: str
    amount_sar: int
    description: str


class InspectionEvent(BaseModel):
    status: Literal["submitted", "rejected", "approved"]
    by: Literal["contractor", "engineer"]
    reason: str | None = None
    note: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Inspection(BaseModel):
    id: str
    month: int
    task_id: str
    title: str
    history: list[InspectionEvent]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        return self.history[-1].status if self.history else "submitted"


# ---- Control / dashboard (Phase 2) ------------------------------------------

class ContingencyEntry(BaseModel):
    label: str
    amount_sar: int  # positive = drawn from contingency
    balance_after_sar: int


class WorkPackageProgress(BaseModel):
    id: str
    name: str
    steps_total: int
    steps_done: int
    percent_complete: float = Field(description="Cost-weighted, from the task % complete")


class Dashboard(BaseModel):
    status_day: int
    planned_progress_pct: float
    actual_progress_pct: float
    steps_total: int
    steps_done: int
    steps_done_pct: float
    work_packages_total: int
    work_packages_done: int
    work_packages_done_pct: float
    work_package_progress: list[WorkPackageProgress]
    budget_excl_vat_sar: int
    work_packages_baseline_sar: int
    approved_changes_sar: int
    risk_forecast_sar: int
    forecast_final_cost_sar: int
    forecast_vs_budget_sar: int  # budget − forecast; positive = under budget
    paid_sar: int
    committed_unpaid_sar: int
    remaining_uncommitted_sar: int
    contingency_start_sar: int
    contingency_left_sar: int
    contingency_ledger: list[ContingencyEntry]
    baseline_handover_day: int
    forecast_handover_day: int
    handover_slip_days: int
    critical_path: list[str]
    change_log: list[ChangeEvent]
    inspections: list[Inspection]


# ---- Permits and stored project (Phase 3) -----------------------------------

class PermitItem(BaseModel):
    """One step of معاملات البناء, linked to the schedule task it blocks."""

    id: str
    title_ar: str
    title_en: str
    owner: Literal["owner", "engineer", "contractor"]
    blocks_task_id: str
    documents: list[str] = Field(default_factory=list, description="Documents this step needs")
    status: str = "to_verify"  # to_verify until checked with construction experts


class ProjectDocument(BaseModel):
    """A file the owner uploaded against a permit or soil step. Metadata only for now."""

    id: str
    permit_id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: str


class PermitView(PermitItem):
    """A permit step with its baseline cost and the documents uploaded so far."""

    baseline_cost_sar: int | None = None
    uploaded: list[ProjectDocument] = Field(default_factory=list)


class ProjectRecord(BaseModel):
    """What the store keeps for one project. Schedule and dashboard are recomputed from this."""

    id: str
    name: str
    input: ProjectInput
    estimate: Estimate
    budget: BudgetProposal
    task_progress_pct: dict[str, float] = Field(default_factory=dict)
    status_day: int = 0
    changes: list[ChangeEvent] = Field(default_factory=list)
    inspections: list[Inspection] = Field(default_factory=list)
    payments: list[Payment] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    documents: list[ProjectDocument] = Field(default_factory=list)
    illustrative: bool = False


class BudgetDecision(BaseModel):
    budget: BudgetProposal
    estimate: Estimate


class ProjectSummary(BaseModel):
    id: str
    name: str
    city: str
    built_up_area_m2: int
    total_incl_vat_sar: int
    illustrative: bool


# ---- Request bodies (Phase 3) -----------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    input: ProjectInput


class ChangeCreate(BaseModel):
    month: int = Field(ge=0, le=60)
    type: Literal["change_request", "procurement_risk", "quote_variance", "risk_forecast"]
    title: str = Field(min_length=1, max_length=300)
    cost_sar: int = Field(default=0, ge=0)
    days: int = Field(default=0, ge=0)
    days_avoided: int = Field(default=0, ge=0)
    approved_by: Literal["engineer", "owner"] | None = None
    affects_task_id: str | None = None
    forecast: bool = False


class InspectionStatusUpdate(BaseModel):
    status: Literal["submitted", "rejected", "approved"]
    by: Literal["contractor", "engineer"]
    reason: str | None = None
    note: str | None = None
    evidence: list[str] = Field(default_factory=list)


class TaskProgressUpdate(BaseModel):
    percent_complete: float = Field(ge=0, le=100)


class TaskProgressResult(BaseModel):
    task_id: str
    percent_complete: float


# ---- AI-assisted features (Phase 5). Gemini output is validated and never shown as a
# number unless the engine computed or validated it. -------------------------------

Severity = Literal["blocker", "high", "medium"]
AISource = Literal["gemini", "mock", "template", "unavailable"]


class MissingInfo(BaseModel):
    item: str
    item_ar: str
    why_it_matters: str
    severity: Severity


class IntakeResult(BaseModel):
    source: AISource
    extracted: dict[str, object] = Field(
        default_factory=dict, description="Fields read from the text or PDF (not yet validated by the engine)"
    )
    missing_fields: list[str] = Field(default_factory=list, description="Inputs the engine needs but the text did not give")
    assumed_defaults: list[str] = Field(default_factory=list, description="Defaults used where the text was silent")
    missing_info: list[MissingInfo]
    project_input: ProjectInput | None = None
    estimate: Estimate | None = None
    note: str | None = None


class BOMRef(BaseModel):
    id: str
    item: str
    category: str
    amount_sar: int


class QuoteLineResult(BaseModel):
    description: str
    matched_bom_id: str | None = None
    quote_qty: float | None = None
    quote_rate_sar: float | None = None
    quote_amount_sar: int
    recomputed_amount_sar: int | None = Field(default=None, description="qty × rate, computed in Python")
    arithmetic_ok: bool = True
    bom_amount_sar: int | None = None
    variance_sar: int | None = None
    variance_pct: float | None = None


class QuoteComparison(BaseModel):
    source: AISource
    supplier: str | None = None
    lines: list[QuoteLineResult]
    quote_total_sar: int
    matched_bom_total_sar: int
    variance_sar: int
    missing_scope: list[BOMRef]
    added_scope: list[str]
    questions: list[str]
    note: str | None = None


class Notification(BaseModel):
    id: str
    kind: Literal["inspection_rejected", "inspection_approved", "change_approved"]
    text_ar: str
    source: AISource
    facts: dict[str, str | int | float]


class PaymentCreate(BaseModel):
    month: int = Field(ge=0, le=60)
    amount_sar: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=300)


class CommitmentCreate(BaseModel):
    amount_sar: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=300)
