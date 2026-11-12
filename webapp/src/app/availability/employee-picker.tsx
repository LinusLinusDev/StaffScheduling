"use client";

import { useRouter } from "next/navigation";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { STAFF_LEVEL_LABELS } from "@/lib/labels";
import type { EmployeeSummary } from "@/lib/types";

/** Chooses the employee, shown with the qualification; the selection lives in the URL next to month and stations. */
export function EmployeePicker({
  href,
  employees,
  selectedId,
}: {
  /** The page URL with the current selection, without `employee`. */
  href: string;
  employees: EmployeeSummary[];
  selectedId: number;
}) {
  const router = useRouter();

  return (
    <div className="flex items-center gap-3">
      <Label htmlFor="employee-picker">Mitarbeiter</Label>
      <Select value={String(selectedId)} onValueChange={(value) => router.push(`${href}&employee=${value}`)}>
        <SelectTrigger id="employee-picker" className="w-80" aria-label="Mitarbeiter">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {employees.map(({ employee_id, display_name, staff_level }) => (
            <SelectItem key={employee_id} value={String(employee_id)}>
              {employee_id} · {display_name} · {STAFF_LEVEL_LABELS[staff_level]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
