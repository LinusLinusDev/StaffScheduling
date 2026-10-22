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
            for shift in dataset.shifts:
                S.append(shift.shift_id)
            S_n = [s.shift_id for s in dataset.shifts if s.type == ShiftType.NIGHT]
            S_e = [s.shift_id for s in dataset.shifts if s.type == ShiftType.EARLY]
            D = list(dataset.planning_month.dates)
            D_prev = [dataset.context.covered_from + timedelta(days=i) for i in range((dataset.planning_month.dates[0] - dataset.context.covered_from).days)]
            D_s = [date for date in dataset.planning_month.dates[:-1] if date.weekday() == 5]
            if D_prev and D_prev[-1].weekday() == 5:
                D_s.append(D_prev[-1])
            # Parameters
            L_n = POLICY.night_recovery_minutes//1440
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
            gap = schedule.addVars(S, D, U, L, lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="gap")
            n_beg = schedule.addVars(I, D_prev[-1:] + D, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_beg")
            n_end = schedule.addVars(I, D_prev[-(L_n+1):] + D[:-1], vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="n_end")
            # Objective functions
            schedule.setObjectiveN(gap.sum(), index=0, priority=1, name="gaps")
            schedule.setObjectiveN(assignment.sum(), index=1, priority=0, name="Min_Assignments")
            schedule.ModelSense = GRB.MINIMIZE
            # Constraints
            # one shift per day
            schedule.addConstrs((assignment.sum(i, '*', d, '*') <= 1 for i in I for d in D));
            # assign duties
            for duty in dataset.context.duties:
                if duty.planning_unit_id in U:
                    assignment[duty.employee_id,duty.shift_id,duty.date,duty.planning_unit_id].lb = 1.0
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
            # max consecutive nights
            for i in I:
                for d in D_prev[-POLICY.max_consecutive_nights:]+ D[:-POLICY.max_consecutive_nights]:
                    window = [d+timedelta(days=i) for i in range(POLICY.max_consecutive_nights + 1)]
                    schedule.addConstr(assignment.sum(i,S_n,window,'*')<= POLICY.max_consecutive_nights)
            # define beginning of nightshiftblock
            schedule.addConstrs((n_beg[i,d] >= assignment.sum(i,S_n,d,'*') - assignment.sum(i,S_n,d-timedelta(days=1),'*') for i in I for d in D_prev[-1:] + D));
            schedule.addConstrs((n_beg[i,d] <= assignment.sum(i,S_n,d,'*') for i in I for d in D_prev[-1:] + D))
            schedule.addConstrs((n_beg[i,d] <= 1 - assignment.sum(i,S_n,d-timedelta(days=1),'*') for i in I for d in D_prev[-1:] + D));
            # define end of nightshiftblock
            schedule.addConstrs((n_end[i,d] >= assignment.sum(i,S_n,d,'*') - assignment.sum(i,S_n,d+timedelta(days=1),'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            schedule.addConstrs((n_end[i,d] <= assignment.sum(i,S_n,d,'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            schedule.addConstrs((n_end[i,d] <= 1 - assignment.sum(i,S_n,d+timedelta(days=1),'*') for i in I for d in D_prev[-(L_n+1):] + D[:-1]));
            # no nightshift block starts and ends on the same day
            schedule.addConstrs(n_beg[i,d]+n_end[i,d]<=1 for i in I for d in D_prev[-1:] + D[:-1]);
            # ensure recovery days after nightshift block
            for i in I:
                for d in D_prev[-(L_n+1):] + D[:-1]:
                    for j in range(1,L_n+1):
                        schedule.addConstr(n_end[i, d] + assignment.sum(i, '*', d + timedelta(days=j), '*') <= 1)
                    # no early shift after recovery days
                    schedule.addConstr((n_end[i, d] + assignment.sum(i, S_e, d + timedelta(days=L_n+1), '*') <= 1))
            # same shifts on weekends
            schedule.addConstrs((assignment.sum(i, s, d, '*') == assignment.sum(i, s, d+timedelta(days=1),'*') for i in I for s in S for d in D_s));
            # solve
            schedule.setParam("TimeLimit", timeout)
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
            for i in range(schedule.NumObj):
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
