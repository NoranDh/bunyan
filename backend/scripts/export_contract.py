"""Write contract/openapi.json and contract/mocks/*.json from the running app.

The mocks are real responses from the engine for Ahmed's villa (month 8), so the
frontend builds against the same numbers the backend returns.

Run from backend/:  python -m scripts.export_contract
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contract"
MOCKS = CONTRACT / "mocks"
AHMED = "ahmed-jeddah-villa"
AHMED_INPUT = {
    "built_up_area_m2": 600,
    "plot_area_m2": 500,
    "floors": 2,
    "has_roof_annex": True,
    "has_basement": False,
    "finish_level": "standard",
    "city": "Jeddah",
}


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    app = create_app(MemoryStore())
    _write(CONTRACT / "openapi.json", app.openapi())

    with TestClient(app) as client:
        def get(url: str) -> object:
            r = client.get(url)
            r.raise_for_status()
            return r.json()

        _write(MOCKS / "estimate.json", client.post("/api/estimate", json=AHMED_INPUT).json())
        _write(MOCKS / "projects.json", get("/api/projects"))
        _write(MOCKS / "project.json", get(f"/api/projects/{AHMED}"))
        _write(MOCKS / "schedule.json", get(f"/api/projects/{AHMED}/schedule"))
        _write(MOCKS / "dashboard.json", get(f"/api/projects/{AHMED}/dashboard"))
        _write(MOCKS / "permits.json", get(f"/api/projects/{AHMED}/permits"))
        _write(MOCKS / "notifications.json", get(f"/api/projects/{AHMED}/notifications"))

        demo = "فيلا دورين وملحق ٦٠٠ متر في جدة، أرض ٥٠٠ متر، تشطيب عادي، الميزانية ٢٫٧ مليون"
        r = client.post("/api/intake", data={"text": demo})
        r.raise_for_status()
        _write(MOCKS / "intake.json", r.json())

        r = client.post(f"/api/projects/{AHMED}/quotes/compare", data={"text": "electrical quote"})
        r.raise_for_status()
        _write(MOCKS / "quote_compare.json", r.json())


if __name__ == "__main__":
    main()
