"""What a ward reads off a month's schedule: plain counts for the review, never an objective or a rule.

The schedule check judges the rules; these counts only describe the schedule, whichever solver made it. Trusted
duties before the month take part, so a late duty on the date before the month precedes an early one on its first.
"""

from collections import Counter
from collections.abc import Iterable
from datetime import date as Date
from datetime import timedelta

from app.domain.assignment import Assignment
from app.domain.core import SchedulingBaseModel
from app.domain.dataset import SchedulingDataset
from app.domain.rules import POLICY
from app.domain.shift import ShiftType

ONE_DAY = timedelta(days=1)


class ScheduleMetrics(SchedulingBaseModel):
    """Counts of the month's schedule for the review."""

    balance_tolerance_minutes: int
    """The band of the monthly balance rule: ± this many minutes."""
    largest_balance_minutes: int
    """The balance furthest from zero, with its sign; 0 without employees."""
    balances_outside_tolerance: int
    """Employees whose balance leaves the band."""
    late_to_early: int
    """Early duties of the month that start on the date after a late duty."""


def schedule_metrics(dataset: SchedulingDataset, assignments: Iterable[Assignment]) -> ScheduleMetrics:
    """The counts of the month's assignments, with the trusted context duties around them."""
    shifts = {row.shift_id: row for row in dataset.shifts}
    assignments = tuple(assignments)

    paid = Counter[int]()
    for row in assignments:
        paid[row.employee_id] += shifts[row.shift_id].net_work_minutes
    balances = [account.balance(paid[account.employee_id]) for account in dataset.monthly_work_accounts]
    tolerance = POLICY.balance_tolerance_minutes

    # Every known duty start by employee and date: the month's and the trusted ones around it.
    known: dict[tuple[int, Date], ShiftType] = {
        (row.employee_id, row.date): shifts[row.shift_id].type for row in (*dataset.context.duties, *assignments)
    }
    late_to_early = sum(
        kind == ShiftType.EARLY and known.get((employee_id, day - ONE_DAY)) == ShiftType.LATE
        for (employee_id, day), kind in known.items()
        if day in dataset.planning_month
    )

    return ScheduleMetrics(
        balance_tolerance_minutes=tolerance,
        largest_balance_minutes=max(balances, key=abs, default=0),
        balances_outside_tolerance=sum(abs(balance) > tolerance for balance in balances),
        late_to_early=late_to_early,
    )
