"""A small fictional station for demonstrations: the planning source without TimeOffice.

It serves the interface of `TimeOfficeService` that the webapp uses, for every month: one station, twelve
employees, the reference shifts and a weekly minimum staffing. What the webapp enters (availability, wishes,
staffing) is kept in memory, so a restart brings back the starting state. A few entries of every month are
prefilled, so that a first schedule already shows vacation, training and wishes; they can be removed like any
other entry.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from threading import Lock

from app.domain import (
    POLICY,
    Availability,
    AvailabilityEntry,
    AvailabilityType,
    DayType,
    DemandConfiguration,
    DemandPattern,
    Employee,
    EmployeeCalendar,
    EmployeeSummary,
    InvalidSelection,
    MonthlyDemand,
    MonthlyWorkAccount,
    PatternRequirement,
    PlanningInspection,
    PlanningMonth,
    PlanningOptions,
    PlanningUnit,
    PlanningUnitMembership,
    PlanningUnitType,
    ScheduleContext,
    SchedulingDataset,
    Shift,
    ShiftOption,
    ShiftType,
    StaffLevel,
    Wish,
    WishEntry,
    WishType,
    WorkCredit,
    WorkSegment,
    build_inspection,
    build_scheduling_dataset,
    expand_pattern,
    month_calendar,
    public_holiday,
)

STATION_ID = 1
STATION = PlanningUnit(planning_unit_id=STATION_ID, display_name="Musterstation", type=PlanningUnitType.STATION)


def _shift(shift_id: int, code: str, kind: ShiftType, segments: tuple[tuple[int, int], ...], paid: int) -> Shift:
    return Shift(
        shift_id=shift_id,
        code=code,
        type=kind,
        segments=tuple(WorkSegment(start_minute=start, end_minute=end) for start, end in segments),
        net_work_minutes=paid,
    )


# The reference shifts of the practice partner: early 05:55-13:25, intermediate 08:30-14:15, late 13:15-21:00 and
# night 20:10-06:10, in local minutes after midnight of the start date, with their unpaid breaks.
EARLY = _shift(1113, "F", ShiftType.EARLY, ((355, 600), (630, 805)), 420)
INTERMEDIATE = _shift(1453, "Z", ShiftType.INTERMEDIATE, ((510, 855),), 345)
LATE = _shift(1605, "S", ShiftType.LATE, ((795, 960), (990, 1260)), 435)
NIGHT = _shift(1690, "N", ShiftType.NIGHT, ((1210, 1305), (1320, 1440), (1470, 1810)), 555)
SHIFTS = (EARLY, INTERMEDIATE, LATE, NIGHT)
SHIFT_OPTIONS = tuple(ShiftOption(shift_id=row.shift_id, code=row.code, type=row.type) for row in SHIFTS)

# Full-time work per Monday to Friday date that is no public holiday: 38.5 hours a week.
FULL_TIME_DAILY_MINUTES = 462


@dataclass(frozen=True, slots=True)
class TeamMember:
    employee_id: int
    name: str
    level: StaffLevel
    part_time: float
    """Share of full time."""


PROFESSIONAL, ASSISTANT, TRAINEE = StaffLevel.PROFESSIONAL, StaffLevel.ASSISTANT, StaffLevel.TRAINEE
TEAM = (
    TeamMember(1, "Becker Anna", PROFESSIONAL, 1.0),
    TeamMember(2, "Schmitz Jonas", PROFESSIONAL, 1.0),
    TeamMember(3, "Wagner Lena", PROFESSIONAL, 1.0),
    TeamMember(4, "Yilmaz Mehmet", PROFESSIONAL, 1.0),
    TeamMember(5, "Hoffmann Sophie", PROFESSIONAL, 1.0),
    TeamMember(6, "Krüger Tobias", PROFESSIONAL, 1.0),
    TeamMember(7, "Neumann Julia", PROFESSIONAL, 0.8),
    TeamMember(8, "Brandt Katharina", PROFESSIONAL, 0.85),
    TeamMember(9, "Lorenz Michael", PROFESSIONAL, 0.9),
    TeamMember(10, "Schulz Peter", ASSISTANT, 1.0),
    TeamMember(11, "Fischer Mia", TRAINEE, 1.0),
    TeamMember(12, "Weber Leon", TRAINEE, 1.0),
)
MEMBERS = {member.employee_id: member for member in TEAM}

WORKDAYS = (DayType.MONDAY, DayType.TUESDAY, DayType.WEDNESDAY, DayType.THURSDAY, DayType.FRIDAY)
DAYS_OFF = (DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY)
# The weekly minimum staffing every month starts with: (day types, shift, qualification, count). It asks for less
# than the team can work, so a month without entries has no gaps and room for wishes.
DEFAULT_PATTERN: tuple[tuple[tuple[DayType, ...], Shift, StaffLevel, int], ...] = (
    (WORKDAYS, EARLY, PROFESSIONAL, 3),
    (WORKDAYS, LATE, PROFESSIONAL, 2),
    (WORKDAYS, NIGHT, PROFESSIONAL, 1),
    (DAYS_OFF, EARLY, PROFESSIONAL, 2),
    (DAYS_OFF, LATE, PROFESSIONAL, 1),
    (DAYS_OFF, NIGHT, PROFESSIONAL, 1),
    (WORKDAYS, EARLY, ASSISTANT, 1),
    (WORKDAYS, EARLY, TRAINEE, 1),
    (WORKDAYS, LATE, TRAINEE, 1),
)

# Credited like an approved absence: the employee's daily target on Monday to Friday dates without a holiday.
CREDITED = {AvailabilityType.VACATION: "Urlaub", AvailabilityType.TRAINING: "Fortbildung"}


def _on_or_after(day: date, weekday: int) -> date:
    """The first date on or after `day` with this ISO weekday."""
    return day + timedelta(days=(weekday - day.isoweekday()) % 7)


def prefilled(month: PlanningMonth) -> tuple[list[Availability], list[Wish]]:
    """The entries every month starts with: a vacation week, a training day and two wishes."""
    start = month.start
    vacation = _on_or_after(start + timedelta(days=7), 1)
    availability = [
        *(
            Availability(
                employee_id=3, date=vacation + timedelta(days=offset), availability_type=AvailabilityType.VACATION
            )
            for offset in range(5)
        ),
        Availability(
            employee_id=6, date=_on_or_after(start + timedelta(days=14), 3), availability_type=AvailabilityType.TRAINING
        ),
    ]
    wishes = [
        Wish(employee_id=1, date=_on_or_after(start + timedelta(days=19), 5), type=WishType.FREE_DAY),
        Wish(
            employee_id=4,
            date=_on_or_after(start + timedelta(days=21), 2),
            type=WishType.PREFERRED_SHIFT,
            shift_id=LATE.shift_id,
        ),
    ]
    return availability, wishes


def default_demand(month: PlanningMonth) -> MonthlyDemand:
    """The month of the default weekly pattern; NRW public holidays take the holiday row."""
    cells = tuple(
        PatternRequirement(day_type=day_type, shift_id=shift.shift_id, staff_level=level, required_count=count)
        for day_types, shift, level, count in DEFAULT_PATTERN
        for day_type in day_types
    )
    return expand_pattern(DemandPattern(planning_unit_id=STATION_ID, planning_month=month, cells=cells))


def _month_of(day: date) -> PlanningMonth:
    return PlanningMonth(year=day.year, month=day.month)


class DemoPlanningSource:
    """The fictional station as a planning source; entries are kept per process and safe across threads.

    Methods raise `InvalidSelection` for anything but the station, its employees and the reference shifts.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._availability: dict[tuple[int, date], AvailabilityEntry] = {}
        self._wishes: dict[tuple[int, date], WishEntry] = {}
        self._demand: dict[tuple[int, int], MonthlyDemand] = {}
        self._prefilled: set[tuple[int, int]] = set()

    def get_planning_options(self, *, planning_month: PlanningMonth) -> PlanningOptions:
        return PlanningOptions(planning_month=planning_month, planning_units=(STATION,))

    def inspect_employees(
        self, *, planning_unit_ids: tuple[int, ...], planning_month: PlanningMonth
    ) -> PlanningInspection:
        _require_station(planning_unit_ids)
        availability = self._month_availability(planning_month)
        return build_inspection(
            planning_month=planning_month,
            selected_station_ids=(STATION_ID,),
            units=(STATION,),
            employees=tuple(
                Employee(employee_id=row.employee_id, display_name=row.name, staff_level=row.level) for row in TEAM
            ),
            memberships=tuple(
                PlanningUnitMembership(
                    planning_unit_id=STATION_ID,
                    employee_id=row.employee_id,
                    valid_from=date(2000, 1, 1),
                    staff_level=row.level,
                    is_home=True,
                    is_replacement=False,
                )
                for row in TEAM
            ),
            accounts=tuple(_account(row, planning_month, availability) for row in TEAM),
            availability=availability,
            shifts=SHIFT_OPTIONS,
        )

    def read_generation_input(
        self, *, planning_unit_ids: tuple[int, ...], planning_month: PlanningMonth
    ) -> SchedulingDataset:
        inspection = self.inspect_employees(planning_unit_ids=planning_unit_ids, planning_month=planning_month)
        after = planning_month.end + timedelta(days=1)
        with self._lock:
            self._prefill(_month_of(after))
            following = tuple(
                Availability(employee_id=employee_id, date=day, **entry.model_dump())
                for (employee_id, day), entry in sorted(self._availability.items())
                if day == after
            )
        # The preceding days are known and free, so the rules at the month start are checked, not left open.
        context = ScheduleContext(
            covered_from=planning_month.start - timedelta(days=POLICY.preceding_context_days),
            covered_until=planning_month.end,
            availability=following,
        )
        return build_scheduling_dataset(
            inspection=inspection,
            shifts=SHIFTS,
            demands=(self._monthly_demand(planning_month),),
            context=context,
            wishes=self._month_wishes(planning_month),
        )

    def list_employees(
        self, *, planning_unit_ids: tuple[int, ...], planning_month: PlanningMonth
    ) -> tuple[EmployeeSummary, ...]:
        _require_station(planning_unit_ids)
        return tuple(EmployeeSummary(employee_id=row.employee_id, display_name=row.name) for row in TEAM)

    def get_employee_calendar(self, *, employee_id: int, planning_month: PlanningMonth) -> EmployeeCalendar:
        _require_employee(employee_id)
        return EmployeeCalendar(
            employee_id=employee_id,
            planning_month=planning_month,
            absences=(),
            availability=tuple(
                row for row in self._month_availability(planning_month) if row.employee_id == employee_id
            ),
            wishes=tuple(row for row in self._month_wishes(planning_month) if row.employee_id == employee_id),
            calendar=month_calendar(planning_month),
            shifts=SHIFT_OPTIONS,
        )

    def set_availability(self, *, employee_id: int, day: date, entry: AvailabilityEntry | None) -> None:
        _require_employee(employee_id)
        _require_shifts(entry.shift_ids or () if entry else ())
        with self._lock:
            self._prefill(_month_of(day))
            if entry:
                self._availability[employee_id, day] = entry
            else:
                self._availability.pop((employee_id, day), None)

    def set_wish(self, *, employee_id: int, day: date, entry: WishEntry | None) -> None:
        _require_employee(employee_id)
        _require_shifts((entry.shift_id,) if entry and entry.shift_id else ())
        with self._lock:
            self._prefill(_month_of(day))
            if entry:
                self._wishes[employee_id, day] = entry
            else:
                self._wishes.pop((employee_id, day), None)

    def get_demand(self, *, planning_unit_id: int, planning_month: PlanningMonth) -> DemandConfiguration:
        _require_station((planning_unit_id,))
        return DemandConfiguration(
            planning_unit_id=planning_unit_id,
            planning_month=planning_month,
            demand=self._monthly_demand(planning_month),
            calendar=month_calendar(planning_month),
            shifts=SHIFT_OPTIONS,
        )

    def save_demand(self, demand: MonthlyDemand) -> None:
        _require_station((demand.planning_unit_id,))
        _require_shifts(tuple(cell.shift_id for cell in demand.cells))
        with self._lock:
            self._demand[demand.planning_month.year, demand.planning_month.month] = demand

    def preview_demand(self, pattern: DemandPattern) -> MonthlyDemand:
        _require_station((pattern.planning_unit_id,))
        _require_shifts(tuple(cell.shift_id for cell in pattern.cells))
        return expand_pattern(pattern)

    def _monthly_demand(self, month: PlanningMonth) -> MonthlyDemand:
        with self._lock:
            return self._demand.get((month.year, month.month)) or default_demand(month)

    def _month_availability(self, month: PlanningMonth) -> tuple[Availability, ...]:
        with self._lock:
            self._prefill(month)
            return tuple(
                Availability(employee_id=employee_id, date=day, **entry.model_dump())
                for (employee_id, day), entry in sorted(self._availability.items())
                if day in month
            )

    def _month_wishes(self, month: PlanningMonth) -> tuple[Wish, ...]:
        with self._lock:
            self._prefill(month)
            return tuple(
                Wish(employee_id=employee_id, date=day, **entry.model_dump())
                for (employee_id, day), entry in sorted(self._wishes.items())
                if day in month
            )

    def _prefill(self, month: PlanningMonth) -> None:
        """Add the month's starting entries the first time it is used; the caller holds the lock."""
        if (month.year, month.month) in self._prefilled:
            return
        self._prefilled.add((month.year, month.month))
        availability, wishes = prefilled(month)
        for row in availability:
            self._availability.setdefault(
                (row.employee_id, row.date), AvailabilityEntry(availability_type=row.availability_type)
            )
        for row in wishes:
            self._wishes.setdefault((row.employee_id, row.date), WishEntry(type=row.type, shift_id=row.shift_id))


def _account(member: TeamMember, month: PlanningMonth, availability: tuple[Availability, ...]) -> MonthlyWorkAccount:
    """The monthly target of the member's share of full time, with a credit for every vacation or training date."""
    bookable = [day for day in month.dates if day.isoweekday() <= 5 and public_holiday(day) is None]
    daily = round(FULL_TIME_DAILY_MINUTES * member.part_time)
    return MonthlyWorkAccount(
        employee_id=member.employee_id,
        target_minutes=daily * len(bookable),
        credit_details=tuple(
            WorkCredit(date=row.date, minutes=daily, kind="approved_absence", source=CREDITED[row.availability_type])
            for row in availability
            if row.employee_id == member.employee_id and row.availability_type in CREDITED and row.date in bookable
        ),
    )


def _require_station(planning_unit_ids: tuple[int, ...]) -> None:
    if set(planning_unit_ids) != {STATION_ID}:
        raise InvalidSelection("Only the demo station can be planned.")


def _require_employee(employee_id: int) -> None:
    if employee_id not in MEMBERS:
        raise InvalidSelection("Unknown employee of the demo station.")


def _require_shifts(shift_ids: tuple[int, ...]) -> None:
    if not set(shift_ids) <= {row.shift_id for row in SHIFTS}:
        raise InvalidSelection("Unknown shift.")
