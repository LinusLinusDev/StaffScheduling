import math
from collections import Counter, defaultdict
from datetime import timedelta
from time import monotonic

import gurobipy as gp
from gurobipy import GRB

from app.domain import (
    POLICY,
    Assignment,
    AvailabilityType,
    Gap,
    SchedulingDataset,
    ShiftType,
    check_schedule,
)
from app.domain.rules import BLOCKING_AVAILABILITY
from app.settings import Settings
from app.solver.models import RunConfiguration, Solution, SolutionStatus, SolverUnavailable, StageReport

# Gurobi errors that mean the license cannot be used (no license, size limit, no network, rejected, session overage),
# not that the model is wrong.
LICENSE_ERRORS = frozenset({
    GRB.Error.NO_LICENSE,
    GRB.Error.SIZE_LIMIT_EXCEEDED,
    GRB.Error.NETWORK,
    GRB.Error.JOB_REJECTED,
    GRB.Error.CLOUD,
    GRB.Error.CSWORKER,
})
# How long past its time limit a run may take before the watchdog stops it, whichever pass is running.
WATCHDOG_GRACE_SECONDS = 5


class GurobiSolverService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._env: gp.Env | None = None

    def close(self) -> None:
        """Release the license session; the next solve opens a new one."""
        if self._env is not None:
            self._env.dispose()
            self._env = None

    def _environment(self) -> gp.Env:
        """The process's one Gurobi environment, opened on first use.

        A WLS license limits the sessions running at once, and a session's token outlives its environment by
        minutes. One environment for every solve keeps this process at a single session, however often it solves.
        """
        if self._env is None:
            # log only when asked (SOLVER_LOG_SEARCH_PROGRESS); this also silences the license banner
            self._env = gp.Env(params={"OutputFlag": 1 if self._settings.solver_log_search_progress else 0})
        return self._env

    def solve(self, dataset: SchedulingDataset, timeout: float | None = None) -> Solution:
        try:
            return self._solve(dataset, timeout)
        except gp.GurobiError as error:
            if error.errno not in LICENSE_ERRORS:
                raise
            # a broken session is not reused: the next solve opens a new one
            self.close()
            raise SolverUnavailable(f"Gurobi cannot use its license (error {error.errno}).") from error

    def _solve(self, dataset: SchedulingDataset, timeout: float | None) -> Solution:
        started = monotonic()
        settings = self._settings
        timeout = timeout if timeout is not None else settings.solver_max_time_seconds
        with gp.Model("schedule", env=self._environment()) as schedule:
            # Sets and Indices
            U = [unit.planning_unit_id for unit in dataset.planning_units]
            I = [employee.employee_id for employee in dataset.employees]
            S =[shift.shift_id for shift in dataset.shifts]
            # shifts by type, so rules hold for every shift of a type whatever its code
            S_early = [s.shift_id for s in dataset.shifts if s.type == ShiftType.EARLY]
            S_late = [s.shift_id for s in dataset.shifts if s.type == ShiftType.LATE]
            S_night = [s.shift_id for s in dataset.shifts if s.type == ShiftType.NIGHT]
            D = list(dataset.planning_month.dates)
            D_prev = [dataset.context.covered_from + timedelta(days=i) for i in range((dataset.planning_month.dates[0] - dataset.context.covered_from).days)]
            D_set = set(D)
            D_prev_set = set(D_prev)
            # a month that ends on a Saturday takes its Sunday along: the weekend's second day, a copy of the Saturday
            # (same shift or both free) on which every rule holds, so each Saturday duty can go on into the next
            # month. It counts for no account, demand or objective, and its duties are not part of the schedule.
            D_next = [D[-1] + timedelta(days=1)] if D[-1].weekday() == 5 else []
            # the days with duty variables: the month and that Sunday
            D_plan = D + D_next
            D_plan_set = set(D_plan)
            # (employee, station, day) -> qualification the duty is credited as, from the membership active that day
            level_at = {}
            for m in dataset.planning_unit_memberships:
                if m.planning_unit_id in dataset.station_ids:
                    for d in D_plan:
                        if m.active_on(d):
                            level_at.setdefault((m.employee_id, m.planning_unit_id, d), m.staff_level)
            # who covers which demand: (station, day, qualification) -> employees
            staff_for = defaultdict(list)
            for (i, u, d), l in level_at.items():
                staff_for[u, d, l].append(i)
            # Saturdays whose Sunday is planned (for "same shift Sat/Sun"), with the month's last day and its Sunday
            D_s = [date for date in D_plan[:-1] if date.weekday() == 5]
            if D_prev and D_prev[-1].weekday() == 5:
                D_s = D_prev[-1:] + D_s
            # every weekend with its Saturday or Sunday in the month or the known days before it, by its Saturday in
            # order (for "no two in a row"); so the weekend just before the month counts on any weekday of month start
            W = sorted({d if d.weekday() == 5 else d - timedelta(days=1) for d in D_prev + D if d.weekday() >= 5})
            # Parameters
            t = {}
            credits = {}
            for entry in dataset.monthly_work_accounts:
                t[entry.employee_id] = entry.target_minutes
                credits[entry.employee_id] = entry.credited_minutes
            h = {}
            for entry in dataset.shifts:
                h[entry.shift_id] = entry.net_work_minutes

            L_n = POLICY.night_recovery_minutes//1440
            K_s = POLICY.max_consecutive_work_days
            Dist_n = 7
            # days of a rotation window
            Rot_w = 28

            # blocking absences (vacation, free day, training, unavailable) and vacation days, also on the date after
            # the month (context availability), which a night of the month's last date reaches
            known_availability = (*dataset.availability, *dataset.context.availability)
            blocked = {(a.employee_id, a.date) for a in known_availability
                       if a.availability_type in BLOCKING_AVAILABILITY}
            vacation = {(a.employee_id, a.date) for a in known_availability
                        if a.availability_type == AvailabilityType.VACATION}
            # training days, also on the date after the month: the recovery days after nights are free of them too
            training_days = {(a.employee_id, a.date) for a in known_availability
                             if a.availability_type == AvailabilityType.TRAINING}

            past_shifts = {}
            for entry in dataset.context.duties:
                past_shifts[(entry.employee_id,entry.date)] = entry.shift_id

            # (employee, shift, day) that availability forbids
            not_allowed = set()
            # assign absences: available_only allows only its shifts, every other absence blocks the day; on the
            # Sunday taken along, the entries the next month has for it
            next_availability = (a for a in dataset.context.availability if a.date in D_next)
            for absence in (*dataset.availability, *next_availability):
                for s in S:
                    if absence.availability_type != "available_only" or s not in absence.shift_ids:
                        not_allowed.add((absence.employee_id, s, absence.date))
            # no night shift before a blocked day (a night touches the next day), and no late shift on the day before
            # vacation or training begins (training is work: a late duty ends at 21:00, leaving 11 hours only up to a
            # start at 08:00); on the last date the next day is the context's
            for i in I:
                for d in D:
                    next_day = d + timedelta(days=1)
                    if (i, next_day) in blocked:
                        for s in S_night:
                            not_allowed.add((i, s, d))
                    if ((i, next_day) in vacation and (i, d) not in vacation
                            or (i, next_day) in training_days and (i, d) not in training_days):
                        for s in S_late:
                            not_allowed.add((i, s, d))
            # wishes: every person has the same weight wish_budget for all their wishes of the month together, and each
            # of their n wishes is worth wish_budget / n. The more wishes a person enters, the less each one weighs, so
            # entering many does not buy more say in the schedule. 840 divides by 1 to 8; beyond that the weight is
            # rounded, so the stage keeps whole values. A transfer costs a third of a person's only wish.
            wish_budget = 840
            transfer_penalty = 280
            wish_count = Counter(entry.employee_id for entry in dataset.wishes)
            wish_reward = {i: max(1, round(wish_budget / n)) for i, n in wish_count.items()}

            # (employee, shift, day, unit) -> preference score; entries not listed are 0
            pref = defaultdict(int)
            # home unit of every employee on every day, from the home membership active that day
            home_of = {}
            for m in dataset.planning_unit_memberships:
                if m.is_home:
                    for d in D:
                        if m.active_on(d):
                            home_of[m.employee_id, d] = m.planning_unit_id
            # a duty at another station than the employee's home station costs transfer_penalty;
            # jumpers (home is a pool) are free to work anywhere
            for (i, u, d) in level_at:
                home = home_of.get((i, d))
                if home in dataset.station_ids and home != u:
                    for s in S:
                        pref[i, s, d, u] -= transfer_penalty
            for entry in dataset.wishes:
                reward = wish_reward[entry.employee_id]
                if entry.type == "free_day":
                    previous = entry.date - timedelta(days=1)
                    for u in U:
                        for s in S:
                            pref[entry.employee_id,s,entry.date,u] -= reward
                        # a night from the evening before reaches into the free day, as the schedule check counts it
                        for s in S_night:
                            pref[entry.employee_id,s,previous,u] -= reward
                elif entry.type == "free_shift":
                    for u in U:
                        pref[entry.employee_id,entry.shift_id,entry.date,u] -= reward
                elif entry.type == "preferred_day":
                    for u in U:
                        for s in S:
                            pref[entry.employee_id,s,entry.date,u] += reward
                elif entry.type == "preferred_shift":
                    for u in U:
                        pref[entry.employee_id,entry.shift_id,entry.date,u] += reward

            # minimum demand: (shift, day, station, qualification) -> required count, only rows with demand
            R_min = {(r.shift_id, r.date, r.planning_unit_id, r.staff_level): r.required_count for r in dataset.demand_requirements}
            # (station, shift, qualification) with minimum demand on at least one day of the month. A night or
            # intermediate shift without any demand for a qualification all month is not worked by it there (e.g. no
            # intermediate shift on the station, or no night shift for trainees); early and late shifts are open to
            # every qualification
            demanded = {(u, s, l) for (s, d, u, l) in R_min}
            always_open = set(S_early) | set(S_late)
            # Decision variables
            # assignment only for duties that can happen: a station membership active that day (7b: allowed
            # by availability), an early or late shift, or a night or intermediate shift that the station demands of
            # the qualification the duty counts as; duties before the month are constants from past_shifts, not
            # variables
            assignment = schedule.addVars(
                [(i, s, d, u) for (i, u, d), l in level_at.items() for s in S
                 if (i, s, d) not in not_allowed and (s in always_open or (u, s, l) in demanded)],
                vtype=GRB.BINARY, name="assignment")
            gap = schedule.addVars(R_min.keys(), lb=0.0, vtype=GRB.CONTINUOUS, name="gap")
            n_beg = schedule.addVars(I, D_prev[-1:] + D_plan, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_beg")
            # days on which the end of a night block matters: recovery and distance to the next block
            D_end = D_prev[-max(Dist_n, L_n + 1):] + D_plan[:-1]
            n_end = schedule.addVars(I, D_end, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_end")
            hour = schedule.addVars(I, vtype=GRB.CONTINUOUS, lb=-GRB.INFINITY, name="hour")
            # minutes by which a balance leaves the band of ±POLICY.balance_tolerance_minutes
            over = schedule.addVars(I, vtype=GRB.CONTINUOUS, lb=0.0, name="over")
            # cons counts a duty that continues the kind of shift of the day before. Early and intermediate are one
            # kind, so an intermediate duty within a run of early ones does not break the block; every other type is
            # a kind of its own
            block_kinds = defaultdict(list)
            for shift in dataset.shifts:
                kind = ShiftType.EARLY if shift.type == ShiftType.INTERMEDIATE else shift.type
                block_kinds[kind.value].append(shift.shift_id)
            cons_s = schedule.addVars(I, list(block_kinds), D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="cons_s")
            L_to_E = schedule.addVars(I,D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="L_to_E")
            # shift balance: minimum demand per (station, shift, day) over all qualifications, and per (station, day)
            required_usd = defaultdict(int)
            for (s, d, u, l), required in R_min.items():
                required_usd[u, s, d] += required
            required_ud = defaultdict(int)
            for (u, s, d), required in required_usd.items():
                required_ud[u, d] += required
            # dev[u, s, d]: how far the staff of shift s deviates from its share of the day's staff at station u
            balance_keys = [(u, s, d) for (u, d) in required_ud for s in S]
            dev = schedule.addVars(balance_keys, lb=0.0, vtype=GRB.CONTINUOUS, name="shift_dev")
            # gap spread: gap_sq[u, d] >= (gaps of station u on day d)^2, so spreading gaps over days costs less
            gap_sq = schedule.addVars(required_ud.keys(), lb=0.0, vtype=GRB.CONTINUOUS, name="gap_sq")
            # staffing spread: day_dev[u, d] >= |staff of the day - its share of the month's staff at station u|,
            # for every day of the month at a station with demand (a day without demand has share 0)
            required_u = defaultdict(int)
            for (u, d), required in required_ud.items():
                required_u[u] += required
            day_keys = [(u, d) for u in required_u for d in D]
            day_dev = schedule.addVars(day_keys, lb=0.0, vtype=GRB.CONTINUOUS, name="day_dev")

            # Expressions, built once and looked up below instead of assignment.sum(...) with wildcards.
            # x[i, s, d]: employee i works shift s on day d (sum over stations); before the month 0 or 1
            by_duty = defaultdict(list)
            for (i, s, d, u), var in assignment.items():
                by_duty[i, s, d].append(var)
            x = {key: gp.quicksum(variables) for key, variables in by_duty.items()}
            for (i, d), s in past_shifts.items():
                if d in D_prev_set:
                    x[i, s, d] = gp.LinExpr(1)

            def total(shifts, i, d):
                return gp.quicksum(x[i, s, d] for s in shifts if (i, s, d) in x)

            days = D_prev + D_plan
            # work: any duty; night, early, late: a duty of that type
            work = {(i, d): total(S, i, d) for i in I for d in days}
            night = {(i, d): total(S_night, i, d) for i in I for d in days}
            early = {(i, d): total(S_early, i, d) for i in I for d in days}
            late = {(i, d): total(S_late, i, d) for i in I for d in days}

            def at(table, i, d):
                """The expression of employee i on day d; 0 outside the month and its known past."""
                return table[i, d] if (i, d) in table else gp.LinExpr()

            def shift_on(i, s, d):
                return x[i, s, d] if (i, s, d) in x else gp.LinExpr()

            # rotation: in every window of Rot_w days that ends in the month and starts on a known day (the month and
            # the days before it, the whole month before when it is loaded), every person works each shift type
            # (early, late, night; not intermediate, which is a short extra rather than a rotation shift) at least once
            # if possible. rotation[i, w, k] can be 1 only if i works a shift of type k in the window starting on w.
            # Only types i can work this month count, those with a duty variable: a trainee is not pushed into nights
            # nobody asks of trainees, and "only certain shifts" leaves the other types out. A type worked already on the window's days before the month needs nothing more.
            shift_types = defaultdict(list)
            for shift in dataset.shifts:
                if shift.type != ShiftType.INTERMEDIATE:
                    shift_types[shift.type].append(shift.shift_id)
            window_starts = [w for w in D_prev + D
                             if D[0] <= w + timedelta(days=Rot_w - 1) <= D[-1]]
            worked_type = {}
            for i in I:
                for w in window_starts:
                    window = [w + timedelta(days=j) for j in range(Rot_w)]
                    for k, shifts in shift_types.items():
                        if any(past_shifts.get((i, d)) in shifts for d in window if d in D_prev_set):
                            continue
                        window_duties = gp.quicksum(x[i, s, d] for s in shifts for d in window
                                                    if d in D_set and (i, s, d) in x)
                        if window_duties.size() > 0:
                            worked_type[i, w, k] = window_duties
            rotation = schedule.addVars(list(worked_type), vtype=GRB.BINARY, name="rotation")
            # loop over the keys only: addConstrs names each constraint after the loop variables
            schedule.addConstrs((rotation[i, w, k] <= worked_type[i, w, k] for i, w, k in worked_type), name="rotation")

            # weekend_start: the weekend across the month start, when the month before is loaded (its duties known, not
            # just days assumed free). The first Sunday should keep the Saturday's shift, and after a free Saturday stay
            # free, as within the month; every person for whom it does not counts 1
            weekend_split = gp.LinExpr()
            if dataset.context.duties and D_prev and D_prev[-1].weekday() == 5:
                saturday, sunday = D_prev[-1], D[0]
                for i in I:
                    if (i, saturday) in past_shifts:
                        weekend_split += 1 - shift_on(i, past_shifts[i, saturday], sunday)
                    else:
                        weekend_split += at(work, i, sunday)

            # saturdays: the worked Saturdays of the month spread evenly over the people who share a qualification.
            # sat_sq[i] >= (Saturdays of i)^2, by the same secants as gap_sq; with the Saturdays of a qualification
            # given, the sum of squares is least when the counts differ by at most one (2+2+3 rather than 1+3+3).
            # Each qualification covers its own demand, so the sum over everybody evens out each one by itself.
            month_saturdays = [d for d in D if d.weekday() == 5]
            saturdays_of = {i: gp.quicksum(at(work, i, d) for d in month_saturdays) for i in I}
            sat_sq = schedule.addVars(I, lb=0.0, vtype=GRB.CONTINUOUS, name="sat_sq")
            for i in I:
                for k in range(len(month_saturdays)):
                    schedule.addConstr(sat_sq[i] >= (2 * k + 1) * saturdays_of[i] - k * (k + 1), name=f"sat_sq[{i},{k}]")

            # Objective functions
            # (name, expression, maximize), highest priority first
            objectives = [
                # the balance band comes first, before the gaps: whenever every balance can lie within it, every
                # schedule keeps it, like a hard rule; when it cannot (e.g. free days for half the month), the
                # month still gets a schedule with the least excess instead of none
                ("balance_violation", over.sum(), False),
                # right after it, the same for the weekend across the month start: kept whenever possible, while a
                # vacation entered on the 1st later on, or a fourth night, splits it instead of leaving no schedule
                ("weekend_start", weekend_split, False),
                ("gaps", gap.sum(), False),
                # relative to the day's demand: a gap weighs more on a day with less demand
                ("gap_spread", gp.quicksum(gap_sq[u, d] / required for (u, d), required in required_ud.items()), False),
                ("staffing_spread", day_dev.sum(), False),
                # worked Saturdays spread evenly within each qualification
                ("saturdays", sat_sq.sum(), False),
                ("wishes",gp.quicksum(score * assignment[key] for key, score in pref.items() if score and key in assignment), True),
                # rotation: every shift type a person works in a 28-day window counts once per window
                ("rotation", rotation.sum(), True),
                ("shift_balance", dev.sum(), False),
                ("Min_L_to_E",L_to_E.sum(), False),
                ("cons", cons_s.sum(), True),
            ]
            # total slack of a stage above its optimum: half of it may be left when the stage stops early
            # (MIPGapAbs), the other half the following stages may worsen it by (abstol); others stay fixed
            stage_slack = {
                # about 5 gaps moved from a day with one gap to another one (1+1 -> 2+0, 0.4 each at demand 5)
                "gap_spread": 2,
                # about one person more or less than the even share on one day per station and week
                "staffing_spread": len(required_u) * len(D) / 7,
                # about one person per station and week in another shift than its share; moving one person from
                # one shift to another changes the deviation of both, so 2 per move
                "shift_balance": 2 * len(required_u) * len(D) / 7,
            }
            abstol = {name: slack / 2 for name, slack in stage_slack.items()}
            # every other stage has whole values (minutes, gaps, weekends, squares, wish scores, counts), so it stays at
            # its optimum with any tolerance below 1. Half a unit absorbs the rounding of a sum over many binaries: with
            # 1e-6, an optimum reported as 294.000004 bars every whole schedule worth 294, and the later stages either
            # find nothing else or nothing at all ("Root relaxation: infeasible") and keep the schedule they get.
            for n, (name, expr, maximize) in enumerate(objectives):
                schedule.setObjectiveN(-expr if maximize else expr, index=n, priority=len(objectives) - 1 - n,
                                       abstol=abstol.get(name, 0.5), name=name)
            schedule.ModelSense = GRB.MINIMIZE
            # Constraints
            # one shift per day
            schedule.addConstrs((work[i, d] <= 1 for i in I for d in D_plan), name="one_shift")
            # min demand, credited with the membership's qualification
            schedule.addConstrs((gp.quicksum(assignment[i, s, d, u] for i in staff_for[u, d, l] if (i, s, d, u) in assignment) + gap[s, d, u, l] >= required
                                 for (s, d, u, l), required in R_min.items()), name="demand")
            # define workhours: the month's duties only, the Sunday taken along belongs to the next month's account
            minutes = defaultdict(list)
            for (i, s, d, u), var in assignment.items():
                if d in D_set:
                    minutes[i].append(h[s] * var)
            schedule.addConstrs((gp.quicksum(minutes[i]) + credits[i] - hour[i] == t[i] for i in I), name="workhours")
            # balance band: over[i] is the excess beyond ±tolerance, kept at 0 by the first stage whenever possible
            tolerance = POLICY.balance_tolerance_minutes
            schedule.addConstrs((over[i] >= hour[i] - tolerance for i in I), name="over_up")
            schedule.addConstrs((over[i] >= -hour[i] - tolerance for i in I), name="over_down")
            # gap spread: gap_sq[u, d] >= G^2 for the gaps G of station u on day d. Gaps are whole numbers from 0 to
            # the day's demand R, and the lines through (k, k^2) and (k+1, (k+1)^2) for k = 0 .. R-1 meet G^2 there.
            gaps_of_day = defaultdict(list)
            for (s, d, u, l), var in gap.items():
                gaps_of_day[u, d].append(var)
            for (u, d), required in required_ud.items():
                day_gaps = gp.quicksum(gaps_of_day[u, d])
                for k in range(required):
                    schedule.addConstr(gap_sq[u, d] >= (2 * k + 1) * day_gaps - k * (k + 1), name=f"gap_sq[{u},{d},{k}]")
            # shift balance: a station's staff of a day spread over its shifts in proportion to their minimum demand,
            # dev >= |staff of the shift - share * staff of the day|
            staffed = defaultdict(list)
            for (i, s, d, u), var in assignment.items():
                staffed[u, s, d].append(var)
            for (u, s, d) in balance_keys:
                share = required_usd[u, s, d] / required_ud[u, d]
                day_total = gp.quicksum(var for s2 in S for var in staffed[u, s2, d])
                deviation = gp.quicksum(staffed[u, s, d]) - share * day_total
                schedule.addConstr(dev[u, s, d] >= deviation, name=f"shift_dev_up[{u},{s},{d}]")
                schedule.addConstr(dev[u, s, d] >= -deviation, name=f"shift_dev_down[{u},{s},{d}]")
            # staffing spread: a station's staff of the month spread over its days in proportion to their minimum
            # demand, so over- and understaffing fall on all days alike; day_dev >= |staff of the day - share * month|
            staff_of_day = {(u, d): gp.quicksum(var for s in S for var in staffed[u, s, d]) for (u, d) in day_keys}
            staff_of_month = {u: gp.quicksum(staff_of_day[u, d] for d in D) for u in required_u}
            for (u, d) in day_keys:
                share = required_ud.get((u, d), 0) / required_u[u]
                deviation = staff_of_day[u, d] - share * staff_of_month[u]
                schedule.addConstr(day_dev[u, d] >= deviation, name=f"day_dev_up[{u},{d}]")
                schedule.addConstr(day_dev[u, d] >= -deviation, name=f"day_dev_down[{u},{d}]")
            # define cons_s: a duty of kind k on day d and on the day before
            one_day = timedelta(days=1)
            # (loop over the keys only: addConstrs names each constraint after the loop variables)
            schedule.addConstrs((cons_s[i, k, d] <= total(block_kinds[k], i, d)
                                 for i in I for k in block_kinds for d in D), name="cons_today")
            schedule.addConstrs((cons_s[i, k, d] <= total(block_kinds[k], i, d - one_day)
                                 for i in I for k in block_kinds for d in D), name="cons_before")
            # max consecutive workdays
            for i in I:
                for d in D_prev[-K_s:] + D_plan[:-K_s]:
                    window = [d + timedelta(days=k) for k in range(K_s + 1)]
                    fixed = sum((i, day) in training_days for day in window)
                    worked = gp.quicksum(at(work, i, day) for day in window) + fixed
                    # days fixed already (worked before the month, training) may reach the limit alone: then no more
                    schedule.addConstr(worked <= max(K_s, worked.getConstant()))
            # define L_to_E
            schedule.addConstrs(L_to_E[i, d] >= at(late, i, d - one_day) + early[i, d] - 1 for i in I for d in D);
            # max consecutive nights
            for i in I:
                for d in D_prev[-POLICY.max_consecutive_nights:]+ D_plan[:-POLICY.max_consecutive_nights]:
                    window = [d + timedelta(days=k) for k in range(POLICY.max_consecutive_nights + 1)]
                    nights = gp.quicksum(at(night, i, day) for day in window)
                    # nights before the month may reach the limit alone: then no more
                    schedule.addConstr(nights <= max(POLICY.max_consecutive_nights, nights.getConstant()))
            # define beginning and end of nightshiftblock; lower bounds suffice, because n_beg and n_end
            # appear only in <= 1 constraints with positive sign and in no objective
            schedule.addConstrs((n_beg[i,d] >= night[i, d] - at(night, i, d - one_day) for i in I for d in D_prev[-1:] + D_plan));
            schedule.addConstrs((n_end[i,d] >= night[i, d] - at(night, i, d + one_day) for i in I for d in D_end));
            # no nightshift block starts and ends on the same day; a single night on the last day before the month is
            # not forced to go on (a vacation or the night limit may forbid a second night on the 1st)
            schedule.addConstrs(n_beg[i,d]+n_end[i,d]<=1 for i in I for d in D_plan[:-1]);
            # ensure recovery days after nightshift block (only planned days: the past is never constrained against
            # itself)
            for i in I:
                for d in D_prev[-(L_n+1):] + D_plan[:-1]:
                    for j in range(1,L_n+1):
                        if d + timedelta(days=j) in D_plan_set:
                            schedule.addConstr(n_end[i, d] + work[i, d + timedelta(days=j)] <= 1)
                    # no early shift after recovery days
                    if d + timedelta(days=L_n+1) in D_plan_set:
                        schedule.addConstr(n_end[i, d] + early[i, d + timedelta(days=L_n+1)] <= 1)
            # the recovery days are free of training too: no night block of the month ends within L_n days before a
            # training day (with training on the next day a night is ruled out already, as before any blocked day).
            # Blocks that ended before the month stay as they were.
            for i in I:
                for d in D_plan[:-1]:
                    if any((i, d + timedelta(days=j)) in training_days for j in range(1, L_n + 1)):
                        schedule.addConstr(n_end[i, d] <= 0, name=f"recovery_training[{i},{d}]")
            # same shifts on weekends, also on the month's last Saturday and the Sunday taken along. At the month start
            # the known Saturday before only bounds the first Sunday here: after a worked Saturday the Sunday keeps its
            # shift or stays free, never forced (a vacation on the 1st or a fourth night would make the month
            # infeasible); after a free Saturday the Sunday is open. With the month before loaded, the goal
            # weekend_start asks for the full rule as well.
            for d in D_s:
                for i in I:
                    if d in D_prev_set:
                        if (i, d) in past_shifts:
                            for s in S:
                                sunday = shift_on(i, s, d + one_day)
                                if s != past_shifts[i, d] and sunday.size() > 0:
                                    schedule.addConstr(sunday <= 0)
                        continue
                    for s in S:
                        schedule.addConstr(shift_on(i, s, d) == shift_on(i, s, d + one_day))
            # min days between nightshift block (only blocks starting in the month)
            for i in I:
                for d in D_prev[-Dist_n:] + D_plan:
                    forbidden_starts = [d+timedelta(days=j) for j in range(1, Dist_n + 1) if d+timedelta(days=j) in D_plan_set]
                    if forbidden_starts:
                        schedule.addConstr(n_end[i, d] + gp.quicksum(n_beg[i, day] for day in forbidden_starts) <= 1)
            # not two weekends in a row. A weekend is worked with a duty on its Saturday or Sunday; a Friday night
            # alone leaves it free. In the month both days carry the same shift (D_s), so the Saturday tells; a weekend
            # before the month is known from the past duties, so a constant.
            def weekend(i, saturday):
                sunday = saturday + one_day
                if sunday in D_prev_set:
                    return gp.LinExpr(int((i, saturday) in past_shifts or (i, sunday) in past_shifts))
                if saturday in D_prev_set:
                    # the weekend across the month start: a worked Saturday before it, or a duty on Sunday the 1st
                    return gp.LinExpr(1) if (i, saturday) in past_shifts else at(work, i, sunday)
                if saturday in D_set:
                    return at(work, i, saturday)
                # the Saturday lies before the known days: a month starting on a Sunday without past duties
                return at(work, i, sunday)

            # only pairs whose later weekend touches the month: the past is never constrained against itself
            for earlier, later in zip(W, W[1:], strict=False):
                if later in D_set or later + one_day in D_set:
                    for i in I:
                        pair = weekend(i, earlier) + weekend(i, later)
                        # two weekends both fixed by the past (a worked Saturday before the month) stay as they were
                        if pair.size() > 0:
                            schedule.addConstr(pair <= 1, name=f"two_weekends[{later},{i}]")
            # solve
            schedule.Params.TimeLimit = timeout
            schedule.Params.MIPGap = 0.03
            if settings.solver_num_search_workers is not None:
                schedule.Params.Threads = settings.solver_num_search_workers
            if settings.solver_random_seed is not None:
                schedule.Params.Seed = settings.solver_random_seed
            # time limit of single stages as a share of the total time; the other stages run until the total limit
            # shift_balance: its bound stays at 0 (shares are met exactly only with fractional staff), so it can never
            # prove a whole-staff value and would run to the total limit; its good value is found early
            # rotation: its bound counts every type a person could work, also one that blocked days rule out, so it
            # may never prove its value either; the share keeps it from taking the time of the stages after it
            # saturdays: solved exactly below; the share only guards against a bound that the rules keep out of reach
            # wishes: with many wishes (or a flood of them) its gap closes slowly and it would take all the time left,
            # so rotation, shift balance, late-to-early and cons would never run
            stage_time_share = {"shift_balance": 0.1, "staffing_spread": 0.15, "rotation": 0.1, "saturdays": 0.1,
                                "wishes": 0.15}  # e.g. {"gap_spread": 0.15, "Min_L_to_E": 0.2}
            for n, (name, _, _) in enumerate(objectives):
                if name in stage_time_share:
                    # pass n is objective n, since the priorities fall with the index
                    schedule.getMultiobjEnv(n).setParam("TimeLimit", stage_time_share[name] * timeout)
            # a stage with slack stops as soon as its value is proven within the other half of its slack
            for n, (name, _, _) in enumerate(objectives):
                if name in stage_slack:
                    schedule.getMultiobjEnv(n).setParam("MIPGapAbs", stage_slack[name] / 2)
            # gaps and balance are solved exactly: a relative gap of 3 % of a large stage value (many gaps, or one
            # account that cannot be reached) would let avoidable gaps or other accounts outside the band pass
            # (and so is the small count of split weekends at the month start)
            for n, (name, _, _) in enumerate(objectives):
                if name in ("gaps", "balance_violation", "weekend_start", "saturdays"):
                    schedule.getMultiobjEnv(n).setParam("MIPGap", 0.0)
                # rotation counts every (person, window, type): 3 % of its value could leave a person without nights
                # for many windows; its time share ends it in any case
                if name == "rotation":
                    schedule.getMultiobjEnv(n).setParam("MIPGap", 0.0)
            # the time limit is a promise to the user: should a pass overrun it, stop the whole run shortly after
            deadline = started + timeout + WATCHDOG_GRACE_SECONDS

            def watchdog(model: gp.Model, _where: int) -> None:
                if monotonic() > deadline:
                    model.terminate()

            schedule.optimize(watchdog)
            # status first: without a solution Gurobi has no values to read
            if schedule.Status == GRB.OPTIMAL:
                status = SolutionStatus.OPTIMAL
            elif schedule.Status in (GRB.INFEASIBLE, GRB.INF_OR_UNBD):
                status = SolutionStatus.INFEASIBLE
            elif schedule.SolCount > 0:
                status = SolutionStatus.FEASIBLE
            else:
                status = SolutionStatus.UNKNOWN
            configuration = RunConfiguration(policy=POLICY, timeout_seconds=timeout,
                                             search_workers=settings.solver_num_search_workers,
                                             random_seed=settings.solver_random_seed)
            if schedule.SolCount == 0:
                return Solution(status=status, configuration=configuration, wall_time_seconds=schedule.Runtime)
            # construct solution: read all values at once; the Sunday taken along is not part of the schedule
            values = schedule.getAttr("X", assignment)
            assignments = tuple(sorted(
                (
                    Assignment(employee_id=i, shift_id=s, date=d, planning_unit_id=u, staff_level=level_at[i, u, d])
                    for (i, s, d, u), value in values.items()
                    if value > 0.5 and d in D_set
                ),
                key=lambda a: (a.date, a.planning_unit_id, a.shift_id, a.employee_id),
            ))
            # gaps exactly as the schedule check counts them: max(0, required - assigned) per demand row
            covered = Counter(a.demand_key for a in assignments)
            gaps = tuple(
                Gap(planning_unit_id=r.planning_unit_id, date=r.date, shift_id=r.shift_id,
                    staff_level=r.staff_level, missing_count=r.required_count - covered[r.demand_key])
                for r in dataset.demand_requirements
                if covered[r.demand_key] < r.required_count
            )
            # stage values computed from the schedule itself where helper variables may lie above the true value
            # (a tolerance lets the following stages loosen them)
            missing_of_day = Counter()
            for g in gaps:
                missing_of_day[g.planning_unit_id, g.date] += g.missing_count
            staff_count = Counter((a.planning_unit_id, a.date) for a in assignments)
            shift_count = Counter((a.planning_unit_id, a.shift_id, a.date) for a in assignments)
            shift_balance_value = sum(
                abs(shift_count[u, s, d] - required_usd.get((u, s, d), 0) / required_ud[u, d] * staff_count[u, d])
                for (u, s, d) in balance_keys
            )
            staffing_spread_value = 0.0
            for u, required_month in required_u.items():
                month_staff = sum(staff_count[u, d] for d in D)
                staffing_spread_value += sum(
                    abs(staff_count[u, d] - required_ud.get((u, d), 0) / required_month * month_staff) for d in D
                )
            # rotation: the (person, window, type) of the stage whose type the schedule has in the window
            type_of = {shift.shift_id: shift.type for shift in dataset.shifts}
            worked_on = {(a.employee_id, a.date): type_of[a.shift_id] for a in assignments}
            rotation_value = sum(
                any(worked_on.get((i, w + timedelta(days=j))) == k for j in range(Rot_w))
                for (i, w, k) in worked_type
            )
            saturday_count = Counter(a.employee_id for a in assignments if a.date.weekday() == 5)
            plan_value = {
                "gaps": sum(g.missing_count for g in gaps),
                "rotation": rotation_value,
                "saturdays": sum(count ** 2 for count in saturday_count.values()),
                "gap_spread": round(sum(missing_of_day[u, d] ** 2 / r for (u, d), r in required_ud.items())),
                "staffing_spread": round(staffing_spread_value),
                "shift_balance": round(shift_balance_value),
            }
            stages = []
            for n, (name, expr, maximize) in enumerate(objectives):
                # one pass per objective, since all priorities differ
                schedule.Params.ObjPassNumber = n
                try:
                    pass_status = schedule.ObjPassNStatus
                    bound = schedule.ObjPassNObjBound
                    bound = (-bound if maximize else bound) if math.isfinite(bound) else None
                except (gp.GurobiError, AttributeError):  # the time ran out before this pass
                    pass_status, bound = None, None
                stages.append(StageReport(
                    name=name,
                    status=SolutionStatus.OPTIMAL if pass_status == GRB.OPTIMAL else SolutionStatus.FEASIBLE,
                    value=plan_value[name] if name in plan_value else round(expr.getValue()),
                    best_bound=bound,
                ))
            stages = tuple(stages)
            if status == SolutionStatus.OPTIMAL and any(stage.status != SolutionStatus.OPTIMAL for stage in stages):
                status = SolutionStatus.FEASIBLE
            return Solution(
                status=status,
                configuration=configuration,
                wall_time_seconds=schedule.Runtime,
                assignments=assignments,
                gaps=gaps,
                stages=stages,
                check=check_schedule(dataset, assignments, gaps),
            )
