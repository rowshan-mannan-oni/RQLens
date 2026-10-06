import type { Severity } from "@/lib/types";

// Status colours are reserved for severity and always come with an icon and a label.
export const SEVERITY_STYLE: Record<
  Severity,
  { icon: string; label: string; className: string }
> = {
  severe: {
    icon: "⛔",
    label: "Severe",
    className:
      "bg-red-50 text-red-900 border-red-200 dark:bg-red-950/40 dark:text-red-200 dark:border-red-900",
  },
  warning: {
    icon: "⚠",
    label: "Warning",
    className:
      "bg-amber-50 text-amber-900 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900",
  },
  info: {
    icon: "ℹ",
    label: "Info",
    className:
      "bg-zinc-50 text-zinc-800 border-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-700",
  },
};

export const SEVERITY_ORDER: Severity[] = ["severe", "warning", "info"];

export function SeverityBadge({
  severity,
  count,
}: {
  severity: Severity;
  count?: number;
}) {
  const s = SEVERITY_STYLE[severity];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs font-medium ${s.className}`}
    >
      <span aria-hidden>{s.icon}</span>
      {count !== undefined ? `${count} ${s.label.toLowerCase()}` : s.label}
    </span>
  );
}
