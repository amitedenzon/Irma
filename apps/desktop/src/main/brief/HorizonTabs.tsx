import type { Horizon } from "../../lib/types";

const ORDER: { id: Horizon; label: string }[] = [
  { id: "day", label: "Today" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
  { id: "all", label: "Overview" },
];

export function HorizonTabs({
  current,
  onChange,
}: {
  current: Horizon;
  onChange: (h: Horizon) => void;
}) {
  return (
    <div className="flex gap-1 text-sm">
      {ORDER.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          type="button"
          className={
            "px-3 py-1 rounded border transition-colors " +
            (current === t.id
              ? "border-irma-indigo text-irma-text bg-irma-surface"
              : "border-transparent text-irma-mute hover:text-irma-text")
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
