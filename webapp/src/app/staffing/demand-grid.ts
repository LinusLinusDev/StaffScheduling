// The unsaved staffing demand of one station month. Cells are addressed by date, shift and
// qualification; a missing cell requires nobody. How cells are keyed stays inside this module.
import type { DemandCell, StaffLevel } from "@/lib/types";

export type DemandGrid = ReadonlyMap<string, DemandCell>;

/** The most staff one field may require, as the backend accepts it; the editor offers exactly 0 to this many. */
export const MAX_REQUIRED_COUNT = 5;

const keyOf = (date: string, shiftId: number, level: StaffLevel) => `${date}|${shiftId}|${level}`;

export function gridOf(cells: readonly DemandCell[]): DemandGrid {
  return new Map(cells.map((cell) => [keyOf(cell.date, cell.shift_id, cell.staff_level), cell]));
}

export function countAt(grid: DemandGrid, date: string, shiftId: number, level: StaffLevel): number {
  return grid.get(keyOf(date, shiftId, level))?.required_count ?? 0;
}

/** A copy with one cell changed; zero removes the cell. */
export function withCount(grid: DemandGrid, date: string, shiftId: number, level: StaffLevel, count: number) {
  const next = new Map(grid);
  const key = keyOf(date, shiftId, level);
  if (count === 0) next.delete(key);
  else next.set(key, { date, shift_id: shiftId, staff_level: level, required_count: count });
  return next as DemandGrid;
}

/** Where `grid` differs from `saved`: per cell, its saved count; a missing cell counts as zero. */
export function changesFrom(grid: DemandGrid, saved: DemandGrid) {
  const changed = new Map<string, number>();
  const levels = new Set<StaffLevel>();
  for (const cell of [...grid.values(), ...saved.values()]) {
    const key = keyOf(cell.date, cell.shift_id, cell.staff_level);
    const before = saved.get(key)?.required_count ?? 0;
    if ((grid.get(key)?.required_count ?? 0) === before) continue;
    changed.set(key, before);
    levels.add(cell.staff_level);
  }
  return {
    size: changed.size,
    /** The saved count of a changed cell, or undefined when the cell is unchanged. */
    savedCount: (date: string, shiftId: number, level: StaffLevel) => changed.get(keyOf(date, shiftId, level)),
    hasLevel: (level: StaffLevel) => levels.has(level),
  };
}

/** The complete month as the cells the API saves. */
export function cellsOf(grid: DemandGrid): DemandCell[] {
  return [...grid.values()];
}

/** `grid` with every cell of `level` taken from `source`, and the sorted dates whose counts change. */
export function withLevelFrom(grid: DemandGrid, source: DemandGrid, level: StaffLevel) {
  const next = new Map([...grid].filter(([, cell]) => cell.staff_level !== level));
  for (const [key, cell] of source) if (cell.staff_level === level) next.set(key, cell);
  const changed = new Set<string>();
  for (const [key, cell] of [...grid, ...next]) {
    if (cell.staff_level === level && grid.get(key)?.required_count !== next.get(key)?.required_count) {
      changed.add(cell.date);
    }
  }
  return { grid: next as DemandGrid, changedDates: [...changed].sort() };
}
