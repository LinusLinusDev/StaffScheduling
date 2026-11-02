"use server";

import { setAvailability, setWish } from "@/lib/api";
import { formatDate } from "@/lib/labels";
import type { AvailabilityEntry, WishEntry } from "@/lib/types";
import { type WriteResult, writeResult } from "@/lib/write-result";

/**
 * Write one day after the other and stop at the first failure. The API writes each day on its own, so days before a
 * failure stay saved; the message then says how many.
 */
async function saveDays(dates: string[], write: (date: string) => Promise<unknown>): Promise<WriteResult> {
  for (const [index, date] of dates.entries()) {
    const result = await writeResult(() => write(date), "/availability");
    if (!result.ok) {
      if (index === 0) return result;
      return {
        ok: false,
        error: `${result.error} Gespeichert für ${index} von ${dates.length} Tagen; ab ${formatDate(date)} nicht.`,
      };
    }
  }
  return { ok: true, value: null };
}

/** Save the employee's availability on these dates; `null` removes it. */
export async function saveAvailability(employeeId: number, dates: string[], entry: AvailabilityEntry | null) {
  return saveDays(dates, (date) => setAvailability(employeeId, date, entry));
}

/** Save the employee's wish on these dates; `null` removes it. */
export async function saveWish(employeeId: number, dates: string[], entry: WishEntry | null) {
  return saveDays(dates, (date) => setWish(employeeId, date, entry));
}
