"""Project repository. Firestore in production, an in-memory dict when FIRESTORE_DISABLED=1.

Both implementations keep the whole ProjectRecord as one document. We considered
separate subcollections; one document is simpler and fits comfortably under Firestore's
1 MiB limit at this size, so we chose it on purpose.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.config import settings
from app.models import ProjectRecord


class ProjectStore(Protocol):
    def list_projects(self) -> list[ProjectRecord]: ...
    def get_project(self, project_id: str) -> ProjectRecord | None: ...
    def save_project(self, record: ProjectRecord) -> None: ...


class MemoryStore:
    """In-memory store for local development and tests. Data is lost on restart."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectRecord] = {}

    def list_projects(self) -> list[ProjectRecord]:
        return list(self._projects.values())

    def get_project(self, project_id: str) -> ProjectRecord | None:
        record = self._projects.get(project_id)
        # Return a copy so callers cannot change stored state by accident.
        return record.model_copy(deep=True) if record else None

    def save_project(self, record: ProjectRecord) -> None:
        self._projects[record.id] = record.model_copy(deep=True)


class FirestoreStore:
    """Firestore (Native mode). Written against the google-cloud-firestore API, not yet run
    against a live project (no GCP project exists yet)."""

    COLLECTION = "projects"

    def __init__(self, project: str | None) -> None:
        from google.cloud import firestore  # imported lazily so local runs need no GCP packages

        self._db = firestore.Client(project=project)

    def list_projects(self) -> list[ProjectRecord]:
        docs = self._db.collection(self.COLLECTION).stream()
        return [ProjectRecord.model_validate(d.to_dict()) for d in docs]

    def get_project(self, project_id: str) -> ProjectRecord | None:
        snap = self._db.collection(self.COLLECTION).document(project_id).get()
        return ProjectRecord.model_validate(snap.to_dict()) if snap.exists else None

    def save_project(self, record: ProjectRecord) -> None:
        self._db.collection(self.COLLECTION).document(record.id).set(record.model_dump(mode="json"))


@lru_cache(maxsize=1)
def get_store() -> ProjectStore:
    if settings.firestore_disabled:
        return MemoryStore()
    return FirestoreStore(project=settings.gcp_project)
