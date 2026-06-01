/**
 * Step 3 — Google Calendar (skippable)
 * 1. Credentials: GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET
 *    saved via POST /api/v1/settings.
 * 2. OAuth flow: connectGoogleCalendar() opens the browser; returns updated
 *    IntegrationsStatus. Show connected / not-connected state.
 */
import { useEffect, useState } from "react";
import { GuideModal } from "../../settings/GuideModal";
import type { Guide } from "../../settings/GuideModal";
import { connectGoogleCalendar, fetchIntegrationsStatus, IRMA_API_BASE } from "../../../lib/api";

const API = `${IRMA_API_BASE}/api/v1`;

const GOOGLE_GUIDE: Guide = {
	title: "Create a Google OAuth credential",
	steps: [
		"Go to console.cloud.google.com and create (or pick) a project.",
		'Enable the "Google Calendar API" under APIs & Services → Library.',
		'Go to APIs & Services → Credentials → "Create Credentials" → OAuth client ID.',
		'Set Application type to "Desktop app", give it any name, and click Create.',
		"Copy the Client ID (ends in .apps.googleusercontent.com) and paste it in the first field below.",
		"Copy the Client Secret and paste it in the second field, then click Save Credentials.",
		'Finally, click "Connect Google Calendar" — a browser window will open for authorization.',
	],
};

export interface CalendarDraft {
	clientId: string;
	clientSecret: string;
}

export function CalendarStep({
	draft,
	onChange,
}: {
	draft: CalendarDraft;
	onChange: (d: CalendarDraft) => void;
}) {
	const [showGuide, setShowGuide] = useState(false);
	const [revealSecret, setRevealSecret] = useState(false);

	// key persistence state
	const [savingCreds, setSavingCreds] = useState(false);
	const [savedCreds, setSavedCreds] = useState(false);
	const [credsError, setCredsError] = useState<string | null>(null);

	// connect state
	const [connecting, setConnecting] = useState(false);
	const [connected, setConnected] = useState<boolean | null>(null);
	const [connectError, setConnectError] = useState<string | null>(null);

	// fetch current connection status on mount
	useEffect(() => {
		fetchIntegrationsStatus()
			.then((s) => setConnected(s.calendar_linked))
			.catch(() => {/* backend may not be running — don't block */});
	}, []);

	const saveCreds = async () => {
		const id = draft.clientId.trim();
		const secret = draft.clientSecret.trim();
		if (!id || !secret) return;
		setSavingCreds(true);
		setCredsError(null);
		setSavedCreds(false);
		try {
			const res = await fetch(`${API}/settings`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					keys: {
						GOOGLE_OAUTH_CLIENT_ID: id,
						GOOGLE_OAUTH_CLIENT_SECRET: secret,
					},
				}),
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
			setSavedCreds(true);
		} catch (e) {
			setCredsError(e instanceof Error ? e.message : "Save failed.");
		} finally {
			setSavingCreds(false);
		}
	};

	const connectCalendar = async () => {
		setConnecting(true);
		setConnectError(null);
		try {
			const status = await connectGoogleCalendar();
			setConnected(status.calendar_linked);
		} catch (e) {
			setConnectError(e instanceof Error ? e.message : "Connection failed.");
		} finally {
			setConnecting(false);
		}
	};

	return (
		<div className="space-y-5">
			{showGuide && (
				<GuideModal guide={GOOGLE_GUIDE} onClose={() => setShowGuide(false)} />
			)}

			<div>
				<div className="flex items-center gap-2 mb-1.5">
					<h2
						className="display text-[22px] font-semibold"
						style={{ color: "var(--color-ink)" }}>
						Google Calendar
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
					Lets Irma read your calendar to surface conflicts and deadlines in
					daily briefs. You can skip this and add credentials in Settings later.
				</p>
			</div>

			{/* Guide button */}
			<button
				type="button"
				onClick={() => setShowGuide(true)}
				className="flex items-center gap-1.5 text-[12px] font-medium transition-opacity hover:opacity-80"
				style={{ color: "var(--color-red)" }}>
				<span
					className="w-4 h-4 rounded-full text-[10px] font-semibold flex items-center justify-center"
					style={{
						background:
							"color-mix(in srgb, var(--color-red) 15%, transparent)",
					}}>
					?
				</span>
				How to create a Google OAuth credential
			</button>

			{/* Credentials card */}
			<section className="card p-4 space-y-4">
				<h3
					className="display text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					OAuth Credentials
				</h3>

				{/* Client ID */}
				<div className="space-y-1">
					<label
						htmlFor="cal-client-id"
						className="block text-[11px] uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Client ID
					</label>
					<input
						id="cal-client-id"
						type="text"
						className="input font-mono text-[12px]"
						placeholder="123456789-abc….apps.googleusercontent.com"
						value={draft.clientId}
						onChange={(e) =>
							onChange({ ...draft, clientId: e.target.value })
						}
						autoComplete="off"
						spellCheck={false}
					/>
				</div>

				{/* Client Secret */}
				<div className="space-y-1">
					<label
						htmlFor="cal-client-secret"
						className="block text-[11px] uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Client Secret
					</label>
					<div className="relative">
						<input
							id="cal-client-secret"
							type={revealSecret ? "text" : "password"}
							className="input font-mono text-[12px]"
							style={{ paddingRight: "3rem" }}
							placeholder="GOCSPX-…"
							value={draft.clientSecret}
							onChange={(e) =>
								onChange({ ...draft, clientSecret: e.target.value })
							}
							autoComplete="off"
							spellCheck={false}
						/>
						<button
							type="button"
							onClick={() => setRevealSecret((v) => !v)}
							tabIndex={-1}
							className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px]"
							style={{ color: "var(--color-ink-faint)" }}>
							{revealSecret ? "hide" : "show"}
						</button>
					</div>
				</div>

				<div className="flex items-center gap-3">
					<button
						type="button"
						disabled={
							!draft.clientId.trim() ||
							!draft.clientSecret.trim() ||
							savingCreds
						}
						onClick={() => void saveCreds()}
						className="btn-red text-[12px] px-3 py-1.5 rounded-lg disabled:opacity-40">
						{savingCreds ? "Saving…" : "Save credentials"}
					</button>
					{savedCreds && (
						<span
							className="text-[12px]"
							style={{ color: "var(--color-moss)" }}>
							✓ Saved
						</span>
					)}
					{credsError && (
						<span
							className="text-[12px]"
							style={{ color: "var(--color-red)" }}>
							{credsError}
						</span>
					)}
				</div>
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Saved to .env — a backend restart will apply them.
				</p>
			</section>

			{/* Connect button */}
			<section className="card p-4 space-y-3">
				<div className="flex items-center gap-2">
					<h3
						className="display text-[11px] font-semibold uppercase tracking-wider"
						style={{ color: "var(--color-ink-mute)" }}>
						Authorization
					</h3>
					{connected !== null && (
						<span
							className="flex items-center gap-1.5 text-[10px] font-medium px-2 py-0.5 rounded-full"
							style={{
								background: connected
									? "color-mix(in srgb, var(--color-moss) 15%, transparent)"
									: "var(--color-surface-2)",
								color: connected
									? "var(--color-moss)"
									: "var(--color-ink-faint)",
							}}>
							<span
								className="w-1.5 h-1.5 rounded-full shrink-0"
								style={{
									background: connected
										? "var(--color-moss)"
										: "var(--color-ink-faint)",
								}}
							/>
							{connected ? "Connected" : "Not connected"}
						</span>
					)}
				</div>
				<p className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
					Opens a browser window to authorise Irma's calendar access. Save your
					credentials first.
				</p>
				<div className="flex items-center gap-3">
					<button
						type="button"
						disabled={connecting}
						onClick={() => void connectCalendar()}
						className="btn-red text-[12px] px-3 py-1.5 rounded-lg disabled:opacity-40">
						{connecting
							? "Opening browser…"
							: connected
								? "Re-connect"
								: "Connect Google Calendar"}
					</button>
					{connectError && (
						<span
							className="text-[12px]"
							style={{ color: "var(--color-red)" }}>
							{connectError}
						</span>
					)}
				</div>
			</section>
		</div>
	);
}
