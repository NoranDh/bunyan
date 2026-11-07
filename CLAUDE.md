# Bunyan (بنيان) — hackathon MVP

Bunyan helps a first-time Saudi homeowner plan and control a villa build. The user enters villa specs (area, plot, floors, city, finish level, budget) and gets:
1. **Cost & material estimate** (the core): a bill of materials (BOM), work-package budget, 10% contingency and 15% VAT.
2. **Project plan**: a baseline Gantt schedule with critical path and engineer hold points.
3. **Permits checklist** (معاملات البناء) linked to the plan.
4. **Tracking dashboard**: planned vs actual progress, paid / committed / remaining, forecast final cost, contingency ledger, change log, inspections.

The reference scenario is "Ahmed's villa" (600 m² BUA, 500 m² plot, Jeddah, SAR 2,656,500 incl. VAT, 14 months). All of it is in `seed/`. It is illustrative, not real project data.

Deadline: submission Nov 11, 2026. Favor a working, demoable flow over breadth.

## Core design rule: the AI does not do the arithmetic
- **Quantities and cost come from a deterministic Python engine** (`backend/app/engine/`). The engine starts from per-m² quantity ratios (`seed/bom_reference_600m2.csv`, column `qty_per_m2_bua`) and adjusts them with modifiers (floors, finish level, basement yes/no, etc.). Rates are in SAR, excluding VAT.
- **Gemini handles language tasks only**: pulling structured specs out of free text or an uploaded spec PDF, flagging missing inputs (soil report, electrical load schedule, window specs…), comparing a contractor quote with the BOM line by line, and writing plain-Arabic explanations and notifications.
- Every number shown in the UI must be traceable to an engine function or a stored record. A Gemini output is never shown as a number unless the engine computed or validated it.
- The UI labels outputs "estimate — requires review by a licensed engineering office". No AI output counts as an engineering approval.

## Team split
- Noran owns `backend/`, `seed/`, `contract/` and deployment. A teammate owns `frontend/` — don't modify it unless asked.
- `contract/openapi.json` + `contract/mocks/*.json` is the interface between the two. Any API change updates both in the same commit.
- Local dev needs no GCP: FIRESTORE_DISABLED=1 and GEMINI_MODE=mock (or `apikey` with a Google AI Studio key). `vertex` is used only once the GCP project exists.

## Stack
- Backend: Python 3.12, FastAPI, Pydantic v2, `google-genai` SDK (Vertex AI mode), `google-cloud-firestore`, `google-cloud-storage`.
- Frontend: React + Vite + TypeScript + Tailwind, Recharts for charts, a simple custom SVG Gantt (no heavy Gantt lib). Arabic/English toggle with `dir="rtl"`.
- Deploy: one Cloud Run service (FastAPI serves the built frontend from `/static`). Container image in Artifact Registry.
- Data: **Firestore** (Native mode) for projects, tasks, change log, inspections and payments. **Cloud Storage** for uploads (drawings, test records, photos). BigQuery is out of MVP scope.
- Region: `me-central2` (Dammam) if every service needed is available there; otherwise `europe-west1` or `us-central1`. Keep it configurable.
- Gemini model ID comes from env var `GEMINI_MODEL`. Confirm the exact ID in the Vertex AI Model Garden and never hardcode it.

## Repo layout (target)
```
backend/app/
  main.py              # FastAPI app, serves /api and the static frontend
  models.py            # Pydantic schemas (ProjectInput, BOMLine, Task, ChangeEvent, Inspection, Snapshot)
  engine/estimate.py   # quantities + cost (deterministic)
  engine/schedule.py   # baseline schedule scaled from template + critical path (CPM)
  engine/control.py    # EVM-lite: progress, paid/committed/remaining, forecast, contingency
  ai/intake.py         # Gemini: free text / PDF -> ProjectInput + missing_info[]
  ai/quote_compare.py  # Gemini: quote lines vs BOM lines -> variances
  ai/explain.py        # Gemini: Arabic plain-language notifications
  store.py             # Firestore repository; in-memory fallback when FIRESTORE_DISABLED=1
  seed_loader.py       # loads seed/*.json|csv into the store
backend/tests/         # pytest; test_engine must reproduce the seed totals
frontend/src/pages/    # Intake, Estimate, Plan, Dashboard, Permits
seed/                  # reference data (do not edit by hand without updating tests)
```

## Seed data contract (tests must pass)
- Work packages total 2,100,000; plus contingency 210,000 = 2,310,000 excl. VAT; VAT 346,500; total 2,656,500.
- BOM: 36 lines, materials total 1,282,790 (about 61% of work packages).
- `estimate(600 m², standard finish, G+1+annex)` must reproduce the BOM totals within ±0.5%.
- Month 8: paid 1,150,000 + committed 640,000 + remaining 420,000 = forecast 2,210,000 = 2,100,000 + approved changes 34,000 + risk forecast 76,000. Contingency left: 100,000.
- Schedule: day 0 = start of Month 0 (pre-construction); status date = day 274 (end of M8); forecast handover = baseline + 7 days.

## Conventions
- Money is integer SAR in storage; format with thousands separators in the UI. VAT is always shown separately.
- Use type hints throughout and keep functions pure in `engine/`. No I/O in the engine.
- Gemini calls use structured output (response schema = Pydantic model) and temperature ≤ 0.2. Validate every response with Pydantic and, if validation fails, retry once and then fall back gracefully.
- Secrets come only from env. Cloud Run runs as its own service account with `roles/aiplatform.user`, `roles/datastore.user` and `roles/storage.objectAdmin` on the uploads bucket.
- Run `pytest` before each commit.
