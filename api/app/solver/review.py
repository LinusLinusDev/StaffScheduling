"""The schedule under review: the latest generated or imported bundle, kept in memory until the API restarts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain import (
    Assignment,
    CalendarDay,
    CheckStatus,
    PlanningMonth,
    PlanningUnit,
    PlanningUnitType,
    PublicationProblem,
    PublicationRejected,
    PublicationRequest,
    ScheduleMetrics,
    SchedulingBaseModel,
    SchedulingDataset,
    Shift,
)
from app.domain.schedule import ScheduleTables
from app.solver.bundle import (
    INPUT_FILE,
    RESULT_FILE,
    BundleProblem,
    FileName,
    InvalidBundle,
    ScheduleBundle,
    ScheduleInput,
    to_json,
)
from app.solver.models import Solution

MONTH_NAMES = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


class ReviewSource(StrEnum):
    GENERATION = "generation"
    IMPORT = "import"


class PlanFile(BaseModel):
    """A saved schedule in one file: the exact texts of its input.json and result.json, with month and version.

    A plain model, so the two texts keep every byte (the result names the SHA-256 of the input's exact bytes).
    """

    model_config = ConfigDict(extra="forbid")

    format: Literal["schichtplan-manager-dienstplan"] = "schichtplan-manager-dienstplan"
    format_version: Literal[1] = 1
    planning_month: PlanningMonth
    version: int = Field(ge=1)
    input: str
    """input.json as saved, character for character."""
    result: str
    """result.json as saved, character for character."""


class ScheduleReview(SchedulingBaseModel):
    """What the review page shows: the bundle's scope, solution and check, its readable tables and counts."""

    source: ReviewSource
    received_at: datetime
    planning_month: PlanningMonth
    planning_units: tuple[PlanningUnit, ...]
    shifts: tuple[Shift, ...]
    calendar: tuple[CalendarDay, ...]
    solution: Solution
    tables: ScheduleTables
    metrics: ScheduleMetrics
    version: int
    """Which schedule of its month this is: counted per month since the API started, or as saved in a loaded plan
    file; it names the saved file."""

    @property
    def station_ids(self) -> tuple[int, ...]:
        return tuple(unit.planning_unit_id for unit in self.planning_units if unit.type == PlanningUnitType.STATION)


class Review:
    """Hold one schedule for review and its downloadable files, and say whether a publication may take it.

    A generation that finds a schedule and a valid import each replace it; a run without a schedule
    and a rejected import leave it unchanged. Nothing is persisted, published or saved to a library.
    """

    def __init__(self) -> None:
        self._current: tuple[ScheduleBundle, ScheduleReview] | None = None
        # The highest version of each month so far, by (year, month); a new schedule of the month gets the next one.
        self._versions: dict[tuple[int, int], int] = {}

    def generated(self, dataset: SchedulingDataset, solution: Solution) -> None:
        """Review a generation's solution, if it found a schedule, as the next version of its month."""
        if solution.found:
            schedule_input = ScheduleInput.of(dataset)
            bundle = ScheduleBundle.solved(schedule_input, to_json(schedule_input), solution)
            self._show(bundle, ReviewSource.GENERATION)

    def imported(self, input_json: bytes, result_json: bytes, version: int | None = None) -> ScheduleReview:
        """Review an uploaded pair; raises InvalidBundle and keeps the current review if it is not a bundle.

        A pair from a plan file keeps the file's version; later schedules of its month count on from it.
        """
        return self._show(ScheduleBundle.read(input_json, result_json), ReviewSource.IMPORT, version)

    def imported_plan(self, content: bytes) -> ScheduleReview:
        """Review a saved plan file; raises InvalidBundle (`malformed`) for anything else."""
        try:
            plan = PlanFile.model_validate_json(content)
        except ValidationError as error:
            raise InvalidBundle(BundleProblem.MALFORMED, "Not a saved schedule file.") from error
        return self.imported(plan.input.encode(), plan.result.encode(), plan.version)

    def current(self) -> ScheduleReview | None:
        return self._current[1] if self._current else None

    def file(self, name: FileName) -> bytes | None:
        """One file of the schedule under review, or None without one."""
        return self._current[0].files[name] if self._current else None

    def plan_file(self) -> tuple[str, bytes] | None:
        """The schedule under review as one plan file, with its German file name, or None without one."""
        if self._current is None:
            return None
        bundle, review = self._current
        month = review.planning_month
        plan = PlanFile(
            planning_month=month,
            version=review.version,
            input=bundle.files[INPUT_FILE].decode(),
            result=bundle.files[RESULT_FILE].decode(),
        )
        name = f"Dienstplan {MONTH_NAMES[month.month - 1]} {month.year} - Version {review.version}.json"
        return name, to_json(plan)

    def publishable(self, request: PublicationRequest) -> tuple[Assignment, ...]:
        """The assignments of the schedule under review if the request names it and its check accepted it.

        Raises PublicationRejected (`changed`, `not_accepted`) otherwise; nothing is written here.
        """
        current = self._current
        if current is None:
            raise PublicationRejected(PublicationProblem.CHANGED, "There is no schedule under review.")
        bundle, review = current
        if (
            review.received_at != request.received_at
            or review.planning_month != request.planning_month
            or set(review.station_ids) != set(request.planning_unit_ids)
        ):
            raise PublicationRejected(PublicationProblem.CHANGED, "The schedule under review is another one.")
        if bundle.check.status != CheckStatus.ACCEPTED:
            raise PublicationRejected(PublicationProblem.NOT_ACCEPTED, "Only an accepted schedule is published.")
        return bundle.result.solution.assignments

    def _show(self, bundle: ScheduleBundle, source: ReviewSource, version: int | None = None) -> ScheduleReview:
        dataset = bundle.input.dataset
        key = (dataset.planning_month.year, dataset.planning_month.month)
        version = version if version is not None else self._versions.get(key, 0) + 1
        self._versions[key] = max(self._versions.get(key, 0), version)
        review = ScheduleReview(
            source=source,
            received_at=datetime.now(UTC),
            planning_month=dataset.planning_month,
            planning_units=dataset.planning_units,
            shifts=dataset.shifts,
            calendar=bundle.input.calendar,
            solution=bundle.result.solution,
            tables=bundle.tables,
            metrics=bundle.metrics,
            version=version,
        )
        self._current = (bundle, review)
        return review
