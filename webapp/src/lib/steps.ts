import { CalendarCheck, CalendarHeart, CalendarPlus, UserCog, Users, type LucideIcon } from "lucide-react";
import { areaColors } from "@/lib/area-colors";

interface Step {
  title: string;
  description: string;
  icon: LucideIcon;
  href: string;
  /** Tinted icon tile on the overview. */
  color: string;
}

/** The planning pages in their usual order, as the overview's cards. */
export const steps = [
  {
    title: "Mitarbeiter",
    description: "Mitarbeiter der Station mit Qualifikation, Monatskonto und Verfügbarkeit ansehen",
    icon: Users,
    href: "/employees",
    color: areaColors.employees.icon,
  },
  {
    title: "Verfügbarkeit",
    description: "Einschränkungen und Wünsche einzelner Mitarbeiter im Monat bearbeiten",
    icon: CalendarHeart,
    href: "/availability",
    color: areaColors.availability.icon,
  },
  {
    title: "Mindestbesetzung",
    description: "Benötigtes Personal je Tag, Schicht und Qualifikation festlegen",
    icon: UserCog,
    href: "/staffing",
    color: areaColors.staffing.icon,
  },
  {
    title: "Dienstplan erstellen",
    description: "Einen Dienstplan für den ganzen Monat berechnen lassen",
    icon: CalendarPlus,
    href: "/generation",
    color: areaColors.createRoster.icon,
  },
  {
    title: "Dienstplan prüfen",
    description: "Den erstellten Dienstplan ansehen, speichern oder einen gespeicherten Plan laden",
    icon: CalendarCheck,
    href: "/review",
    color: areaColors.reviewRoster.icon,
  },
] as const satisfies readonly Step[];
