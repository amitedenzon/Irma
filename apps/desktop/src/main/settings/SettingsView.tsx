import { useEffect, useRef, useState } from "react";
import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";
import { invoke } from "@tauri-apps/api/core";
import { exit } from "@tauri-apps/plugin-process";
import { fetchLocalModels } from "../../lib/api";
import type { LocalModel } from "../../lib/api";
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
type SettingsTab = "general" | "local" | "api";

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
						'You don\'t need to copy anything — come back here and the field will show "✓ set".',
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
		value: "left-of-dock",
		label: "Left of Dock",
		hint: "Irma roams the bottom-left, beside the Dock.",
	},
	{
		value: "on-dock",
		label: "On the Dock",
		hint: "Irma sits on top of the Dock strip.",
	},
	{
		value: "right-of-dock",
		label: "Right of Dock",
		hint: "Irma roams the bottom-right, beside the Dock.",
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
				style={{ borderColor: "var(--color-border)" }}>
				{(["general", "local", "api"] as SettingsTab[]).map((t) => {
					const active = activeTab === t;
					const label =
						t === "api"
							? "API Keys"
							: t === "local"
								? "Local Models"
								: "General";
					return (
						<button
							key={t}
							type="button"
							onClick={() => setActiveTab(t)}
							className="px-3 py-1.5 text-[12px] font-medium transition-colors"
							style={{
								color: active
									? "var(--color-red)"
									: "var(--color-ink-mute)",
								borderBottom: `2px solid ${active ? "var(--color-red)" : "transparent"}`,
								marginBottom: -1,
							}}>
							{label}
						</button>
					);
				})}
			</div>

			{/* Content */}
			<div className="flex-1 overflow-y-auto flex flex-col items-center">
				<div className="w-full max-w-lg px-6 py-5">
					{activeTab === "general" && <GeneralTab />}
					{activeTab === "local" && <LocalTab />}
					{activeTab === "api" && <ApiTab />}
				</div>
			</div>
		</div>
	);
}

// ---------------------------------------------------------------------------
// Restart button — restarts only the FastAPI backend (not Tauri)
// ---------------------------------------------------------------------------
function RestartButton() {
	const [state, setState] = useState<"idle" | "restarting" | "done">("idle");

	const restart = async () => {
		setState("restarting");
		try {
			await fetch(`${API}/settings/restart-backend`, { method: "POST" });
		} catch {
			/* expected — process is replacing itself */
		}
		// Poll until the backend is back up
		for (let i = 0; i < 30; i++) {
			await new Promise((r) => setTimeout(r, 600));
			try {
				const res = await fetch(`${API}/state`, {
					signal: AbortSignal.timeout(1000),
				});
				if (res.ok) {
					setState("done");
					setTimeout(() => setState("idle"), 2500);
					return;
				}
			} catch {
				/* still starting */
			}
		}
		setState("idle"); // timed out
	};

	return (
		<button
			type="button"
			disabled={state === "restarting"}
			onClick={() => void restart()}
			className="shrink-0 text-[12px] font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60"
			style={{
				background:
					state === "done"
						? "color-mix(in srgb, var(--color-moss) 15%, transparent)"
						: "var(--color-surface-2)",
				color:
					state === "done"
						? "var(--color-moss)"
						: "var(--color-ink-mute)",
				border: `1px solid ${state === "done" ? "color-mix(in srgb, var(--color-moss) 35%, transparent)" : "var(--color-border)"}`,
			}}>
			{state === "restarting"
				? "Restarting…"
				: state === "done"
					? "✓ Applied"
					: "Restart"}
		</button>
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
	const [loadingScreen, setLoadingScreen] = useState<boolean>(
		() => localStorage.getItem("irma.settings.loadingScreen") !== "false",
	);

	useEffect(() => {
		isEnabled()
			.then((v) => setAutostart(v))
			.catch(() => setAutostart(false));
	}, []);

	const onLoadingScreenChange = (checked: boolean) => {
		setLoadingScreen(checked);
		localStorage.setItem(
			"irma.settings.loadingScreen",
			checked ? "true" : "false",
		);
	};

	const onAutostartChange = async (checked: boolean) => {
		try {
			if (checked) await enable();
			else await disable();
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
		<div className="space-y-4 w-full">
			{/* Companion */}
			<section className="card p-4 space-y-3">
				<div>
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
						style={{ color: "var(--color-ink-mute)" }}>
						Companion
					</h3>
					<p
						className="text-[12px]"
						style={{ color: "var(--color-ink-faint)" }}>
						Choose which character lives beside your Dock.
					</p>
				</div>
				<div>
					<label
						className="block text-[11px] uppercase tracking-wider mb-1"
						style={{ color: "var(--color-ink-mute)" }}>
						Character
					</label>
					<select
						className="input"
						value={companionId}
						onChange={(e) => onCompanionChange(e.target.value)}>
						{COMPANIONS.map((c) => (
							<option key={c.id} value={c.id}>
								{c.name}
							</option>
						))}
					</select>
				</div>
			</section>

			{/* Placement */}
			<section className="card p-4 space-y-3">
				<div>
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider mb-1"
						style={{ color: "var(--color-ink-mute)" }}>
						Placement
					</h3>
					<p
						className="text-[12px]"
						style={{ color: "var(--color-ink-faint)" }}>
						Where Irma appears. Takes effect on next restart.
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
									border: `1px solid ${active ? "var(--color-red)" : "var(--color-border)"}`,
								}}>
								<div className="flex items-center justify-between">
									<span
										className="text-[13px] font-medium"
										style={{ color: "var(--color-ink)" }}>
										{opt.label}
									</span>
									<span
										className="inline-block w-3 h-3 rounded-full"
										style={{
											border: `2px solid ${active ? "var(--color-red)" : "var(--color-ink-faint)"}`,
											background: active
												? "var(--color-red)"
												: "transparent",
										}}
									/>
								</div>
								<p
									className="text-[12px] mt-0.5"
									style={{ color: "var(--color-ink-faint)" }}>
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
						<p
							className="text-[13px] font-medium"
							style={{ color: "var(--color-ink)" }}>
							Launch at startup
						</p>
						<p
							className="text-[12px] mt-0.5"
							style={{ color: "var(--color-ink-faint)" }}>
							Start Irma automatically when you log in to macOS.
						</p>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={autostart ?? false}
						disabled={autostart === null}
						onClick={() =>
							void onAutostartChange(!(autostart ?? false))
						}
						className="shrink-0 disabled:opacity-40"
						style={{
							position: "relative",
							width: 44,
							height: 26,
							borderRadius: 13,
							background: autostart
								? "var(--color-red)"
								: "var(--color-surface-2)",
							border: `1.5px solid ${autostart ? "var(--color-red)" : "var(--color-border)"}`,
							cursor: autostart === null ? "default" : "pointer",
							transition:
								"background 0.15s ease, border-color 0.15s ease",
							flexShrink: 0,
						}}>
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

			{/* Loading screen */}
			<section className="card p-4">
				<div className="flex items-center justify-between gap-4">
					<div className="min-w-0">
						<p
							className="text-[13px] font-medium"
							style={{ color: "var(--color-ink)" }}>
							Show loading screen
						</p>
						<p
							className="text-[12px] mt-0.5"
							style={{ color: "var(--color-ink-faint)" }}>
							Display a progress screen while Irma's backend is
							starting up.
						</p>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={loadingScreen}
						onClick={() => onLoadingScreenChange(!loadingScreen)}
						className="shrink-0"
						style={{
							position: "relative",
							width: 44,
							height: 26,
							borderRadius: 13,
							background: loadingScreen
								? "var(--color-red)"
								: "var(--color-surface-2)",
							border: `1.5px solid ${loadingScreen ? "var(--color-red)" : "var(--color-border)"}`,
							cursor: "pointer",
							transition:
								"background 0.15s ease, border-color 0.15s ease",
							flexShrink: 0,
						}}>
						<span
							style={{
								position: "absolute",
								top: 2,
								left: loadingScreen ? 18 : 2,
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

			{/* Restart backend */}
			<section className="card p-4">
				<div className="flex items-center justify-between gap-4">
					<div className="min-w-0">
						<p
							className="text-[13px] font-medium"
							style={{ color: "var(--color-ink)" }}>
							Apply changes
						</p>
						<p
							className="text-[12px] mt-0.5"
							style={{ color: "var(--color-ink-faint)" }}>
							Restarts the backend to pick up new API keys or
							Ollama settings.
						</p>
					</div>
					<RestartButton />
				</div>
			</section>

			{/* Quit */}
			<section className="card p-4">
				<div className="flex items-center justify-between gap-4">
					<div className="min-w-0">
						<p
							className="text-[13px] font-medium"
							style={{ color: "var(--color-ink)" }}>
							Quit Irma
						</p>
						<p
							className="text-[12px] mt-0.5"
							style={{ color: "var(--color-ink-faint)" }}>
							Close the companion and exit the app.
						</p>
					</div>
					<button
						type="button"
						onClick={() => void exit(0)}
						className="shrink-0 text-[12px] font-medium px-3 py-1.5 rounded-lg transition-colors"
						style={{
							background: "color-mix(in srgb, var(--color-red) 12%, transparent)",
							color: "var(--color-red)",
							border: "1px solid color-mix(in srgb, var(--color-red) 30%, transparent)",
						}}>
						Quit
					</button>
				</div>
			</section>
		</div>
	);
}

// ---------------------------------------------------------------------------
// Local Models tab
// ---------------------------------------------------------------------------

const PROFICIENCY_COLORS: Record<string, string> = {
	chat: "var(--color-moss)",
	coding: "var(--color-amber)",
	vision: "#8b5cf6",
	math: "#06b6d4",
	embeddings: "var(--color-ink-faint)",
};

function LocalTab() {
	const [ollamaUrl, setOllamaUrl] = useState<string>(
		"http://127.0.0.1:11434",
	);
	const [modelsPath, setModelsPath] = useState<string>(
		() => localStorage.getItem("irma.settings.modelsPath") ?? "",
	);
	const [models, setModels] = useState<LocalModel[]>([]);
	const [reachable, setReachable] = useState<boolean | null>(null);
	const [scanning, setScanning] = useState(false);
	const [saving, setSaving] = useState(false);
	const [saved, setSaved] = useState(false);

	// Load current Ollama URL from .env status on mount
	useEffect(() => {
		fetch(`${API}/settings`)
			.then((r) => r.json())
			.then((d: { keys: { key: string; set: boolean }[] }) => {
				// If server has it set, show a placeholder — we can't read the value
				const has = d.keys.find(
					(k) => k.key === "OLLAMA_BASE_URL",
				)?.set;
				if (!has) setOllamaUrl("http://127.0.0.1:11434");
			})
			.catch(() => {});
	}, []);

	const scan = async (path?: string) => {
		setScanning(true);
		try {
			const res = await fetchLocalModels(
				path ?? (modelsPath || undefined),
			);
			setModels(res.models);
			setReachable(res.ollama_reachable);
		} catch {
			setReachable(false);
		} finally {
			setScanning(false);
		}
	};

	// Auto-scan on mount
	useEffect(() => {
		void scan();
	}, []); // eslint-disable-line react-hooks/exhaustive-deps

	const browseFolder = async () => {
		try {
			const selected = await invoke<string | null>("browse_folder");
			if (!selected) return; // User cancelled
			setModelsPath(selected);
			localStorage.setItem("irma.settings.modelsPath", selected);
			void scan(selected);
		} catch (err) {
			console.error("[settings] browse failed:", err);
		}
	};

	const setDefault = async (model: string) => {
		setSaving(true);
		try {
			await fetch(`${API}/settings`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ keys: { OLLAMA_MODEL: model } }),
			});
			setSaved(true);
			setTimeout(() => setSaved(false), 2500);
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="space-y-4 w-full">
			{/* Ollama server */}
			<section className="card p-4 space-y-3">
				<div className="flex items-center gap-2">
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Ollama Server
					</h3>
					<span
						className="flex items-center gap-1.5 text-[10px] font-medium px-2 py-0.5 rounded-full"
						style={{
							background:
								reachable === true
									? "color-mix(in srgb, var(--color-moss) 15%, transparent)"
									: reachable === false
										? "color-mix(in srgb, var(--color-red) 12%, transparent)"
										: "var(--color-surface-2)",
							color:
								reachable === true
									? "var(--color-moss)"
									: reachable === false
										? "var(--color-red)"
										: "var(--color-ink-faint)",
						}}>
						<span
							className="w-1.5 h-1.5 rounded-full shrink-0"
							style={{
								background:
									reachable === true
										? "var(--color-moss)"
										: reachable === false
											? "var(--color-red)"
											: "var(--color-ink-faint)",
							}}
						/>
						{reachable === true
							? "Connected"
							: reachable === false
								? "Unreachable"
								: "Checking…"}
					</span>
				</div>
				<div>
					<label
						className="block text-[11px] uppercase tracking-wider mb-1"
						style={{ color: "var(--color-ink-mute)" }}>
						Base URL
					</label>
					<input
						type="text"
						className="input w-full font-mono text-[12px]"
						value={ollamaUrl}
						onChange={(e) => setOllamaUrl(e.target.value)}
						placeholder="http://127.0.0.1:11434"
					/>
					<p
						className="text-[11px] mt-1"
						style={{ color: "var(--color-ink-faint)" }}>
						Saved to .env — restart Irma to apply.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<button
						type="button"
						className="btn-primary text-[12px] px-3 py-1.5 rounded-lg disabled:opacity-40"
						disabled={saving}
						onClick={async () => {
							setSaving(true);
							try {
								await fetch(`${API}/settings`, {
									method: "POST",
									headers: {
										"Content-Type": "application/json",
									},
									body: JSON.stringify({
										keys: { OLLAMA_BASE_URL: ollamaUrl },
									}),
								});
								void scan();
								setSaved(true);
								setTimeout(() => setSaved(false), 2500);
							} finally {
								setSaving(false);
							}
						}}>
						{saving ? "Saving…" : "Save & Test"}
					</button>
					{saved && (
						<span
							className="text-[12px]"
							style={{ color: "var(--color-moss)" }}>
							Saved
						</span>
					)}
				</div>
			</section>

			{/* Models folder */}
			<section className="card p-4 space-y-3">
				<h3
					className="display text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Models Folder
				</h3>
				<p
					className="text-[12px]"
					style={{ color: "var(--color-ink-faint)" }}>
					Optional — point to a folder of .gguf files to include them
					alongside Ollama models.
				</p>
				<div className="flex items-center gap-2">
					<input
						type="text"
						className="input flex-1 text-[12px] font-mono"
						value={modelsPath}
						readOnly
						placeholder="No folder selected"
					/>
					<button
						type="button"
						className="btn-primary text-[12px] px-3 py-1.5 rounded-lg shrink-0"
						onClick={() => void browseFolder()}>
						Browse…
					</button>
				</div>
				<button
					type="button"
					className="text-[12px] underline disabled:opacity-40"
					style={{ color: "var(--color-ink-mute)" }}
					disabled={scanning}
					onClick={() => void scan()}>
					{scanning ? "Scanning…" : "↺ Refresh"}
				</button>
			</section>

			{/* Detected models */}
			{models.length > 0 && (
				<section className="card p-4 space-y-3">
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Detected Models ({models.length})
					</h3>
					<div className="space-y-2">
						{models.map((m) => (
							<div
								key={m.name}
								className="flex items-start justify-between gap-3 rounded-lg p-3"
								style={{
									background: "var(--color-bg)",
									border: "1px solid var(--color-border)",
								}}>
								<div className="min-w-0 space-y-1.5">
									<p
										className="text-[13px] font-medium truncate"
										style={{ color: "var(--color-ink)" }}>
										{m.display_name}
									</p>
									<div className="flex flex-wrap gap-1.5 items-center">
										{/* Size */}
										<span
											className="text-[10px] px-1.5 py-0.5 rounded font-medium"
											style={{
												background:
													"var(--color-surface-2)",
												color: "var(--color-ink-mute)",
											}}>
											{m.size_label}
										</span>
										{/* Quantization */}
										{m.quantization && (
											<span
												className="text-[10px] px-1.5 py-0.5 rounded font-medium font-mono"
												style={{
													background:
														"var(--color-surface-2)",
													color: "var(--color-ink-mute)",
												}}>
												{m.quantization}
											</span>
										)}
										{/* Proficiency chips */}
										{m.proficiency.map((p) => (
											<span
												key={p}
												className="text-[10px] px-1.5 py-0.5 rounded font-medium"
												style={{
													background: `color-mix(in srgb, ${PROFICIENCY_COLORS[p] ?? "var(--color-ink-faint)"} 15%, transparent)`,
													color:
														PROFICIENCY_COLORS[p] ??
														"var(--color-ink-faint)",
												}}>
												{p}
											</span>
										))}
										{/* Source */}
										<span
											className="text-[10px]"
											style={{
												color: "var(--color-ink-faint)",
											}}>
											{m.source}
										</span>
									</div>
								</div>
								<button
									type="button"
									className="shrink-0 text-[11px] px-2 py-1 rounded-md transition-colors"
									style={{
										background: "var(--color-surface-2)",
										color: "var(--color-ink-mute)",
									}}
									onClick={() => void setDefault(m.name)}>
									Set default
								</button>
							</div>
						))}
					</div>
				</section>
			)}

			{models.length === 0 && !scanning && reachable === false && (
				<section className="card p-4 space-y-1.5">
					<p
						className="text-[13px] font-medium"
						style={{ color: "var(--color-ink)" }}>
						Ollama isn't running
					</p>
					<p
						className="text-[12px]"
						style={{ color: "var(--color-ink-faint)" }}>
						Start it from the terminal or the Ollama app, then click
						↺ Refresh above.
					</p>
					<code
						className="block text-[11px] font-mono px-2 py-1 rounded mt-1"
						style={{
							background: "var(--color-surface-2)",
							color: "var(--color-ink-mute)",
						}}>
						ollama serve
					</code>
					<p
						className="text-[11px]"
						style={{ color: "var(--color-ink-faint)" }}>
						If your models are on an external drive, make sure it's
						mounted and the symlink at{" "}
						<code className="font-mono">~/.ollama/models</code>{" "}
						resolves before starting.
					</p>
				</section>
			)}
			{models.length === 0 && !scanning && reachable === true && (
				<section className="card p-4 space-y-1.5">
					<p
						className="text-[13px] font-medium"
						style={{ color: "var(--color-ink)" }}>
						No models installed
					</p>
					<p
						className="text-[12px]"
						style={{ color: "var(--color-ink-faint)" }}>
						Pull a model from the terminal to get started.
					</p>
					<code
						className="block text-[11px] font-mono px-2 py-1 rounded mt-1"
						style={{
							background: "var(--color-surface-2)",
							color: "var(--color-ink-mute)",
						}}>
						ollama pull llama3.2
					</code>
				</section>
			)}
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
			onClick={onClose}>
			<div
				className="mx-6 w-full max-w-sm rounded-xl border p-5 shadow-2xl"
				style={{
					background: "var(--color-surface)",
					borderColor: "var(--color-border)",
				}}
				onClick={(e) => e.stopPropagation()}>
				<div className="flex items-start justify-between mb-4 gap-3">
					<h2
						className="display text-[14px] font-semibold leading-snug"
						style={{ color: "var(--color-ink)" }}>
						{guide.title}
					</h2>
					<button
						type="button"
						onClick={onClose}
						className="shrink-0 text-[16px] leading-none px-1 rounded hover:bg-[var(--color-surface-2)]"
						style={{ color: "var(--color-ink-mute)" }}>
						×
					</button>
				</div>

				<ol className="space-y-2.5">
					{guide.steps.map((step, i) => (
						<li key={i} className="flex gap-3">
							<span
								className="shrink-0 w-5 h-5 rounded-full text-[10px] font-semibold flex items-center justify-center mt-0.5"
								style={{
									background:
										"color-mix(in srgb, var(--color-red) 15%, transparent)",
									color: "var(--color-red)",
								}}>
								{i + 1}
							</span>
							<p
								className="text-[12px] leading-relaxed"
								style={{ color: "var(--color-ink-mute)" }}>
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
// ---------------------------------------------------------------------------
// Reminders card (inside ApiTab)
// ---------------------------------------------------------------------------
interface RemindersStatus {
	reminders_linked: boolean;
	reminders_last_sync_at: string | null;
	reminders_last_sync_error: string | null;
}

function RemindersCard() {
	const [status, setStatus] = useState<RemindersStatus | null>(null);
	const [syncing, setSyncing] = useState(false);
	const [linking, setLinking] = useState(false);
	const [syncResult, setSyncResult] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	const fetchStatus = () => {
		fetch(`${API}/integrations/google/status`)
			.then((r) => r.json())
			.then((d: RemindersStatus) => setStatus(d))
			.catch(() => {});
	};

	useEffect(() => { fetchStatus(); }, []);

	const handleLink = async () => {
		setLinking(true); setError(null); setSyncResult(null);
		try {
			const res = await fetch(`${API}/integrations/reminders/link`, { method: "POST" });
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error((d as { detail?: string }).detail ?? `HTTP ${res.status}`);
			}
			fetchStatus();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Link failed.");
		} finally { setLinking(false); }
	};

	const handleUnlink = async () => {
		setLinking(true); setError(null); setSyncResult(null);
		try {
			await fetch(`${API}/integrations/reminders/link`, { method: "DELETE" });
			fetchStatus();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Unlink failed.");
		} finally { setLinking(false); }
	};

	const handleSync = async () => {
		setSyncing(true); setError(null); setSyncResult(null);
		try {
			const res = await fetch(`${API}/integrations/reminders/sync`, { method: "POST" });
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error((d as { detail?: string }).detail ?? `HTTP ${res.status}`);
			}
			const stats = await res.json() as Record<string, number>;
			const total = Object.values(stats).reduce((a, b) => a + b, 0);
			setSyncResult(total === 0 ? "Up to date." : `${total} change${total !== 1 ? "s" : ""} applied.`);
			fetchStatus();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Sync failed.");
		} finally { setSyncing(false); }
	};

	const linked = status?.reminders_linked ?? false;
	const lastSync = status?.reminders_last_sync_at
		? new Date(status.reminders_last_sync_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
		: null;

	return (
		<section className="card p-4 space-y-3">
			<div>
				<h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-0.5"
					style={{ color: "var(--color-ink-mute)" }}>
					Apple Reminders
				</h3>
				<p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
					Mirror projects + tasks to macOS Reminders for phone access.
				</p>
			</div>

			<div className="flex items-center justify-between">
				<div className="flex items-center gap-2">
					<span className="w-2 h-2 rounded-full" style={{
						background: linked ? "var(--color-red)" : "var(--color-ink-faint)",
						opacity: linked ? 1 : 0.4,
					}} />
					<span className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
						{linked ? "Linked" : "Not linked"}
					</span>
					{lastSync && (
						<span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
							· last sync {lastSync}
						</span>
					)}
				</div>
				<div className="flex items-center gap-2">
					{linked && (
						<button type="button"
							className="btn-primary text-[11px] px-3 py-1 rounded-lg disabled:opacity-40"
							disabled={syncing}
							onClick={() => void handleSync()}>
							{syncing ? "Syncing…" : "Sync now"}
						</button>
					)}
					<button type="button"
						className="text-[11px] px-3 py-1 rounded-lg transition-colors disabled:opacity-40"
						style={{
							background: "var(--color-surface-2)",
							color: "var(--color-ink-mute)",
						}}
						disabled={linking}
						onClick={() => void (linked ? handleUnlink() : handleLink())}>
						{linking ? "…" : linked ? "Unlink" : "Link"}
					</button>
				</div>
			</div>

			{(error || syncResult || status?.reminders_last_sync_error) && (
				<p className="text-[11px]" style={{
					color: error || status?.reminders_last_sync_error
						? "var(--color-ink-faint)"
						: "var(--color-red)",
				}}>
					{error ?? syncResult ?? status?.reminders_last_sync_error}
				</p>
			)}
		</section>
	);
}

function ApiTab() {
	const [drafts, setDrafts] = useState<Record<string, string>>({});
	const [statuses, setStatuses] = useState<Record<string, boolean>>({});
	const [revealed, setRevealed] = useState<Record<string, boolean>>({});
	const [saving, setSaving] = useState(false);
	const [saved, setSaved] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);
	const [restartRequired, setRestartRequired] = useState(false);
	const [activeGuide, setActiveGuide] = useState<KeyMeta["guide"] | null>(
		null,
	);
	const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

	useEffect(() => {
		fetch(`${API}/settings`)
			.then((r) => r.json())
			.then((data: { keys: KeyStatus[] }) => {
				const map: Record<string, boolean> = {};
				data.keys.forEach((k) => {
					map[k.key] = k.set;
				});
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
				throw new Error(
					(err as { detail?: string }).detail ?? `HTTP ${res.status}`,
				);
			}
			const data: { keys: KeyStatus[]; restart_required: boolean } =
				await res.json();
			const map: Record<string, boolean> = {};
			data.keys.forEach((k) => {
				map[k.key] = k.set;
			});
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
		<div className="space-y-4 w-full">
			{activeGuide && (
				<GuideModal
					guide={activeGuide}
					onClose={() => setActiveGuide(null)}
				/>
			)}

			{KEY_GROUPS.map((group) => (
				<section key={group.title} className="card p-4 space-y-4">
					<div>
						<h3
							className="display text-[11px] font-semibold uppercase tracking-wider mb-0.5"
							style={{ color: "var(--color-ink-mute)" }}>
							{group.title}
						</h3>
						<p
							className="text-[12px]"
							style={{ color: "var(--color-ink-faint)" }}>
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
										<label
											className="text-[11px] uppercase tracking-wider truncate"
											style={{
												color: "var(--color-ink-mute)",
											}}>
											{meta.label}
										</label>
										<button
											type="button"
											onClick={() =>
												setActiveGuide(meta.guide)
											}
											title="How to get this key"
											className="shrink-0 w-4 h-4 rounded-full text-[10px] font-semibold flex items-center justify-center transition-colors hover:opacity-80"
											style={{
												background:
													"color-mix(in srgb, var(--color-red) 15%, transparent)",
												color: "var(--color-red)",
											}}>
											?
										</button>
									</div>
									<span
										className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded"
										style={{
											background: isSet
												? "color-mix(in srgb, var(--color-red) 12%, transparent)"
												: "var(--color-surface-2)",
											color: isSet
												? "var(--color-red)"
												: "var(--color-ink-faint)",
										}}>
										{isSet ? "✓ set" : "not set"}
									</span>
								</div>

								<div className="relative">
									<input
										type={
											meta.secret && !isRevealed
												? "password"
												: "text"
										}
										className="input w-full font-mono text-[12px]"
										style={{
											paddingRight: meta.secret
												? "2.5rem"
												: undefined,
										}}
										placeholder={
											isSet
												? "leave blank to keep current"
												: meta.placeholder
										}
										value={draft}
										onChange={(e) =>
											setDrafts((d) => ({
												...d,
												[meta.key]: e.target.value,
											}))
										}
										autoComplete="off"
										spellCheck={false}
									/>
									{meta.secret && (
										<button
											type="button"
											onClick={() =>
												setRevealed((r) => ({
													...r,
													[meta.key]: !r[meta.key],
												}))
											}
											className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px]"
											style={{
												color: "var(--color-ink-faint)",
											}}
											tabIndex={-1}>
											{isRevealed ? "hide" : "show"}
										</button>
									)}
								</div>

								<p
									className="text-[11px]"
									style={{ color: "var(--color-ink-faint)" }}>
									{meta.hint}
								</p>
							</div>
						);
					})}
				</section>
			))}

			<RemindersCard />

			{/* Save bar */}
			<div className="flex items-center gap-3 pb-2">
				<button
					type="button"
					className="btn-primary text-[12px] px-4 py-1.5 rounded-lg disabled:opacity-40"
					disabled={!hasChanges || saving}
					onClick={() => void onSave()}>
					{saving ? "Saving…" : "Save"}
				</button>

				{saved && (
					<span
						className="text-[12px]"
						style={{ color: "var(--color-red)" }}>
						Saved.{restartRequired ? " Restart Irma to apply." : ""}
					</span>
				)}
				{saveError && (
					<span
						className="text-[12px]"
						style={{ color: "var(--color-ink-faint)" }}>
						{saveError}
					</span>
				)}
			</div>
		</div>
	);
}
