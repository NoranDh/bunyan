# Bunyan API contract (for the frontend)

Source of truth: `openapi.json` (generated from the backend). Example responses for every page are in `mocks/`. Both are regenerated with `cd backend && python -m scripts.export_contract`. If the API changes, the contract and mocks change in the same commit.

## Base URL
- Local: `http://localhost:8000` (backend runs with `make dev`). CORS allows `http://localhost:5173`.
- All routes are under `/api`.
- Local backend uses an in-memory store and mocked Gemini. Ahmed's villa (month 8) is loaded at startup.

## Conventions
- **Money is integer SAR**, excluding VAT, unless a field name says `incl_vat`. Format with thousands separators in the UI.
- **VAT is always shown separately** (`vat_sar`). Never fold it into a subtotal.
- Progress percentages are floats from 0 to 100. Round to a whole number in the UI (`actual_progress_pct` is 58.21 and shows as 58%).
- Schedule days count from day 0, the start of Month 0 (pre-construction). Month 14 handover is day 456.
- **Show the workings.** Every `bom_lines[]` item, `work_packages[]` item, `allowances[]` item and `totals_calculation` carries `calculation`: a list of `{label, formula, result, source}` rows. Render them as a table in the same order. The last row's `result` equals the number the line shows (for example `Amount` for a BOM line). `source` is optional. It names the data file or the assumption behind a step, and an assumption is marked `ASSUMPTION`.
- Every estimate carries `disclaimer`: "estimate — requires review by a licensed engineering office". Show it on every estimate and dashboard screen.
- Errors use FastAPI's shape: `{"detail": "..."}`. 422 means invalid input (for example, the footprint does not fit on the plot). 409 means an invalid state change. 404 means not found.

## Endpoints by page

| Page | Method and path | Notes |
|---|---|---|
| Intake, Estimate | `POST /api/estimate` | Stateless. Body `ProjectInput`, returns `Estimate`. Call it again whenever a rate changes. |
| Estimate | `POST /api/projects` | Save the estimate as a project. Body `{name, input}`. Returns `ProjectRecord`. The `budget` field starts as `proposed`. |
| Estimate | `POST /api/projects/{id}/budget/accept` | Owner accepts the proposed budget. Locks it. Returns `BudgetDecision` (`budget`, `estimate`). 409 if already accepted. |
| Estimate | `POST /api/projects/{id}/budget/reject` | Owner rejects it. Returns a cheaper option as a new proposal, with `budget.last_change` naming the lever pulled. 409 if already accepted or no cheaper option is left. |
| Plan | `GET /api/projects/{id}/schedule` | Tasks with baseline and forecast dates, critical path, hold points, handover slip. |
| Dashboard | `GET /api/projects/{id}/dashboard?status_day=274` | Everything on the dashboard, in one call. |
| Dashboard | `POST /api/projects/{id}/changes` | Log a change. An approved change with `days` shifts the schedule. |
| Dashboard | `POST /api/projects/{id}/inspections/{iid}/status` | `{status: submitted\|rejected\|approved, by, reason?, note?, evidence?}`. |
| Dashboard | `POST /api/projects/{id}/payments` | `{month, amount_sar, description}`. Money actually paid. Returns `Payment`. |
| Dashboard | `POST /api/projects/{id}/commitments` | `{amount_sar, description}`. Money agreed but not yet paid. Returns `Commitment`. |
| Dashboard | `PATCH /api/projects/{id}/tasks/{tid}` | `{percent_complete: 0–100}`. |
| Permits | `GET /api/projects/{id}/permits` | Checklist. Each item has `blocks_task_id`, so link it to the Plan task. `baseline_cost_sar` is the planning figure, and `uploaded` lists the documents already added. |
| Permits | `POST /api/projects/{id}/permits/{permit_id}/documents` | Multipart `file` (PDF, JPG or PNG, max 10 MB). Returns `ProjectDocument`. Only the metadata is stored for now. |
| Any | `GET /api/projects`, `GET /api/projects/{id}` | Project list and the full stored record. |
| Intake | `POST /api/intake` | Multipart: `text` and/or `spec_pdf` (PDF, max 10 MB). Returns `IntakeResult`: fields read, `missing_info` (checklist), and an `estimate` when the numbers are complete. |
| Intake | `POST /api/projects/{id}/quotes/compare` | Multipart: `text` and/or `quote_pdf`. Returns `QuoteComparison`: line variances, missing and added scope, and questions for the contractor. |
| Dashboard | `GET /api/projects/{id}/notifications` | Arabic notices (`text_ar`) for inspections and approved changes. `source` shows `gemini` or `template`. |
| Any | `GET /api/health` | Liveness check. |

## Mock files
| File | Matches |
|---|---|
| `mocks/estimate.json` | `POST /api/estimate` for Ahmed's inputs |
| `mocks/projects.json` | `GET /api/projects` |
| `mocks/project.json` | `GET /api/projects/ahmed-jeddah-villa` |
| `mocks/schedule.json` | `GET .../schedule` |
| `mocks/dashboard.json` | `GET .../dashboard` (month 8) |
| `mocks/permits.json` | `GET .../permits` |
| `mocks/notifications.json` | `GET .../notifications` |
| `mocks/intake.json` | `POST /api/intake` with the reference Arabic sentence |
| `mocks/quote_compare.json` | `POST .../quotes/compare` with a fixture electrical quote |

## Things to know
- **Budget is proposed, not typed in.** `ProjectInput` no longer has a budget. Use `estimate.proposed_budget_sar` (construction incl. VAT plus allowances) and let the owner accept or reject it. `budget_incl_vat_sar` survives only as the stated figure in the intake text (`extracted`).
- **Allowances** (`estimate.allowances`) are permits, soil survey, topographic survey, utilities, design fees and project management, at baseline midpoints. They are in the proposed budget but **not** in `total_incl_vat_sar`, and carry no VAT (ASSUMPTION).
- **Escalation.** `duration_months` above 12 escalates work that ends after month 12 at `annual_inflation_pct` (default 3%, ASSUMPTION). Each work package shows `escalation_years` and `escalation_sar`. Ahmed's villa is 14 months, so its WP5 is escalated.
- Dashboard progress: `steps_done`/`steps_total` count schedule tasks (not milestones or hold points). `work_packages_done` counts packages whose steps are all at 100%. `work_package_progress` gives each package's own numbers.
- The month-8 `planned_progress_pct` is **66.65**, computed from the baseline. The seed snapshot says 61. This is intentional for now (see the summary). Show the number as it comes.
- `actual_progress_pct` (58.21) uses illustrative per-task progress in the seed.
- The inspection `status` field is derived from its history. Never set it directly.
- `permits` items have `status: "to_verify"` until the construction experts confirm the steps.
- AI outputs carry a `source` field: `gemini` (live model), `mock` (fixture, local dev) or `template` (fixed Arabic text). Show a small badge when the source is not `gemini`.
- Intake flags 7 checklist items. Two are blockers (soil report, electrical load schedule), four are high (windows, structural, MEP drawings, building permit) and one is medium (finish schedule). Show them grouped by severity.
