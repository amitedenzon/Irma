import type { Project } from "../../lib/types";

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
  const active = projects.filter((p) => p.status !== "archived");
  const archived = projects.filter((p) => p.status === "archived");

  return (
    <aside className="w-60 border-r border-irma-border pr-3 text-sm">
      <ul>
        {active.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => onSelect(p.id)}
              className={
                "w-full text-left py-1 px-2 rounded flex items-center gap-2 " +
                (selectedId === p.id
                  ? "bg-irma-surface text-irma-text"
                  : "text-irma-mute hover:text-irma-text")
              }
            >
              <span className="text-xs">P{p.priority}</span>
              <span className="flex-1 truncate">{p.name}</span>
            </button>
          </li>
        ))}
      </ul>
      {archived.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-irma-mute cursor-pointer">archived ({archived.length})</summary>
          <ul className="mt-1">
            {archived.map((p) => (
              <li key={p.id}>
                <button onClick={() => onSelect(p.id)}
                        className="w-full text-left py-1 px-2 rounded text-irma-mute hover:text-irma-text">
                  {p.name}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <button onClick={onNew} className="mt-3 w-full text-left text-xs text-irma-indigo px-2 py-1">
        + new project
      </button>
    </aside>
  );
}
