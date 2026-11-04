import { cn } from "@/lib/utils";

export function BulletList({ items, label, className }: { items: string[]; label?: string; className?: string }) {
  return (
    <ul className={cn("list-disc space-y-0.5 pl-5", className)} aria-label={label}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
