/**
 * Step 4 — Email & daily brief (skippable)
 * - Resend API key  → POST /api/v1/settings
 * - owner_email     → patchProfile (hot-reloaded, no restart needed)
 * - daily_brief_enabled toggle + brief_hour → patchProfile (hot-reloaded)
 *
 * Profile fields are persisted when the wizard advances (via the wizard
 * shell's onAdvance handler), so we only need to handle the key-save here.
 */
import { useState } from "react";
import { GuideModal } from "../../settings/GuideModal";
import type { Guide } from "../../settings/GuideModal";
import { IRMA_API_BASE } from "../../../lib/api";

const API = `${IRMA_API_BASE}/api/v1`;

const RESEND_GUIDE: Guide = {
	title: "Get your Resend API Key",
	steps: [
		"Go to resend.com and sign up for a free account.",
		'From the dashboard, open "API Keys" in the left sidebar.',
		'Click "Create API Key", name it "Irma", and confirm.',
		"Copy the key — it starts with re_.",
		"Paste it here and click Save. The free tier is enough for daily briefs.",
	],
};

const HOURS = Array.from({ length: 24 }, (_, i) => i);

function hourLabel(h: number): string {
	const amPm = h < 12 ? "AM" : "PM";
	const display = h % 12 === 0 ? 12 : h % 12;
	return `${display}:00 ${amPm}`;
}

export interface EmailDraft {
	resendKey: string;
	owner_email: string;
	daily_brief_enabled: boolean;
	brief_hour: number;
}

export function EmailStep({
	draft,
	onChange,
	onKeySaved,
}: {
	draft: EmailDraft;
	onChange: (d: EmailDraft) => void;
	/** Called after Resend key is successfully persisted */
	onKeySaved: (restartRequired: boolean) => void;
}) {
	const [showGuide, setShowGuide] = useState(false);
	const [revealed, setRevealed] = useState(false);
	const [saving, setSaving] = useState(false);
	const [saved, setSaved] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);

	const saveKey = async () => {
		const key = draft.resendKey.trim();
		if (!key) return;
		setSaving(true);
		setSaveError(null);
		setSaved(false);
		try {
			const res = await fetch(`${API}/settings`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ keys: { RESEND_API_KEY: key } }),
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
				<GuideModal guide={RESEND_GUIDE} onClose={() => setShowGuide(false)} />
			)}

			<div>
				<div className="flex items-center gap-2 mb-1.5">
					<h2
						className="display text-[22px] font-semibold"
						style={{ color: "var(--color-ink)" }}>
						Email &amp; daily brief
					</h2>
					<span
						className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
						style={{
							background:
								"color-mix(in srgb, var(--color-ink-faint) 15%, transparent)",
							color: "var(--color-ink-faint)",
						}}>
						optional
					</span>
				</div>
				<p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
					Receive your daily standup brief by email. Requires a Resend account
					(free tier is plenty). Skip if you prefer to pull briefs from the app.
				</p>
			</div>

			{/* Resend key */}
			<section className="card p-4 space-y-3">
				<div className="flex items-center gap-1.5">
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Resend API Key
					</h3>
					<button
						type="button"
						onClick={() => setShowGuide(true)}
						title="How to get a Resend API key"
						aria-label="How to get a Resend API key"
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
						id="email-resend-key"
						type={revealed ? "text" : "password"}
						className="input font-mono text-[12px]"
						style={{ paddingRight: "3rem" }}
						placeholder="re_…"
						value={draft.resendKey}
						onChange={(e) =>
							onChange({ ...draft, resendKey: e.target.value })
						}
						autoComplete="off"
						spellCheck={false}
						aria-label="Resend API key"
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

				<div className="flex items-center gap-3">
					<button
						type="button"
						disabled={!draft.resendKey.trim() || saving}
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
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Saved to .env — a backend restart will apply it.
				</p>
			</section>

			{/* Your email */}
			<div className="space-y-1">
				<label
					htmlFor="email-recipient"
					className="block text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Your email address
				</label>
				<input
					id="email-recipient"
					type="email"
					className="input"
					placeholder="you@example.com"
					value={draft.owner_email}
					onChange={(e) =>
						onChange({ ...draft, owner_email: e.target.value })
					}
				/>
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Where Irma sends the brief. Locked server-side — the LLM cannot change it.
				</p>
			</div>

			{/* Brief schedule */}
			<section className="card p-4 space-y-4">
				<h3
					className="display text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Daily brief
				</h3>

				{/* Enable toggle */}
				<div className="flex items-center justify-between gap-4">
					<div className="min-w-0">
						<p
							className="text-[13px] font-medium"
							style={{ color: "var(--color-ink)" }}>
							Enable daily brief
						</p>
						<p
							className="text-[12px] mt-0.5"
							style={{ color: "var(--color-ink-faint)" }}>
							Irma emails you a morning standup at your chosen time.
						</p>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={draft.daily_brief_enabled}
						onClick={() =>
							onChange({
								...draft,
								daily_brief_enabled: !draft.daily_brief_enabled,
							})
						}
						className="shrink-0"
						style={{
							position: "relative",
							width: 44,
							height: 26,
							borderRadius: 13,
							background: draft.daily_brief_enabled
								? "var(--color-red)"
								: "var(--color-surface-2)",
							border: `1.5px solid ${draft.daily_brief_enabled ? "var(--color-red)" : "var(--color-border)"}`,
							cursor: "pointer",
							transition:
								"background 0.15s ease, border-color 0.15s ease",
							flexShrink: 0,
						}}>
						<span
							style={{
								position: "absolute",
								top: 2,
								left: draft.daily_brief_enabled ? 18 : 2,
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

				{/* Brief hour */}
				{draft.daily_brief_enabled && (
					<div className="space-y-1">
						<label
							htmlFor="email-brief-hour"
							className="block text-[11px] uppercase tracking-wider"
							style={{ color: "var(--color-ink-mute)" }}>
							Send at
						</label>
						<select
							id="email-brief-hour"
							className="input"
							value={draft.brief_hour}
							onChange={(e) =>
								onChange({
									...draft,
									brief_hour: Number(e.target.value),
								})
							}>
							{HOURS.map((h) => (
								<option key={h} value={h}>
									{hourLabel(h)}
								</option>
							))}
						</select>
						<p
							className="text-[11px]"
							style={{ color: "var(--color-ink-faint)" }}>
							Local time — uses the timezone you set in step 1.
						</p>
					</div>
				)}
			</section>
		</div>
	);
}
