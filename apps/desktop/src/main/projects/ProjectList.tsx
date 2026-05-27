import type { Project } from "../../lib/types";
import { IconArchive, IconFolder, IconPlus } from "../../lib/icons";

export function ProjectList({
  projects,
  selectedId,
  onSelect,
  onNew,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const active = projects.filter((p) => p.status === "active");
  const paused = projects.filter((p) => p.status === "paused");
  const archived = projects.filter((p) => p.status === "archived");

  return (
    <aside
      className="w-64 shrink-0 overflow-y-auto border-r flex flex-col"
      style={{ background: "var(--color-paper)", borderColor: "var(--color-rule)" }}
    >
      <div className="px-3 pt-4 pb-2 flex items-baseline justify-between">
        <h2
          style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
          className="text-[11px] uppercase tracking-[0.18em]"
        >
          ── ledger ──
        </h2>
        <span
          style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}
          className="text-[10px]"
        >
          {active.length}/{projects.length}
        </span>
      </div>

      <Section title="active" projects={active} selectedId={selectedId} onSelect={onSelect} />
      {paused.length > 0 && (
        <Section title="paused" projects={paused} selectedId={selectedId} onSelect={onSelect} faded />
      )}
      {archived.length > 0 && (
        <details className="px-3 mt-2">
          <summary
            className="text-[10px] uppercase tracking-widest cursor-pointer flex items-center gap-1.5"
            style={{ color: "var(--color-ink-faint)" }}
          >
            <IconArchive size={11} /> archived ({archived.length})
          </summary>
          <ul className="mt-1 ml-1 space-y-0.5">
            {archived.map((p) => (
              <Row key={p.id} project={p} selected={p.id === selectedId} onSelect={onSelect} faded />
            ))}
          </ul>
        </details>
      )}

      <div className="flex-1" />
      <div className="px-3 py-3 border-t" style={{ borderColor: "var(--color-rule)" }}>
        <button
          type="button"
          onClick={onNew}
          className="w-full wax-seal px-3 py-1.5 flex items-center justify-center gap-1.5 text-[11px] uppercase tracking-wider"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          <IconPlus size={12} /> new project
        </button>
      </div>
    </aside>
  );
}

function Section({
  title,
  projects,
  selectedId,
  onSelect,
  faded,
}: {
  title: string;
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  faded?: boolean;
}) {
  return (
    <div className="px-3 mt-2">
      <div
        className="text-[10px] uppercase tracking-widest mb-1 flex items-center gap-2"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span>· {title}</span>
        <span className="rule-dash flex-1" />
      </div>
      <ul className="space-y-0.5">
        {projects.map((p) => (
          <Row
            key={p.id}
            project={p}
            selected={p.id === selectedId}
            onSelect={onSelect}
            faded={faded}
          />
        ))}
        {projects.length === 0 && (
          <li
            className="text-[11px] italic px-1 py-0.5"
            style={{ color: "var(--color-ink-faint)" }}
          >
            (none)
          </li>
        )}
      </ul>
    </div>
  );
}

function Row({
  project,
  selected,
  onSelect,
  faded,
}: {
  project: Project;
  selected: boolean;
  onSelect: (id: string) => void;
  faded?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(project.id)}
        className="w-full text-left px-2 py-1 flex items-center gap-2 text-[12px] transition-colors"
        style={{
          fontFamily: "var(--font-mono)",
          background: selected ? "var(--color-paper-fold)" : "transparent",
          color: faded ? "var(--color-ink-faint)" : "var(--color-ink)",
          borderLeft: selected ? "2px solid var(--color-red-seal)" : "2px solid transparent",
        }}
      >
        <IconFolder size={12} />
        <span className="flex-1 truncate">{project.name}</span>
        <span className={priorityClass(project.priority)}>P{project.priority}</span>
      </button>
    </li>
  );
}

function priorityClass(p: 1 | 2 | 3): string {
  if (p === 1) return "stamp stamp-p1";
  if (p === 2) return "stamp stamp-p2";
  return "stamp stamp-p3";
}
