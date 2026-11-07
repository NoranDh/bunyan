# Bunyan developer shortcuts. Local defaults: in-memory store, mock Gemini.
# Override the interpreter with: make dev PY=path/to/python
# On Windows without make, run the commands in README.md directly.

PY ?= backend/.venv/Scripts/python

.PHONY: install dev test contract deploy

install:
	$(PY) -m pip install -r backend/requirements.txt

dev:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

test:
	cd backend && ../$(PY) -m pytest

contract:
	cd backend && ../$(PY) -m scripts.export_contract

# Deployment. Untested: needs the GCP project, region and IAM roles first.
# Usage: make deploy PROJECT=my-project REGION=me-central2 SERVICE=bunyan
REGION ?= me-central2
SERVICE ?= bunyan
IMAGE = $(REGION)-docker.pkg.dev/$(PROJECT)/bunyan/$(SERVICE):latest

deploy:
	gcloud builds submit --tag $(IMAGE) .
	gcloud run deploy $(SERVICE) --project $(PROJECT) --region $(REGION) \
		--image $(IMAGE) \
		--min-instances 0 --max-instances 2 --cpu 1 --memory 512Mi \
		--set-env-vars GEMINI_MODE=vertex,GCP_REGION=$(REGION),FIRESTORE_DISABLED=0
