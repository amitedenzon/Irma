/**
 * Step 1 — Identity
 * Collects: owner_name (required), owner_role, persona_blurb, timezone.
 * The wizard shell persists these on advance (write-on-advance strategy).
 */

export interface IdentityDraft {
	owner_name: string;
	owner_role: string;
	persona_blurb: string;
	timezone: string;
}

export function IdentityStep({
	draft,
	onChange,
}: {
	draft: IdentityDraft;
	onChange: (d: IdentityDraft) => void;
}) {
	const set =
		(key: keyof IdentityDraft) =>
		(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
			onChange({ ...draft, [key]: e.target.value });

	return (
		<div className="space-y-5">
			<div>
				<h2
					className="display text-[22px] font-semibold mb-1.5"
					style={{ color: "var(--color-ink)" }}>
					Let's set up Irma
				</h2>
				<p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
					A few quick details so Irma can tailor her voice to you.
				</p>
			</div>

			{/* Name — required */}
			<div className="space-y-1">
				<label
					htmlFor="identity-name"
					className="block text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Your name{" "}
					<span style={{ color: "var(--color-red)" }}>*</span>
				</label>
				<input
					id="identity-name"
					type="text"
					className="input"
					placeholder="e.g. Alex"
					value={draft.owner_name}
					onChange={set("owner_name")}
					autoFocus
				/>
			</div>

			{/* Role — optional */}
			<div className="space-y-1">
				<label
					htmlFor="identity-role"
					className="block text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					What you work on{" "}
					<span
						className="text-[10px] normal-case tracking-normal font-normal"
						style={{ color: "var(--color-ink-faint)" }}>
						optional
					</span>
				</label>
				<input
					id="identity-role"
					type="text"
					className="input"
					placeholder="AI researcher, deep learning, generative models"
					value={draft.owner_role}
					onChange={set("owner_role")}
				/>
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Helps Irma contextualise projects and surface relevant blockers.
				</p>
			</div>

			{/* Tone / persona blurb — optional */}
			<div className="space-y-1">
				<label
					htmlFor="identity-blurb"
					className="block text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Tone preference{" "}
					<span
						className="text-[10px] normal-case tracking-normal font-normal"
						style={{ color: "var(--color-ink-faint)" }}>
						optional
					</span>
				</label>
				<textarea
					id="identity-blurb"
					className="input resize-none"
					rows={3}
					placeholder="Terse and precise. No preamble. Surface blockers first."
					value={draft.persona_blurb}
					onChange={set("persona_blurb")}
					style={{ fontFamily: "var(--font-sans)" }}
				/>
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Injected verbatim into Irma's persona prompt.
				</p>
			</div>

			{/* Timezone */}
			<div className="space-y-1">
				<label
					htmlFor="identity-tz"
					className="block text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					Timezone
				</label>
				<input
					id="identity-tz"
					type="text"
					className="input font-mono text-[12px]"
					placeholder="e.g. America/New_York"
					value={draft.timezone}
					onChange={set("timezone")}
				/>
				<p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
					Anchors the daily brief and calendar signals.
				</p>
			</div>
		</div>
	);
}
