"use client";

import { usePathname, useRouter } from "next/navigation";
import { useTransition } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { PlanningScope } from "@/lib/scope";
import { MONTHS, PLANNING_YEARS, selectionMonth, selectionSearch } from "@/lib/selection";

/** Month and year of the plan; the station is always the demo station. The URL is the only state. */
export function PlanningScopePicker({ month, error }: PlanningScope) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [year, monthNumber] = month.split("-").map(Number);

  const changeMonth = (nextMonth: string) =>
    nextMonth !== month && startTransition(() => router.push(`${pathname}${selectionSearch(nextMonth)}`));

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Planungsmonat">
      <Select
        value={String(monthNumber)}
        onValueChange={(value) => changeMonth(selectionMonth(year, Number(value)))}
        disabled={pending}
      >
        <SelectTrigger className="h-8 w-[124px]" aria-label="Monat">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {MONTHS.map((label, index) => (
            <SelectItem key={label} value={String(index + 1)}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={String(year)}
        onValueChange={(value) => changeMonth(selectionMonth(Number(value), monthNumber))}
        disabled={pending}
      >
        <SelectTrigger className="h-8 w-[92px]" aria-label="Jahr">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PLANNING_YEARS.map((option) => (
            <SelectItem key={option} value={String(option)}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          Daten nicht geladen
        </p>
      )}
    </div>
  );
}
