import math
from collections import Counter, defaultdict
from datetime import timedelta

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
from app.solver.models import RunConfiguration, Solution, SolutionStatus, StageReport


class GurobiSolverService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def solve(self, dataset: SchedulingDataset, timeout: float | None = None) -> Solution:
        settings = self._settings
        timeout = timeout if timeout is not None else settings.solver_max_time_seconds
        # log only when asked (SOLVER_LOG_SEARCH_PROGRESS); this also silences the license banner
        env_params = {"OutputFlag": 1 if settings.solver_log_search_progress else 0}
        with gp.Env(params=env_params) as env, gp.Model("schedule", env=env) as schedule:
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
            # (employee, station, day) -> qualification the duty is credited as, from the membership active that day
            level_at = {}
            for m in dataset.planning_unit_memberships:
                if m.planning_unit_id in dataset.station_ids:
                    for d in D:
                        if m.active_on(d):
                            level_at.setdefault((m.employee_id, m.planning_unit_id, d), m.staff_level)
            # who covers which demand: (station, day, qualification) -> employees
            staff_for = defaultdict(list)
            for (i, u, d), l in level_at.items():
                staff_for[u, d, l].append(i)
            # Saturdays whose Sunday lies in the month (for "same shift Sat/Sun")
            D_s = [date for date in D[:-1] if date.weekday() == 5]
            # all weekends that touch the month, in order (for "no two in a row")
            W = [date for date in D if date.weekday() == 5]
            if D_prev and D_prev[-1].weekday() == 5:
                D_s = D_prev[-1:] + D_s
                W = D_prev[-1:] + W
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
            K_s = 10
            Dist_n = 7

            training = defaultdict(set)
            for absence in dataset.availability:
                if absence.availability_type == 'training':
                    training[absence.employee_id].add(absence.date)
            # blocking absences (vacation, free day, training, unavailable) and vacation days
            blocked = {(a.employee_id, a.date) for a in dataset.availability if a.availability_type in BLOCKING_AVAILABILITY}
            vacation = {(a.employee_id, a.date) for a in dataset.availability if a.availability_type == AvailabilityType.VACATION}

            past_shifts = {}
            for entry in dataset.context.duties:
                past_shifts[(entry.employee_id,entry.date)] = entry.shift_id

            # (employee, shift, day) that availability forbids
            not_allowed = set()
            # assign absences: available_only allows only its shifts, every other absence blocks the day
            for absence in dataset.availability:
                for s in S:
                    if absence.availability_type != "available_only" or s not in absence.shift_ids:
                        not_allowed.add((absence.employee_id, s, absence.date))
            # no night shift before a blocked day (a night touches the next day)
            # and no late shift on the day before vacation begins
            for i in I:
                for d in D[:-1]:
                    next_day = d + timedelta(days=1)
                    if (i, next_day) in blocked:
                        for s in S_night:
                            not_allowed.add((i, s, d))
                    if (i, next_day) in vacation and (i, d) not in vacation:
                        for s in S_late:
                            not_allowed.add((i, s, d))

            transfer_penalty = 10
            wish_reward = 30

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
                if entry.type == "free_day":
                    for u in U:
                        for s in S:
                            pref[entry.employee_id,s,entry.date,u] -= wish_reward
                elif entry.type == "free_shift":
                    for u in U:
                        pref[entry.employee_id,entry.shift_id,entry.date,u] -= wish_reward
                elif entry.type == "preferred_day":
                    for u in U:
                        for s in S:
                            pref[entry.employee_id,s,entry.date,u] += wish_reward
                elif entry.type == "preferred_shift":
                    for u in U:
                        pref[entry.employee_id,entry.shift_id,entry.date,u] += wish_reward

            # minimum demand: (shift, day, station, qualification) -> required count, only rows with demand
            R_min = {(r.shift_id, r.date, r.planning_unit_id, r.staff_level): r.required_count for r in dataset.demand_requirements}
            # Decision variables
            # assignment only for duties that can happen: a station membership active that day (7b: allowed
            # by availability); duties before the month are constants from past_shifts, not variables
            assignment = schedule.addVars(
                [(i, s, d, u) for (i, u, d) in level_at for s in S if (i, s, d) not in not_allowed],
                vtype=GRB.BINARY, name="assignment")
            gap = schedule.addVars(R_min.keys(), lb=0.0, vtype=GRB.CONTINUOUS, name="gap")
            n_beg = schedule.addVars(I, D_prev[-1:] + D, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_beg")
            # days on which the end of a night block matters: recovery and distance to the next block
            D_end = D_prev[-max(Dist_n, L_n + 1):] + D[:-1]
            n_end = schedule.addVars(I, D_end, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_end")
            hour = schedule.addVars(I, vtype=GRB.CONTINUOUS, lb=-GRB.INFINITY, name="hour")
            # minutes by which a balance leaves the band of ±POLICY.balance_tolerance_minutes
            over = schedule.addVars(I, vtype=GRB.CONTINUOUS, lb=0.0, name="over")
            cons_s = schedule.addVars(I, S, D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="cons_s")
            cons_x = schedule.addVars(I, D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="cons_x")
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

            days = D_prev + D
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

            # Objective functions
            # (name, expression, maximize), highest priority first
            objectives = [
                ("gaps", gap.sum(), False),
                ("balance_violation", over.sum(), False),
                # relative to the day's demand: a gap weighs more on a day with less demand
                ("gap_spread", gp.quicksum(gap_sq[u, d] / required for (u, d), required in required_ud.items()), False),
                ("wishes",gp.quicksum(score * assignment[key] for key, score in pref.items() if score and key in assignment), True),
                ("shift_balance", dev.sum(), False),
                ("Min_L_to_E",L_to_E.sum(), False),
                ("cons", cons_s.sum() + 2*cons_x.sum(), True),
            ]
            for n, (name, expr, maximize) in enumerate(objectives):
                schedule.setObjectiveN(-expr if maximize else expr, index=n, priority=len(objectives) - 1 - n, name=name)
            schedule.ModelSense = GRB.MINIMIZE
            # Constraints
            # one shift per day
            schedule.addConstrs((work[i, d] <= 1 for i in I for d in D), name="one_shift")
            # min demand, credited with the membership's qualification
            schedule.addConstrs((gp.quicksum(assignment[i, s, d, u] for i in staff_for[u, d, l] if (i, s, d, u) in assignment) + gap[s, d, u, l] >= required
                                 for (s, d, u, l), required in R_min.items()), name="demand")
            # define workhours
            minutes = defaultdict(list)
            for (i, s, d, u), var in assignment.items():
                minutes[i].append(h[s] * var)
            schedule.addConstrs((gp.quicksum(minutes[i]) + credits[i] - hour[i] == t[i] for i in I), name="workhours")
            # balance band, soft: over[i] is the excess beyond ±tolerance
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
            # define cons_s and cons_x
            one_day = timedelta(days=1)
            schedule.addConstrs((cons_s[i,s,d] <= shift_on(i, s, d) for i in I for s in S for d in D));
            schedule.addConstrs((cons_s[i,s,d] <= shift_on(i, s, d - one_day) for i in I for s in S for d in D));
            schedule.addConstrs((cons_x[i,d] <= 1 - work[i, d] for i in I for d in D));
            schedule.addConstrs((cons_x[i,d] <= 1 - at(work, i, d - one_day) for i in I for d in D));
            # max consecutive workdays
            for i in I:
                for d in D_prev[-K_s:] + D[:-K_s]:
                    window = [d + timedelta(days=k) for k in range(K_s + 1)]
                    fixed = len(training[i].intersection(window))
                    schedule.addConstr(gp.quicksum(at(work, i, day) for day in window) + fixed <= K_s)
            # define L_to_E
            schedule.addConstrs(L_to_E[i, d] >= at(late, i, d - one_day) + early[i, d] - 1 for i in I for d in D);
            # max consecutive nights
            for i in I:
                for d in D_prev[-POLICY.max_consecutive_nights:]+ D[:-POLICY.max_consecutive_nights]:
                    window = [d + timedelta(days=k) for k in range(POLICY.max_consecutive_nights + 1)]
                    schedule.addConstr(gp.quicksum(at(night, i, day) for day in window) <= POLICY.max_consecutive_nights)
            # define beginning and end of nightshiftblock; lower bounds suffice, because n_beg and n_end
            # appear only in <= 1 constraints with positive sign and in no objective
            schedule.addConstrs((n_beg[i,d] >= night[i, d] - at(night, i, d - one_day) for i in I for d in D_prev[-1:] + D));
            schedule.addConstrs((n_end[i,d] >= night[i, d] - at(night, i, d + one_day) for i in I for d in D_end));
            # no nightshift block starts and ends on the same day
            schedule.addConstrs(n_beg[i,d]+n_end[i,d]<=1 for i in I for d in D_prev[-1:] + D[:-1]);
            # ensure recovery days after nightshift block (only month days: the past is never constrained against itself)
            for i in I:
                for d in D_prev[-(L_n+1):] + D[:-1]:
                    for j in range(1,L_n+1):
                        if d + timedelta(days=j) in D_set:
                            schedule.addConstr(n_end[i, d] + work[i, d + timedelta(days=j)] <= 1)
                    # no early shift after recovery days
                    if d + timedelta(days=L_n+1) in D_set:
                        schedule.addConstr(n_end[i, d] + early[i, d + timedelta(days=L_n+1)] <= 1)
            # same shifts on weekends
            schedule.addConstrs((shift_on(i, s, d) == shift_on(i, s, d + one_day) for i in I for s in S for d in D_s));
            # min days between nightshift block (only blocks starting in the month)
            for i in I:
                for d in D_prev[-Dist_n:] + D:
                    forbidden_starts = [d+timedelta(days=j) for j in range(1, Dist_n + 1) if d+timedelta(days=j) in D_set]
                    if forbidden_starts:
                        schedule.addConstr(n_end[i, d] + gp.quicksum(n_beg[i, day] for day in forbidden_starts) <= 1)
            # not two cons weekends
            schedule.addConstrs(work[i, W[j]] + work[i, W[j+1]] <= 1 for i in I for j in range(len(W) - 1));
            # solve
            schedule.Params.TimeLimit = timeout
            schedule.Params.MIPGap = 0.03
            if settings.solver_num_search_workers is not None:
                schedule.Params.Threads = settings.solver_num_search_workers
            if settings.solver_random_seed is not None:
                schedule.Params.Seed = settings.solver_random_seed
            # time limit of single stages as a share of the total time; the other stages run until the total limit
            stage_time_share = {"gap_spread": 0.15, "shift_balance": 0.1, "Min_L_to_E": 0.2}
            for n, (name, _, _) in enumerate(objectives):
                if name in stage_time_share:
                    # pass n is objective n, since the priorities fall with the index
                    schedule.getMultiobjEnv(n).setParam("TimeLimit", stage_time_share[name] * timeout)
            schedule.optimize()
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
            # construct solution: read all values at once
            values = schedule.getAttr("X", assignment)
            assignments = tuple(sorted(
                (
                    Assignment(employee_id=i, shift_id=s, date=d, planning_unit_id=u, staff_level=level_at[i, u, d])
                    for (i, s, d, u), value in values.items()
                    if value > 0.5
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
                    value=sum(g.missing_count for g in gaps) if name == "gaps" else round(expr.getValue()),
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
