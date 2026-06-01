/**
 * Step 2 — AI model
 * User either provides an Anthropic API key (saved via POST /api/v1/settings)
 * or opts for Ollama local inference (skip key entirely).
 */
import { useState } from "react";
import { GuideModal } from "../../settings/GuideModal";
import type { Guide } from "../../settings/GuideModal";
import { IRMA_API_BASE } from "../../../lib/api";

const API = `${IRMA_API_BASE}/api/v1`;

const ANTHROPIC_GUIDE: Guide = {
	title: "Get your Anthropic API Key",
	steps: [
		"Go to console.anthropic.com and sign in (or create a free account).",
		'Open the "API Keys" page from the left sidebar.',
		'Click "Create Key", give it a name (e.g. "Irma"), and confirm.',
		"Copy the key — it starts with sk-ant-. You won't be able to see it again.",
		"Paste it into the field and click Save.",
	],
};

export type AiMode = "claude" | "ollama";

export interface AiDraft {
	mode: AiMode;
	apiKey: string;
}

export function AiStep({
	draft,
	onChange,
	onKeySaved,
}: {
	draft: AiDraft;
	onChange: (d: AiDraft) => void;
	/** Called after the key is successfully persisted to .env */
	onKeySaved: (restartRequired: boolean) => void;
}) {
	const [showGuide, setShowGuide] = useState(false);
	const [revealed, setRevealed] = useState(false);
	const [saving, setSaving] = useState(false);
	const [saved, setSaved] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);

	const saveKey = async () => {
		const key = draft.apiKey.trim();
		if (!key) return;
		setSaving(true);
		setSaveError(null);
		setSaved(false);
		try {
			const res = await fetch(`${API}/settings`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ keys: { ANTHROPIC_API_KEY: key } }),
			});
			if (!res.ok) {
				const err: unknown = await res.json().catch(() => ({}));
				const detail =
					typeof err === "object" &&
					err !== null &&
					"detail" in err &&
					typeof (err as { detail?: unknown }).detail === "string"
						? (err as { detail: string }).detail
						: `HTTP ${res.status}`;
				throw new Error(detail);
			}
			const data: { restart_required: boolean } = await res.json();
			setSaved(true);
			onKeySaved(data.restart_required);
		} catch (e) {
			setSaveError(e instanceof Error ? e.message : "Save failed.");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="space-y-5">
			{showGuide && (
				<GuideModal guide={ANTHROPIC_GUIDE} onClose={() => setShowGuide(false)} />
			)}

			<div>
				<h2
					className="display text-[22px] font-semibold mb-1.5"
					style={{ color: "var(--color-ink)" }}>
					Choose your AI
				</h2>
				<p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
					Irma needs a language model to synthesise briefs and chat with you.
				</p>
			</div>

			{/* Mode picker */}
			<div className="space-y-2">
				{(["claude", "ollama"] as AiMode[]).map((m) => {
					const active = draft.mode === m;
					return (
						<button
							key={m}
							type="button"
							onClick={() => onChange({ ...draft, mode: m })}
							className="w-full text-left rounded-lg p-3.5 transition-colors"
							style={{
								background: active
									? "var(--color-surface-2)"
									: "var(--color-bg)",
								border: `1px solid ${active ? "var(--color-red)" : "var(--color-border)"}`,
							}}>
							<div className="flex items-center justify-between">
								<span
									className="text-[13px] font-semibold"
									style={{ color: "var(--color-ink)" }}>
									{m === "claude"
										? "Claude (Anthropic API)"
										: "Local model (Ollama)"}
								</span>
								<span
									className="inline-block w-3 h-3 rounded-full shrink-0"
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
								{m === "claude"
									? "Best quality. Requires an Anthropic account (free tier available)."
									: "Runs fully offline. Configure Ollama in Settings → Local Models later."}
							</p>
						</button>
					);
				})}
			</div>

			{/* Claude key input — shown only in claude mode */}
			{draft.mode === "claude" && (
				<section className="card p-4 space-y-3">
					<div className="flex items-center gap-1.5">
						<label
							htmlFor="ai-api-key"
							className="text-[11px] font-semibold uppercase tracking-wider"
							style={{ color: "var(--color-ink-mute)" }}>
							Anthropic API Key
						</label>
						<button
							type="button"
							onClick={() => setShowGuide(true)}
							title="How to get an API key"
							aria-label="How to get an Anthropic API key"
							className="w-4 h-4 rounded-full text-[10px] font-semibold flex items-center justify-center transition-colors hover:opacity-80"
							style={{
								background:
									"color-mix(in srgb, var(--color-red) 15%, transparent)",
								color: "var(--color-red)",
							}}>
							?
						</button>
					</div>

					<div className="relative">
						<input
							id="ai-api-key"
							type={revealed ? "text" : "password"}
							className="input font-mono text-[12px]"
							style={{ paddingRight: "3rem" }}
							placeholder="sk-ant-…"
							value={draft.apiKey}
							onChange={(e) =>
								onChange({ ...draft, apiKey: e.target.value })
							}
							autoComplete="off"
							spellCheck={false}
						/>
						<button
							type="button"
							onClick={() => setRevealed((v) => !v)}
							tabIndex={-1}
							className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px]"
							style={{ color: "var(--color-ink-faint)" }}>
							{revealed ? "hide" : "show"}
						</button>
					</div>

					<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
						Saved to .env — a backend restart will apply it.
					</p>

					<div className="flex items-center gap-3">
						<button
							type="button"
							disabled={!draft.apiKey.trim() || saving}
							onClick={() => void saveKey()}
							className="btn-red text-[12px] px-3 py-1.5 rounded-lg disabled:opacity-40">
							{saving ? "Saving…" : "Save key"}
						</button>
						{saved && (
							<span
								className="text-[12px]"
								style={{ color: "var(--color-moss)" }}>
								✓ Saved
							</span>
						)}
						{saveError && (
							<span
								className="text-[12px]"
								style={{ color: "var(--color-red)" }}>
								{saveError}
							</span>
						)}
					</div>
				</section>
			)}

			{draft.mode === "ollama" && (
				<section
					className="card p-4 space-y-1"
					style={{
						background:
							"color-mix(in srgb, var(--color-amber) 8%, var(--color-surface))",
						borderColor:
							"color-mix(in srgb, var(--color-amber) 30%, transparent)",
					}}>
					<p
						className="text-[12px] font-semibold"
						style={{ color: "var(--color-amber)" }}>
						Ollama mode
					</p>
					<p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
						Make sure Ollama is running and at least one model is pulled before
						you open Irma's chat. You can configure the model and base URL in
						Settings → Local Models after setup.
					</p>
				</section>
			)}
		</div>
	);
}
