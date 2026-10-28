from app.domain import SchedulingDataset
from app.settings import Settings
from app.solver.models import Solution
from datetime import timedelta
from app.domain import StaffLevel
import gurobipy as gp
from gurobipy import GRB
from app.solver.models import RunConfiguration, Solution, SolutionStatus, StageReport
from app.domain import (
    POLICY,
    SchedulingDataset,
    Assignment,
    ShiftType,
    Gap,
    check_schedule
)

class GurobiSolverService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings        

    def solve(self, dataset: SchedulingDataset, timeout: float | None = None) -> Solution:
        timeout = timeout if timeout is not None else self._settings.solver_max_time_seconds
        with gp.Env() as env, gp.Model("schedule", env=env) as schedule:
            # Sets and Indices
            U = []
            for unit in dataset.planning_units:
                U.append(unit.planning_unit_id)
            L = [level.value for level in StaffLevel]
            stations_of = {
                e.employee_id: sorted({
                    m.planning_unit_id
                    for m in dataset.planning_unit_memberships
                    if m.employee_id == e.employee_id and m.planning_unit_id in dataset.station_ids
                })
                for e in dataset.employees
            }

            I = []
            I_l = {l:[] for l in L}
            for employee in dataset.employees:
                I.append(employee.employee_id)
                I_l[employee.staff_level].append(employee.employee_id)
            S = []
            S_id = {}
            for shift in dataset.shifts:
                S.append(shift.shift_id)
                S_id[shift.code] = shift.shift_id
            D = list(dataset.planning_month.dates)
            D_prev = [dataset.context.covered_from + timedelta(days=i) for i in range((dataset.planning_month.dates[0] - dataset.context.covered_from).days)]
            D_s = [date for date in dataset.planning_month.dates[:-1] if date.weekday() == 5]
            if D_prev and D_prev[-1].weekday() == 5:
                D_s.append(D_prev[-1])
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

            training = {i:[] for i in I}
            absences = {i:{d:0 for d in D_prev[-Dist_n:] + D} for i in I}
            for absence in dataset.availability:
                if absence.availability_type == 'training':
                    training[absence.employee_id].append(absence.date)
                absences[absence.employee_id][absence.date] = 1
            
            past_shifts = {}
            for entry in dataset.context.duties:
                past_shifts[(entry.employee_id,entry.date)] = entry.shift_id

            home_reward = 10
            wish_reward = 30

            pref = {(i,s,d,u):0 for i in I for s in S for d in D for u in U}
            for entry in dataset.planning_unit_memberships:
                if entry.is_home:
                    for s in S:
                        for d in D:
                            pref[entry.employee_id,s,d,entry.planning_unit_id] += 10
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

            R_min = {}
            for s in S:
                for d in D:
                    for u in U:
                        for l in L:
                            R_min[s, d, u, l] = 0
            for entry in dataset.demand_requirements:
                R_min[entry.shift_id,entry.date,entry.planning_unit_id,entry.staff_level] = entry.required_count
            # Decision variables
            assignment = schedule.addVars(I, S, D_prev + D, U, vtype=GRB.BINARY,name="assignment")
            gap = schedule.addVars(S, D, U, L, lb=0.0, vtype=GRB.CONTINUOUS, name="gap")
            n_beg = schedule.addVars(I, D_prev[-Dist_n:] + D, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_beg")
            n_end = schedule.addVars(I, D_prev[-Dist_n:] + D[:-1], vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_end")
            hour = schedule.addVars(I, vtype=GRB.CONTINUOUS, lb=-GRB.INFINITY, name="hour")
            hour_max = schedule.addVars(L, vtype=GRB.CONTINUOUS, lb=-GRB.INFINITY, name="hour_max")
            hour_min = schedule.addVars(L, vtype=GRB.CONTINUOUS, lb=-GRB.INFINITY, name="hour_min")
            cons_s = schedule.addVars(I, S, D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="cons_s")
            cons_x = schedule.addVars(I, D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="cons_x")
            L_to_E = schedule.addVars(I,D, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="L_to_E")
            # Objective functions
            schedule.setObjectiveN(gap.sum(), index=0, priority=4, name="gaps")
            schedule.setObjectiveN(hour_max.sum() - hour_min.sum(), index=1, priority=3, abstol=300, name="hour_max")
            schedule.setObjectiveN(-gp.quicksum(pref[i,s,d,u]*assignment[i,s,d,u] for i in I for s in S for d in D for u in U), index=2, priority=2, name="wishes")
            schedule.setObjectiveN(L_to_E.sum(), index=3, priority=1, name="Min_L_to_E")
            schedule.setObjectiveN(-(cons_s.sum() + 2*cons_x.sum()), index=4, priority=0, name="cons")
            schedule.ModelSense = GRB.MINIMIZE
            # Constraints
            # one shift per day
            schedule.addConstrs((assignment.sum(i, '*', d, '*') <= 1 for i in I for d in D));
            # assign absences
            for absence in dataset.availability:
                if absence.availability_type == "available_only":
                    for s in S:
                        if s in absence.shift_ids:
                            continue
                        for u in U:
                            assignment[absence.employee_id,s,absence.date,u].ub = 0.0
                else:
                    for s in S:
                        for u in U:
                            assignment[absence.employee_id,s,absence.date,u].ub = 0.0
            # no night or late shift before vacation
                        for i in I:
                            for d in D[1:]:
                                if absences[i][d] == 1 and absences[i][d-timedelta(days=1)] == 0:
                                    for u in U:
                                        assignment[i,S_id['N'],d-timedelta(days=1),u].ub = 0.0
                                        assignment[i,S_id['S'],d-timedelta(days=1),u].ub = 0.0
            # assign duties
            for i in I:
                for d in D_prev:
                    if (i,d) in past_shifts.keys():
                        assignment[i, past_shifts[(i,d)],d,U[0]].lb = 1.0
                    else:
                        for s in S:
                            for u in U:
                                assignment[i, s,d, u].ub = 0.0
            # only assign on allowed units
            for i in I:
                for u in U:
                    if u not in stations_of[i]:
                        for s in S:
                            for d in D:
                                assignment[i,s,d,u].ub = 0
            # min demand
            for l in L:
                schedule.addConstrs((assignment.sum(I_l[l], s, d, u) + gap[s, d, u, l] >= R_min[s, d, u, l] for s in S for d in D for u in U));
            # define workhours
            schedule.addConstrs(gp.quicksum(h[s] * assignment.sum(i,s,d,u) for s in S for d in D for u in U) - hour[i] == t[i] for i in I);
            for l in L:
                if I_l[l]:
                    schedule.addConstrs(hour_max[l] >= hour[i] for i in I_l[l]);
                    schedule.addConstrs(hour_min[l] <= hour[i] for i in I_l[l]);
                else:
                    schedule.addConstr(hour_max[l] >= 0)
                    schedule.addConstr(hour_min[l] <= 0)
            # define cons_s and cons_x
            schedule.addConstrs((cons_s[i,s,d] <= assignment.sum(i,s,d,'*') for i in I for s in S for d in D));
            schedule.addConstrs((cons_s[i,s,d] <= assignment.sum(i,s,d-timedelta(days=1),'*') for i in I for s in S for d in D));
            schedule.addConstrs((cons_x[i,d] <= 1 - assignment.sum(i,'*',d,'*') for i in I for d in D));
            schedule.addConstrs((cons_x[i,d] <= 1 - assignment.sum(i,'*',d-timedelta(days=1),'*') for i in I for d in D));
            # max consecutive workdays
            for i in I:
                for d in D_prev[-K_s:] + D[:-K_s]:
                    window = [d+timedelta(days=i) for i in range(K_s + 1)]
                    fixed = len(set(window).intersection(set(training[i])))
                    schedule.addConstr(assignment.sum(i, '*', window, '*') + fixed <= K_s)
            # define L_to_E
            schedule.addConstrs(L_to_E[i, d] >= assignment.sum(i, S_id['S'], d-timedelta(days=1),'*') + assignment.sum(i, S_id['F'], d,'*') - 1 for i in I for d in D);
            # max consecutive nights
            for i in I:
                for d in D_prev[-POLICY.max_consecutive_nights:]+ D[:-POLICY.max_consecutive_nights]:
                    window = [d+timedelta(days=i) for i in range(POLICY.max_consecutive_nights + 1)]
                    schedule.addConstr(assignment.sum(i,S_id['N'],window,'*')<= POLICY.max_consecutive_nights)
            # define beginning of nightshiftblock
            schedule.addConstrs((n_beg[i,d] >= assignment.sum(i,S_id['N'],d,'*') - assignment.sum(i,S_id['N'],d-timedelta(days=1),'*') for i in I for d in D_prev[-1:] + D));
            schedule.addConstrs((n_beg[i,d] <= assignment.sum(i,S_id['N'],d,'*') for i in I for d in D_prev[-1:] + D))
            schedule.addConstrs((n_beg[i,d] <= 1 - assignment.sum(i,S_id['N'],d-timedelta(days=1),'*') for i in I for d in D_prev[-1:] + D));
            # define end of nightshiftblock
            schedule.addConstrs((n_end[i,d] >= assignment.sum(i,S_id['N'],d,'*') - assignment.sum(i,S_id['N'],d+timedelta(days=1),'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            schedule.addConstrs((n_end[i,d] <= assignment.sum(i,S_id['N'],d,'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            schedule.addConstrs((n_end[i,d] <= 1 - assignment.sum(i,S_id['N'],d+timedelta(days=1),'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            # no nightshift block starts and ends on the same day
            schedule.addConstrs(n_beg[i,d]+n_end[i,d]<=1 for i in I for d in D_prev[-1:] + D[:-1]);
            # ensure recovery days after nightshift block
            for i in I:
                for d in D_prev[-(L_n+1):] + D[:-1]:
                    for j in range(1,L_n+1):
                        if d + timedelta(days=j) in D_prev[-L_n:] + D:
                            schedule.addConstr(n_end[i, d] + assignment.sum(i, '*', d + timedelta(days=j), '*') <= 1)
                    # no early shift after recovery days
                    schedule.addConstr((n_end[i, d] + assignment.sum(i, S_id['F'], d + timedelta(days=L_n+1), '*') <= 1))
            # same shifts on weekends
            schedule.addConstrs((assignment.sum(i, s, d, '*') == assignment.sum(i, s, d+timedelta(days=1),'*') for i in I for s in S for d in D_s));
            # max 3 weekends each
            schedule.addConstrs((assignment.sum(i, '*', D_s, '*') <= 3 for i in I));
            # min days between nightshift block
            for i in I:
                for d in D_prev[-Dist_n:] + D:
                    forbidden_starts = [d+timedelta(days=j) for j in range(1, Dist_n + 1) if d+timedelta(days=j) in D_prev[-Dist_n:] + D]
                    if forbidden_starts:
                        schedule.addConstr(n_end[i, d] + n_beg.sum(i, forbidden_starts) <= 1)
            # not two cons weekends
            schedule.addConstrs(assignment.sum(i,'*',D_s[j],'*') + assignment.sum(i,'*',D_s[j+1],'*') <= 1 for i in I for j in range(len(D_s) - 1));
            # solve
            schedule.setParam("TimeLimit", timeout)
            schedule.Params.MIPGap = 0.03
            schedule.optimize()
            # construct solution
            assignments = tuple(
                Assignment(employee_id=i, shift_id=s, date=d, planning_unit_id=u, staff_level=l)
                for l in L for i in I_l[l] for s in S for d in D for u in U
                if assignment[i, s, d, u].X > 0.5
            )
            gaps = tuple(
                Gap(shift_id=s, date=d, planning_unit_id=u, staff_level=l, missing_count=int(var.X))
                for (s,d,u,l), var in gap.items()
                if int(var.X) > 0
            )
            stages = []
            for i in range(schedule.NumObjPasses):
                schedule.Params.ObjNumber = i
                stages.append(StageReport(
                    name=schedule.ObjNName,
                    status=SolutionStatus.OPTIMAL if schedule.ObjPassNStatus==2 else SolutionStatus.FEASIBLE,
                    value=int(schedule.ObjNVal),
                    best_bound=int(schedule.ObjPassNObjBound)))
            stages = tuple(stages)
            if schedule.Status == GRB.OPTIMAL:
                status = SolutionStatus.OPTIMAL
            elif schedule.Status in (GRB.INFEASIBLE, GRB.INF_OR_UNBD):
                status = SolutionStatus.INFEASIBLE
            elif schedule.SolCount > 0:
                status = SolutionStatus.FEASIBLE
            else:
                status = SolutionStatus.UNKNOWN

            found = status in (SolutionStatus.OPTIMAL, SolutionStatus.FEASIBLE)
            return Solution(
                status=status,
                configuration=RunConfiguration(policy=POLICY, timeout_seconds=schedule.Params.TimeLimit,
                                            search_workers=None, random_seed=None),
                wall_time_seconds=schedule.Runtime,
                assignments=assignments if found else (),
                gaps=gaps if found else (),
                stages=stages if found else (),
                check=check_schedule(dataset, assignments, gaps) if found else None,
            )
