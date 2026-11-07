# Bunyan (بنيان)

Plan and control a villa build in Saudi Arabia. The estimate comes from a deterministic engine. Gemini handles language only. Every estimate is labelled "requires review by a licensed engineering office".

Start with [CLAUDE.md](CLAUDE.md) for the project rules.

## Run locally (no GCP needed)

Requires Python 3.12. `make` is optional on Windows; the commands are below.

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/api/health. Ahmed's villa at month 8 is loaded at startup.

Tests (run before each commit):

```powershell
cd backend
.venv\Scripts\python -m pytest
```

Regenerate the API contract and mocks after any API change:

```powershell
cd backend
.venv\Scripts\python -m scripts.export_contract
```

## Modes

| Variable | Values | Default | Use |
|---|---|---|---|
| `FIRESTORE_DISABLED` | `1` / `0` | `1` | `1` = in-memory store |
| `GEMINI_MODE` | `mock` / `apikey` / `vertex` | `mock` | `mock` = fixtures, no network |
| `GEMINI_API_KEY` | string | unset | Needed for `apikey` (Google AI Studio) |
| `GEMINI_MODEL` | model id | unset | Confirm the id in Vertex AI Model Garden; never hardcode it |
| `GCP_PROJECT`, `GCP_REGION` | | unset, `me-central2` | Needed for `vertex` and Firestore |

## Layout

- `backend/app/engine/`: estimate, schedule and cost control. Pure functions, no I/O.
- `backend/app/ai/`: Gemini features (intake, quote comparison, Arabic notices). Numbers come from the engine.
- `backend/app/api.py`: routes under `/api`.
- `seed/`: Ahmed's reference villa. Illustrative, not real project data.
- `contract/`: OpenAPI spec, mock responses and the frontend README.
- `frontend/`: owned by the frontend teammate.
