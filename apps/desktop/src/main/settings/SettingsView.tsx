import { useEffect, useRef, useState } from "react";
import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";
import {
  COMPANIONS,
  loadSettings,
  saveCompanionId,
  saveDockPosition,
  type DockPosition,
} from "../../lib/settings";

const API = "http://127.0.0.1:8765/api/v1";

// ---------------------------------------------------------------------------
// Sub-tab
// ---------------------------------------------------------------------------
type SettingsTab = "general" | "api";

// ---------------------------------------------------------------------------
// API Keys metadata
// ---------------------------------------------------------------------------
interface KeyMeta {
  key: string;
  label: string;
  hint: string;
  secret: boolean;
  placeholder: string;
  guide: { title: string; steps: string[] };
}

const KEY_GROUPS: { title: string; description: string; keys: KeyMeta[] }[] = [
  {
    title: "Claude (AI)",
    description: "Powers Irma's synthesis and chat.",
    keys: [
      {
        key: "ANTHROPIC_API_KEY",
        label: "Anthropic API Key",
        hint: "console.anthropic.com → API Keys",
        secret: true,
        placeholder: "sk-ant-…",
        guide: {
          title: "Get your Anthropic API Key",
          steps: [
            "Go to console.anthropic.com and sign in (or create a free account).",
            'Open the "API Keys" page from the left sidebar.',
            'Click "Create Key", give it a name (e.g. "Irma"), and confirm.',
            "Copy the key — it starts with sk-ant-. You won't be able to see it again.",
            "Paste it into the field and hit Save.",
          ],
        },
      },
    ],
  },
  {
    title: "Google Calendar",
    description: "Lets Irma read your calendar for the daily brief.",
    keys: [
      {
        key: "GOOGLE_OAUTH_CLIENT_ID",
        label: "OAuth Client ID",
        hint: "Google Cloud Console → Credentials",
        secret: false,
        placeholder: "123456789-abc….apps.googleusercontent.com",
        guide: {
          title: "Create a Google OAuth credential",
          steps: [
            "Go to console.cloud.google.com and create (or pick) a project.",
            'Enable the "Google Calendar API" under APIs & Services → Library.',
            'Go to APIs & Services → Credentials → "Create Credentials" → OAuth client ID.',
            'Set Application type to "Desktop app", give it any name, and click Create.',
            "Copy the Client ID (ends in .apps.googleusercontent.com) and paste it here.",
            "Also copy the Client Secret for the next field.",
          ],
        },
      },
      {
        key: "GOOGLE_OAUTH_CLIENT_SECRET",
        label: "OAuth Client Secret",
        hint: "Same credential, Client Secret field",
        secret: true,
        placeholder: "GOCSPX-…",
        guide: {
          title: "Find your OAuth Client Secret",
          steps: [
            "In Google Cloud Console, go to APIs & Services → Credentials.",
            "Click the pencil icon next to the OAuth client you just created.",
            'The "Client secret" field is on that page — copy it.',
            "Paste it here. It typically starts with GOCSPX-.",
          ],
        },
      },
      {
        key: "GOOGLE_OAUTH_REFRESH_TOKEN",
        label: "Refresh Token",
        hint: 'Run "irma-api auth google" once in the terminal to capture this',
        secret: true,
        placeholder: "1//0A…",
        guide: {
          title: "Capture the Google Refresh Token",
          steps: [
            "Make sure GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are saved first.",
            "Open a terminal and run: irma-api auth google",
            "A browser window will open asking you to sign in to Google and grant calendar access.",
            "After you approve, the token is saved automatically to your .env file.",
            "You don't need to copy anything — come back here and the field will show \"✓ set\".",
          ],
        },
      },
    ],
  },
  {
    title: "Email (Resend)",
    description: "Required to receive your daily brief by email.",
    keys: [
      {
        key: "RESEND_API_KEY",
        label: "Resend API Key",
        hint: "resend.com → API Keys",
        secret: true,
        placeholder: "re_…",
        guide: {
          title: "Get your Resend API Key",
          steps: [
            "Go to resend.com and sign up for a free account.",
            'From the dashboard, open "API Keys" in the left sidebar.',
            'Click "Create API Key", name it "Irma", and confirm.',
            "Copy the key — it starts with re_.",
            "Paste it here and save. The free tier is enough for daily briefs.",
          ],
        },
      },
      {
        key: "IRMA_USER_EMAIL",
        label: "Your Email Address",
        hint: "Where Irma sends the brief",
        secret: false,
        placeholder: "you@example.com",
        guide: {
          title: "Your email address",
          steps: [
            "Enter the email address where you want to receive the daily brief.",
            "This is locked server-side — the LLM cannot change or override it.",
            "On Resend's free plan, delivery works without a custom domain when sending to the account's own verified email.",
          ],
        },
      },
    ],
  },
];

interface KeyStatus {
  key: string;
  set: boolean;
}

// ---------------------------------------------------------------------------
// Dock placement options
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  return (
    <div className="flex flex-col h-full">
      {/* Inner tab bar */}
      <div
        className="flex items-center gap-1 px-6 pt-4 border-b shrink-0"
        style={{ borderColor: "var(--color-border)" }}
      >
        {(["general", "api"] as SettingsTab[]).map((t) => {
          const active = activeTab === t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => setActiveTab(t)}
              className="px-3 py-1.5 text-[12px] font-medium capitalize transition-colors"
              style={{
                color: active ? "var(--color-red)" : "var(--color-ink-mute)",
                borderBottom: `2px solid ${active ? "var(--color-red)" : "transparent"}`,
                marginBottom: -1,
              }}
            >
              {t === "api" ? "API Keys" : "General"}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "general" && <GeneralTab />}
        {activeTab === "api" && <ApiTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// General tab
// ---------------------------------------------------------------------------
function GeneralTab() {
  const [companionId, setCompanionId] = useState<string>(
    () => loadSettings().companionId,
  );
  const [dockPosition, setDockPosition] = useState<DockPosition>(
    () => loadSettings().dockPosition,
  );
  const [autostart, setAutostart] = useState<boolean | null>(null);

  useEffect(() => {
    isEnabled()
      .then((v) => setAutostart(v))
      .catch(() => setAutostart(false));
  }, []);

  const onAutostartChange = async (checked: boolean) => {
    try {
      if (checked) await enable(); else await disable();
      setAutostart(checked);
    } catch (e) {
      console.error("[settings] autostart toggle failed", e);
    }
  };

  const onCompanionChange = (id: string) => {
    setCompanionId(id);
    saveCompanionId(id);
  };

  const onDockChange = (position: DockPosition) => {
    setDockPosition(position);
    saveDockPosition(position);
  };

  return (
    <div className="px-6 py-5 max-w-xl space-y-4">
      {/* Companion */}
      <section className="card p-4 space-y-3">
        <div>
          <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
              style={{ color: "var(--color-ink-mute)" }}>
            Companion
          </h3>
          <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            Choose which character lives beside your Dock.
          </p>
        </div>
        <div>
          <label className="block text-[11px] uppercase tracking-wider mb-1"
                 style={{ color: "var(--color-ink-mute)" }}>
            Character
          </label>
          <select className="input" value={companionId}
                  onChange={(e) => onCompanionChange(e.target.value)}>
            {COMPANIONS.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </section>

      {/* Placement */}
      <section className="card p-4 space-y-3">
        <div>
          <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
              style={{ color: "var(--color-ink-mute)" }}>
            Placement
          </h3>
          <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            Where Irma appears. Takes effect on next restart.
          </p>
        </div>
        <div className="space-y-2">
          {DOCK_OPTIONS.map((opt) => {
            const active = dockPosition === opt.value;
            return (
              <button key={opt.value} type="button"
                      onClick={() => onDockChange(opt.value)}
                      className="w-full text-left rounded-lg p-3 transition-colors"
                      style={{
                        background: active ? "var(--color-surface-2)" : "var(--color-bg)",
                        border: `1px solid ${active ? "var(--color-red)" : "var(--color-border)"}`,
                      }}>
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium" style={{ color: "var(--color-ink)" }}>
                    {opt.label}
                  </span>
                  <span className="inline-block w-3 h-3 rounded-full"
                        style={{
                          border: `2px solid ${active ? "var(--color-red)" : "var(--color-ink-faint)"}`,
                          background: active ? "var(--color-red)" : "transparent",
                        }} />
                </div>
                <p className="text-[12px] mt-0.5" style={{ color: "var(--color-ink-faint)" }}>
                  {opt.hint}
                </p>
              </button>
            );
          })}
        </div>
      </section>

      {/* Launch at startup */}
      <section className="card p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[13px] font-medium" style={{ color: "var(--color-ink)" }}>
              Launch at startup
            </p>
            <p className="text-[12px] mt-0.5" style={{ color: "var(--color-ink-faint)" }}>
              Start Irma automatically when you log in to macOS.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autostart ?? false}
            disabled={autostart === null}
            onClick={() => void onAutostartChange(!(autostart ?? false))}
            className="shrink-0 disabled:opacity-40"
            style={{
              position: "relative",
              width: 44,
              height: 26,
              borderRadius: 13,
              background: autostart ? "var(--color-red)" : "var(--color-surface-2)",
              border: `1.5px solid ${autostart ? "var(--color-red)" : "var(--color-border)"}`,
              cursor: autostart === null ? "default" : "pointer",
              transition: "background 0.15s ease, border-color 0.15s ease",
              flexShrink: 0,
            }}
          >
            <span
              style={{
                position: "absolute",
                top: 2,
                left: autostart ? 18 : 2,
                width: 18,
                height: 18,
                borderRadius: "50%",
                background: "white",
                boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
                transition: "left 0.15s ease",
              }}
            />
          </button>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Guide modal
// ---------------------------------------------------------------------------
function GuideModal({
  guide,
  onClose,
}: {
  guide: KeyMeta["guide"];
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={onClose}
    >
      <div
        className="mx-6 w-full max-w-sm rounded-xl border p-5 shadow-2xl"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4 gap-3">
          <h2 className="display text-[14px] font-semibold leading-snug"
              style={{ color: "var(--color-ink)" }}>
            {guide.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-[16px] leading-none px-1 rounded hover:bg-[var(--color-surface-2)]"
            style={{ color: "var(--color-ink-mute)" }}
          >
            ×
          </button>
        </div>

        <ol className="space-y-2.5">
          {guide.steps.map((step, i) => (
            <li key={i} className="flex gap-3">
              <span
                className="shrink-0 w-5 h-5 rounded-full text-[10px] font-semibold flex items-center justify-center mt-0.5"
                style={{
                  background: "color-mix(in srgb, var(--color-red) 15%, transparent)",
                  color: "var(--color-red)",
                }}
              >
                {i + 1}
              </span>
              <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-ink-mute)" }}>
                {step}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// API Keys tab
// ---------------------------------------------------------------------------
function ApiTab() {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [statuses, setStatuses] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const [activeGuide, setActiveGuide] = useState<KeyMeta["guide"] | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch(`${API}/settings`)
      .then((r) => r.json())
      .then((data: { keys: KeyStatus[] }) => {
        const map: Record<string, boolean> = {};
        data.keys.forEach((k) => { map[k.key] = k.set; });
        setStatuses(map);
      })
      .catch(() => {});
  }, []);

  const hasChanges = Object.values(drafts).some((v) => v.trim() !== "");

  const onSave = async () => {
    const payload: Record<string, string> = {};
    for (const [k, v] of Object.entries(drafts)) {
      if (v.trim()) payload[k] = v.trim();
    }
    if (!Object.keys(payload).length) return;

    setSaving(true);
    setSaveError(null);
    setSaved(false);

    try {
      const res = await fetch(`${API}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys: payload }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      const data: { keys: KeyStatus[]; restart_required: boolean } = await res.json();
      const map: Record<string, boolean> = {};
      data.keys.forEach((k) => { map[k.key] = k.set; });
      setStatuses(map);
      setDrafts({});
      setSaved(true);
      setRestartRequired(data.restart_required);
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaved(false), 3500);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-6 py-5 max-w-xl space-y-4">
      {activeGuide && (
        <GuideModal guide={activeGuide} onClose={() => setActiveGuide(null)} />
      )}

      {KEY_GROUPS.map((group) => (
        <section key={group.title} className="card p-4 space-y-4">
          <div>
            <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-0.5"
                style={{ color: "var(--color-ink-mute)" }}>
              {group.title}
            </h3>
            <p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
              {group.description}
            </p>
          </div>

          {group.keys.map((meta) => {
            const isSet = statuses[meta.key] ?? false;
            const draft = drafts[meta.key] ?? "";
            const isRevealed = revealed[meta.key] ?? false;

            return (
              <div key={meta.key} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <label className="text-[11px] uppercase tracking-wider truncate"
                           style={{ color: "var(--color-ink-mute)" }}>
                      {meta.label}
                    </label>
                    <button
                      type="button"
                      onClick={() => setActiveGuide(meta.guide)}
                      title="How to get this key"
                      className="shrink-0 w-4 h-4 rounded-full text-[10px] font-semibold flex items-center justify-center transition-colors hover:opacity-80"
                      style={{
                        background: "color-mix(in srgb, var(--color-red) 15%, transparent)",
                        color: "var(--color-red)",
                      }}
                    >
                      ?
                    </button>
                  </div>
                  <span
                    className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded"
                    style={{
                      background: isSet
                        ? "color-mix(in srgb, var(--color-red) 12%, transparent)"
                        : "var(--color-surface-2)",
                      color: isSet ? "var(--color-red)" : "var(--color-ink-faint)",
                    }}
                  >
                    {isSet ? "✓ set" : "not set"}
                  </span>
                </div>

                <div className="relative">
                  <input
                    type={meta.secret && !isRevealed ? "password" : "text"}
                    className="input w-full font-mono text-[12px]"
                    style={{ paddingRight: meta.secret ? "2.5rem" : undefined }}
                    placeholder={isSet ? "leave blank to keep current" : meta.placeholder}
                    value={draft}
                    onChange={(e) => setDrafts((d) => ({ ...d, [meta.key]: e.target.value }))}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  {meta.secret && (
                    <button
                      type="button"
                      onClick={() => setRevealed((r) => ({ ...r, [meta.key]: !r[meta.key] }))}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px]"
                      style={{ color: "var(--color-ink-faint)" }}
                      tabIndex={-1}
                    >
                      {isRevealed ? "hide" : "show"}
                    </button>
                  )}
                </div>

                <p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                  {meta.hint}
                </p>
              </div>
            );
          })}
        </section>
      ))}

      {/* Save bar */}
      <div className="flex items-center gap-3 pb-2">
        <button
          type="button"
          className="btn-primary text-[12px] px-4 py-1.5 rounded-lg disabled:opacity-40"
          disabled={!hasChanges || saving}
          onClick={() => void onSave()}
        >
          {saving ? "Saving…" : "Save"}
        </button>

        {saved && (
          <span className="text-[12px]" style={{ color: "var(--color-red)" }}>
            Saved.{restartRequired ? " Restart Irma to apply." : ""}
          </span>
        )}
        {saveError && (
          <span className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
            {saveError}
          </span>
        )}
      </div>
    </div>
  );
}
