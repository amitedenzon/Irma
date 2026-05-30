import { useState } from "react";
import {
  COMPANIONS,
  loadSettings,
  saveCompanionId,
  saveDockPosition,
  type DockPosition,
} from "../../lib/settings";

const DOCK_OPTIONS: { value: DockPosition; label: string; hint: string }[] = [
  {
    value: "on-dock",
    label: "On the Dock",
    hint: "Irma sits inside the Dock strip.",
  },
  {
    value: "beside-dock",
    label: "Beside the Dock",
    hint: "Irma stands next to the Dock, bottom-left.",
  },
];

export function SettingsView() {
  // Settings are persisted to localStorage immediately on change; local state
  // just mirrors the stored value for a responsive UI.
  const [companionId, setCompanionId] = useState<string>(
    () => loadSettings().companionId,
  );
  const [dockPosition, setDockPosition] = useState<DockPosition>(
    () => loadSettings().dockPosition,
  );

  const onCompanionChange = (id: string): void => {
    setCompanionId(id);
    saveCompanionId(id);
  };

  const onDockChange = (position: DockPosition): void => {
    setDockPosition(position);
    saveDockPosition(position);
  };

  return (
    <div className="px-6 py-6 max-w-3xl mx-auto space-y-5">
      <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
        Settings
      </p>

      {/* Companion picker */}
      <section className="card p-4 space-y-3">
        <div>
          <h3
            className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
            style={{ color: "var(--color-ink-mute)" }}
          >
            Companion
          </h3>
          <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            Choose which character lives beside your Dock.
          </p>
        </div>
        <div>
          <label
            className="block text-[11px] uppercase tracking-wider mb-1"
            style={{ color: "var(--color-ink-mute)" }}
          >
            Character
          </label>
          <select
            className="input"
            value={companionId}
            onChange={(e) => onCompanionChange(e.target.value)}
          >
            {COMPANIONS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      </section>

      {/* Dock placement (front-end only for now) */}
      <section className="card p-4 space-y-3">
        <div>
          <h3
            className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
            style={{ color: "var(--color-ink-mute)" }}
          >
            Placement
          </h3>
          <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            Where Irma should appear. (Takes effect later — saved for now.)
          </p>
        </div>
        <div className="space-y-2">
          {DOCK_OPTIONS.map((opt) => {
            const active = dockPosition === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => onDockChange(opt.value)}
                className="w-full text-left rounded-lg p-3 transition-colors"
                style={{
                  background: active
                    ? "var(--color-surface-2)"
                    : "var(--color-bg)",
                  border: `1px solid ${
                    active ? "var(--color-red)" : "var(--color-border)"
                  }`,
                }}
              >
                <div className="flex items-center justify-between">
                  <span
                    className="text-[13px] font-medium"
                    style={{ color: "var(--color-ink)" }}
                  >
                    {opt.label}
                  </span>
                  <span
                    className="inline-block w-3 h-3 rounded-full"
                    style={{
                      border: `2px solid ${
                        active ? "var(--color-red)" : "var(--color-ink-faint)"
                      }`,
                      background: active ? "var(--color-red)" : "transparent",
                    }}
                    aria-hidden="true"
                  />
                </div>
                <p
                  className="text-[12px] mt-0.5"
                  style={{ color: "var(--color-ink-faint)" }}
                >
                  {opt.hint}
                </p>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
