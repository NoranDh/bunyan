"""Budget decisions. Pure functions, no I/O.

The estimator proposes a budget. If the owner rejects it, the next option is the same
project with one lever pulled, in this order: finish level down, basement removed, then
built-up area down 5%. Each step is cheaper than the last.
"""

from __future__ import annotations

from app.models import ProjectInput

MIN_BUA_M2 = 200
BUA_STEP = 0.05
_FINISH_DOWN = {"premium": "standard", "standard": "economy"}


def next_option(inp: ProjectInput) -> tuple[ProjectInput, str]:
    """Return a cheaper version of the project and a short description of what changed."""
    if inp.finish_level in _FINISH_DOWN:
        new_finish = _FINISH_DOWN[inp.finish_level]
        return inp.model_copy(update={"finish_level": new_finish}), f"Finish {inp.finish_level} → {new_finish}"

    if inp.has_basement:
        return inp.model_copy(update={"has_basement": False}), "Basement removed"

    new_bua = max(MIN_BUA_M2, round(inp.built_up_area_m2 * (1 - BUA_STEP)))
    if new_bua >= inp.built_up_area_m2:
        raise ValueError(f"No cheaper option left: built-up area is already at the {MIN_BUA_M2} m² minimum.")
    return (
        inp.model_copy(update={"built_up_area_m2": new_bua}),
        f"Built-up area {inp.built_up_area_m2} → {new_bua} m²",
    )
