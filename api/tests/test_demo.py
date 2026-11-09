"""The fictional demo station: a valid planning input for every month, with the webapp's entries kept in memory."""

from datetime import date

import pytest

from app.demo import EARLY, LATE, NIGHT, STATION_ID, TEAM, DemoPlanningSource, default_demand
from app.domain import (
    AvailabilityEntry,
    AvailabilityType,
    DemandCell,
    InvalidSelection,
    MonthlyDemand,
    PlanningMonth,
    StaffLevel,
    WishEntry,
    WishType,
    check_schedule,
    public_holiday,
)

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
