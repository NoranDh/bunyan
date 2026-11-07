"""Baseline schedule for a villa: scaling, dependency passes, critical path, slips.

Pure functions, no I/O. The template (seed/schedule_tasks.json) is passed in.

Method:
- Construction tasks are scaled by (BUA ÷ 600)^0.5 around the mobilisation day;
  pre-construction tasks are not scaled.
- Each dependency keeps the gap it has in the template (lag = successor start −
  predecessor end), so a change to one task shifts its successors by the same amount.
- Approved change events with `days` extend the affected task. Forecast items
  never move the schedule.
- A forward pass gives forecast early dates; a backward pass gives late dates.
  Tasks with zero float are the critical path.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence

from app.models import ChangeEvent, ScheduleResult, ScheduledTask, TaskTemplate

REFERENCE_BUA_M2 = 600
CONSTRUCTION_ORIGIN_DAY = 30  # T06 Mobilisation starts here; construction is measured from it
PRE_CONSTRUCTION_PHASE = "pre"

# Which work package each construction task spends against (ASSUMPTION — derived from
# the phases and the WP month ranges in seed/work_packages.json; confirm with engineers).
TASK_WORK_PACKAGE: dict[str, str] = {
    **{t: "WP1_site_foundations" for t in ("T06", "T07", "T08", "T09", "T10")},
    **{t: "WP2_structure" for t in ("T11", "T12", "T13", "T14", "T15")},
    **{t: "WP3_mep" for t in ("T16", "T17", "T18", "T19", "T20", "T21")},
    **{t: "WP4_finishes" for t in ("T22", "T23", "T24", "T25", "T26", "T27", "T28")},
    **{t: "WP5_external" for t in ("T29", "T30", "T31", "T32", "T33")},
}


def construction_scale(built_up_area_m2: int) -> float:
    return math.sqrt(built_up_area_m2 / REFERENCE_BUA_M2)


def _round_day(value: float) -> int:
    return int(math.floor(value + 0.5))


def _scale(tasks: Sequence[TaskTemplate], k: float) -> list[TaskTemplate]:
    scaled: list[TaskTemplate] = []
    for t in tasks:
        if t.phase == PRE_CONSTRUCTION_PHASE:
            scaled.append(t)
            continue
        start = CONSTRUCTION_ORIGIN_DAY + (t.start_day - CONSTRUCTION_ORIGIN_DAY) * k
        end = CONSTRUCTION_ORIGIN_DAY + (t.end_day - CONSTRUCTION_ORIGIN_DAY) * k
        scaled.append(t.model_copy(update={"start_day": _round_day(start), "end_day": _round_day(end)}))
    return scaled


def _topological_order(tasks: Sequence[TaskTemplate]) -> list[str]:
    ids = {t.id for t in tasks}
    for t in tasks:
        missing = [d for d in t.depends_on if d not in ids]
        if missing:
            raise ValueError(f"Task {t.id} depends on unknown task(s) {missing}")
    indegree = {t.id: len(t.depends_on) for t in tasks}
    successors: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for d in t.depends_on:
            successors[d].append(t.id)
    queue = deque(sorted(tid for tid, n in indegree.items() if n == 0))
    order: list[str] = []
    while queue:
        tid = queue.popleft()
        order.append(tid)
        for s in sorted(successors[tid]):
            indegree[s] -= 1
            if indegree[s] == 0:
                queue.append(s)
    if len(order) != len(tasks):
        raise ValueError("Schedule dependencies contain a cycle")
    return order


def approved_slip_days(changes: Sequence[ChangeEvent]) -> dict[str, int]:
    """Extra days per task from approved changes. Forecasts and avoided risks add nothing."""
    extra: dict[str, int] = {}
    for c in changes:
        if c.forecast or c.approved_by is None or c.days <= 0 or not c.affects_task_id:
            continue
        extra[c.affects_task_id] = extra.get(c.affects_task_id, 0) + c.days
    return extra


def build_schedule(
    template: Sequence[TaskTemplate],
    built_up_area_m2: int,
    changes: Sequence[ChangeEvent] = (),
) -> ScheduleResult:
    k = construction_scale(built_up_area_m2)
    base_list = _scale(template, k)
    base = {t.id: t for t in base_list}
    order = _topological_order(base_list)
    extra = approved_slip_days(changes)

    def duration(tid: str) -> int:
        t = base[tid]
        return (t.end_day - t.start_day) + extra.get(tid, 0)

    def lag(pred: str, succ: str) -> int:
        # Gap the template has between predecessor end and successor start (may be negative).
        return base[succ].start_day - base[pred].end_day

    successors: dict[str, list[str]] = {tid: [] for tid in base}
    for t in base_list:
        for d in t.depends_on:
            successors[d].append(t.id)

    # Forward pass: forecast early start / finish.
    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for tid in order:
        t = base[tid]
        candidates = [base[tid].start_day]
        candidates += [ef[p] + lag(p, tid) for p in t.depends_on]
        es[tid] = max(candidates)
        ef[tid] = es[tid] + duration(tid)

    project_finish = max(ef.values())

    # Backward pass: late start / finish, and float.
    lf: dict[str, int] = {}
    ls: dict[str, int] = {}
    for tid in reversed(order):
        succs = successors[tid]
        if succs:
            lf[tid] = min(ls[s] - lag(tid, s) for s in succs)
        else:
            lf[tid] = project_finish
        ls[tid] = lf[tid] - duration(tid)

    tasks: list[ScheduledTask] = []
    for t in base_list:
        flt = ls[t.id] - es[t.id]
        tasks.append(
            ScheduledTask(
                id=t.id,
                phase=t.phase,
                name=t.name,
                type=t.type,
                baseline_start_day=t.start_day,
                baseline_end_day=t.end_day,
                start_day=es[t.id],
                end_day=ef[t.id],
                duration_days=duration(t.id),
                float_days=flt,
                is_critical=flt <= 0,
                is_hold_point=t.type == "hold_point",
                depends_on=list(t.depends_on),
                work_package_id=TASK_WORK_PACKAGE.get(t.id),
            )
        )

    baseline_finish = max(t.end_day for t in base_list)
    critical = [t.id for t in sorted(tasks, key=lambda x: x.start_day) if t.is_critical]
    return ScheduleResult(
        tasks=tasks,
        critical_path=critical,
        baseline_handover_day=baseline_finish,
        forecast_handover_day=project_finish,
        slip_days=project_finish - baseline_finish,
        construction_scale=round(k, 4),
    )
