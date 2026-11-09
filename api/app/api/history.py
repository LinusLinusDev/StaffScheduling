"""The saved schedule of the month before, loaded as a month's history so the rules hold across the month boundary."""

from enum import StrEnum
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, UploadFile, status

from app.api.shared import Month, Year, get_planning_source
from app.demo import HistorySummary
from app.domain import Assignment, CheckStatus, InvalidSelection, PlanningMonth
from app.solver.review import read_plan

router = APIRouter()


class HistoryProblem(StrEnum):
    """Why a valid plan file cannot be a month's history.

    WRONG_MONTH: it is not the month before. NOT_ACCEPTED: its check found rule violations. FOREIGN: it belongs to
    another station, other employees or other shifts.
    """

    WRONG_MONTH = "wrong_month"
    NOT_ACCEPTED = "not_accepted"
    FOREIGN = "foreign"


class HistoryRejected(ValueError):
    def __init__(self, problem: HistoryProblem, message: str) -> None:
        super().__init__(message)
        self.problem = problem


class HistorySource(Protocol):
    def get_history(self, *, planning_month: PlanningMonth) -> HistorySummary | None: ...

    def set_history(
        self, *, planning_month: PlanningMonth, assignments: tuple[Assignment, ...], version: int
    ) -> HistorySummary: ...

    def clear_history(self, *, planning_month: PlanningMonth) -> None: ...


Source = Annotated[HistorySource, Depends(get_planning_source)]


@router.get("/history")
def get_history(year: Year, month: Month, source: Source) -> HistorySummary | None:
    """The month before loaded as this month's history, or null."""
    return source.get_history(planning_month=PlanningMonth(year=year, month=month))


@router.put(
    "/history",
    responses={422: {"description": "Not a valid plan file of the month before; `problem` names why."}},
)
def put_history(plan: UploadFile, year: Year, month: Month, source: Source) -> HistorySummary:
    """Load a saved plan file of the month before as this month's history.

    The file passes every check of a loaded plan (InvalidBundle otherwise), and it must be the month before, accepted
    by the schedule check and of the same station and team (HistoryRejected otherwise).
    """
    target = PlanningMonth(year=year, month=month)
    bundle, version = read_plan(plan.file.read())
    if bundle.input.dataset.planning_month != target.previous:
        raise HistoryRejected(HistoryProblem.WRONG_MONTH, "The plan is not of the month before.")
    if bundle.check.status != CheckStatus.ACCEPTED:
        raise HistoryRejected(HistoryProblem.NOT_ACCEPTED, "Only a schedule that keeps every rule is history.")
    try:
        return source.set_history(
            planning_month=target, assignments=bundle.result.solution.assignments, version=version
        )
    except InvalidSelection as error:
        raise HistoryRejected(HistoryProblem.FOREIGN, "The plan belongs to another station or team.") from error


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
def delete_history(year: Year, month: Month, source: Source) -> None:
    source.clear_history(planning_month=PlanningMonth(year=year, month=month))
