"""The fictional demo station: a valid planning input for every month, with the webapp's entries kept in memory."""

import io
from datetime import date

import pytest
from fastapi import UploadFile
from test_review import JANUARY_DUTIES, found, january

from app.api.history import HistoryProblem, HistoryRejected, put_history
from app.demo import EARLY, LATE, NIGHT, STATION_ID, TEAM, DemoPlanningSource, default_demand
from app.domain import (
    Assignment,
    AvailabilityEntry,
    AvailabilityType,
    DemandCell,
    InvalidSelection,
    MonthlyDemand,
    PlanningMonth,
    SchedulingDataset,
    StaffLevel,
    WishEntry,
    WishType,
    check_schedule,
    public_holiday,
)
from app.solver.bundle import InvalidBundle
from app.solver.review import Review

STATION = (STATION_ID,)


@pytest.mark.parametrize(
    "month", [PlanningMonth(year=year, month=month) for year in (2026, 2027) for month in range(1, 13)]
)
def test_every_month_is_a_valid_input_with_demand_targets_and_prefilled_entries(month: PlanningMonth) -> None:
    dataset = DemoPlanningSource().read_generation_input(planning_unit_ids=STATION, planning_month=month)

    assert len(dataset.employees) == len(TEAM) == 12
    assert {row.staff_level for row in dataset.employees} == {
        StaffLevel.PROFESSIONAL,
        StaffLevel.ASSISTANT,
        StaffLevel.TRAINEE,
    }
    assert dataset.demand_requirements == default_demand(month).requirements
    # A vacation week and a training day, credited on every such date that is no public holiday; two wishes.
    assert sorted(row.availability_type for row in dataset.availability) == [
        AvailabilityType.TRAINING,
        *[AvailabilityType.VACATION] * 5,
    ]
    credited = {
        (row.employee_id, credit.date) for row in dataset.monthly_work_accounts for credit in row.credit_details
    }
    assert credited == {(row.employee_id, row.date) for row in dataset.availability if public_holiday(row.date) is None}
    assert len(dataset.wishes) == 2
    # Every rule can be checked: the days before the month are known and free, so nothing blocking stays open.
    assert not any(row.blocking for row in check_schedule(dataset, ()).not_assessed)


def test_part_time_targets_follow_the_share_of_full_time() -> None:
    january = PlanningMonth(year=2027, month=1)
    dataset = DemoPlanningSource().read_generation_input(planning_unit_ids=STATION, planning_month=january)
    targets = {row.employee_id: row.target_minutes for row in dataset.monthly_work_accounts}

    # January 2027 has 20 Monday to Friday dates without a holiday (New Year is a Friday): 462 minutes each.
    assert targets[1] == 20 * 462
    assert targets[7] == 20 * round(462 * 0.8)


def test_entries_are_kept_removed_and_reach_the_next_month_start() -> None:
    source = DemoPlanningSource()
    january = PlanningMonth(year=2027, month=1)
    source.set_availability(
        employee_id=2, day=date(2027, 1, 12), entry=AvailabilityEntry(availability_type=AvailabilityType.FREE_DAY)
    )
    source.set_wish(
        employee_id=5, day=date(2027, 1, 13), entry=WishEntry(type=WishType.PREFERRED_SHIFT, shift_id=NIGHT.shift_id)
    )
    # Vacation on February 1 keeps a night of January 31 away.
    source.set_availability(
        employee_id=2, day=date(2027, 2, 1), entry=AvailabilityEntry(availability_type=AvailabilityType.VACATION)
    )

    calendar = source.get_employee_calendar(employee_id=2, planning_month=january)
    assert [(row.date.day, row.availability_type) for row in calendar.availability] == [(12, AvailabilityType.FREE_DAY)]
    dataset = source.read_generation_input(planning_unit_ids=STATION, planning_month=january)
    assert [(row.employee_id, row.date) for row in dataset.context.availability] == [(2, date(2027, 2, 1))]
    assert (5, date(2027, 1, 13)) in {(row.employee_id, row.date) for row in dataset.wishes}

    # A prefilled entry is removed like any other and stays removed.
    [vacation, *_] = [row for row in dataset.availability if row.availability_type == AvailabilityType.VACATION]
    source.set_availability(employee_id=vacation.employee_id, day=vacation.date, entry=None)
    source.set_availability(employee_id=2, day=date(2027, 1, 12), entry=None)
    again = source.read_generation_input(planning_unit_ids=STATION, planning_month=january)
    assert len(again.availability) == len(dataset.availability) - 2


def test_saved_demand_replaces_the_default_of_its_month_only() -> None:
    source = DemoPlanningSource()
    january, february = PlanningMonth(year=2027, month=1), PlanningMonth(year=2027, month=2)
    cell = DemandCell(
        date=date(2027, 1, 4), shift_id=LATE.shift_id, staff_level=StaffLevel.PROFESSIONAL, required_count=5
    )
    source.save_demand(MonthlyDemand(planning_unit_id=STATION_ID, planning_month=january, cells=(cell,)))

    saved = source.get_demand(planning_unit_id=STATION_ID, planning_month=january).demand
    assert saved is not None
    assert saved.cells == (cell,)
    assert source.get_demand(planning_unit_id=STATION_ID, planning_month=february).demand == default_demand(february)


def test_only_the_station_its_team_and_the_reference_shifts_are_accepted() -> None:
    source = DemoPlanningSource()
    january = PlanningMonth(year=2027, month=1)
    with pytest.raises(InvalidSelection):
        source.inspect_employees(planning_unit_ids=(99,), planning_month=january)
    with pytest.raises(InvalidSelection):
        source.get_employee_calendar(employee_id=99, planning_month=january)
    with pytest.raises(InvalidSelection):
        source.set_wish(employee_id=1, day=date(2027, 1, 5), entry=WishEntry(type=WishType.FREE_SHIFT, shift_id=1))
    assert source.get_planning_options(planning_month=january).planning_units[0].planning_unit_id == STATION_ID
    assert EARLY.net_work_minutes == 420


def plan_file(data: SchedulingDataset, duties: tuple[Assignment, ...]) -> bytes:
    review = Review()
    review.generated(data, found(data, duties))
    saved = review.plan_file()
    assert saved is not None
    return saved[1]


def load_history(content: bytes, year: int, month: int, source: DemoPlanningSource) -> None:
    put_history(plan=UploadFile(io.BytesIO(content), filename="plan.json"), year=year, month=month, source=source)


def test_history_takes_only_an_accepted_plan_of_the_month_before_and_of_the_station() -> None:
    source = DemoPlanningSource()
    # January 2026 at another station (101), accepted; and the same month without its duties, rejected.
    accepted, rejected = plan_file(january(), JANUARY_DUTIES), plan_file(january(), ())

    for content, month, problem in [
        (accepted, 3, HistoryProblem.WRONG_MONTH),
        (rejected, 2, HistoryProblem.NOT_ACCEPTED),
        (accepted, 2, HistoryProblem.FOREIGN),
    ]:
        with pytest.raises(HistoryRejected) as caught:
            load_history(content, 2026, month, source)
        assert caught.value.problem == problem
    with pytest.raises(InvalidBundle):
        load_history(b"{}", 2026, 2, source)
    assert source.get_history(planning_month=PlanningMonth(year=2026, month=2)) is None


def test_the_duties_of_the_month_before_become_the_history_of_the_month() -> None:
    source = DemoPlanningSource()
    february = PlanningMonth(year=2027, month=2)

    def night(employee_id: int, day: date) -> Assignment:
        return Assignment(
            employee_id=employee_id,
            date=day,
            planning_unit_id=STATION_ID,
            shift_id=NIGHT.shift_id,
            staff_level=StaffLevel.PROFESSIONAL,
        )

    duties = (night(1, date(2027, 1, 30)), night(1, date(2027, 1, 31)))
    summary = source.set_history(planning_month=february, assignments=duties, version=3)
    assert (summary.previous_month, summary.version, summary.duties) == (PlanningMonth(year=2027, month=1), 3, 2)
    dataset = source.read_generation_input(planning_unit_ids=STATION, planning_month=february)
    # The whole month before is known: its duties, and free where it has none.
    assert (dataset.context.covered_from, dataset.context.duties) == (date(2027, 1, 1), duties)

    # Only the station's team, in the month before.
    with pytest.raises(InvalidSelection):
        source.set_history(planning_month=february, assignments=(night(99, date(2027, 1, 31)),), version=1)
    with pytest.raises(InvalidSelection):
        source.set_history(planning_month=february, assignments=(night(1, date(2026, 12, 31)),), version=1)
    source.clear_history(planning_month=february)
    assert source.read_generation_input(planning_unit_ids=STATION, planning_month=february).context.duties == ()
