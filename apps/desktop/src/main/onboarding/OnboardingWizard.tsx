/**
 * OnboardingWizard — full-screen first-run setup wizard.
 *
 * Persistence strategy: write-on-advance.
 *   - Profile fields (identity + email/brief) → patchProfile() when the user
 *     clicks Next on that step. Hot-reloaded; no restart required.
 *   - Secret keys (Anthropic / Google OAuth / Resend) → saved immediately when
 *     the user clicks the per-key "Save" button inside the step. Keys need a
 *     backend restart; the steps inform the user of this.
 *   - setup_complete → set to true via completeSetup() at Done.
 *
 * Wiring (Task 8): import OnboardingWizard from this file and conditionally
 * render it in App.tsx when needsSetup() returns true. Pass onDone to clear
 * the wizard gate.
 */

import React, { useState } from "react";
import confetti from "canvas-confetti";
import { patchProfile } from "../../lib/api";
import { completeSetup } from "../../lib/onboarding";

import { IdentityStep } from "./steps/IdentityStep";
import type { IdentityDraft } from "./steps/IdentityStep";
import { AiStep } from "./steps/AiStep";
import type { AiDraft } from "./steps/AiStep";
import { CalendarStep } from "./steps/CalendarStep";
import type { CalendarDraft } from "./steps/CalendarStep";
import { EmailStep } from "./steps/EmailStep";
import type { EmailDraft } from "./steps/EmailStep";
import { DoneStep } from "./steps/DoneStep";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type StepId = "identity" | "ai" | "calendar" | "email" | "done";

interface StepMeta {
	id: StepId;
	label: string;
	skippable: boolean;
}

const STEPS: StepMeta[] = [
	{ id: "identity", label: "You", skippable: false },
	{ id: "ai", label: "AI", skippable: false },
	{ id: "calendar", label: "Calendar", skippable: true },
	{ id: "email", label: "Email", skippable: true },
	{ id: "done", label: "Done", skippable: false },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function stepIndex(id: StepId): number {
	return STEPS.findIndex((s) => s.id === id);
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export function OnboardingWizard({
	onDone,
}: {
	onDone: () => void;
}): React.ReactElement {
	// Current step
	const [stepId, setStepId] = useState<StepId>("identity");

	// Per-step draft state — kept at wizard level so reopening preserves input
	const [identityDraft, setIdentityDraft] = useState<IdentityDraft>({
		owner_name: "",
		owner_role: "",
		persona_blurb: "",
		timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
	});
	const [aiDraft, setAiDraft] = useState<AiDraft>({
		mode: "claude",
		apiKey: "",
	});
	const [calendarDraft, setCalendarDraft] = useState<CalendarDraft>({
		clientId: "",
		clientSecret: "",
	});
	const [emailDraft, setEmailDraft] = useState<EmailDraft>({
		resendKey: "",
		owner_email: "",
		daily_brief_enabled: true,
		brief_hour: 8,
	});

	// Restart-required notice state
	const [restartNote, setRestartNote] = useState(false);

	// Advance / back loading state
	const [advancing, setAdvancing] = useState(false);
	const [advanceError, setAdvanceError] = useState<string | null>(null);

	const current = STEPS[stepIndex(stepId)];
	const idx = stepIndex(stepId);
	const isFirst = idx === 0;
	const isLast = stepId === "done";

	const goToIndex = (i: number) => {
		setAdvanceError(null);
		setStepId(STEPS[i].id);
	};

	const goBack = () => {
		if (idx > 0) goToIndex(idx - 1);
	};

	// ---------------------------------------------------------------------------
	// Advance logic — persists profile fields for the current step before moving
	// ---------------------------------------------------------------------------
	const advance = async (skip = false) => {
		setAdvanceError(null);
		setAdvancing(true);
		try {
			if (!skip) {
				// Write-on-advance: persist profile fields for this step
				if (stepId === "identity") {
					await patchProfile({
						owner_name: identityDraft.owner_name.trim(),
						owner_role: identityDraft.owner_role.trim() || undefined,
						persona_blurb: identityDraft.persona_blurb.trim() || undefined,
						timezone:
							identityDraft.timezone.trim() ||
							Intl.DateTimeFormat().resolvedOptions().timeZone,
					});
				} else if (stepId === "email") {
					await patchProfile({
						owner_email: emailDraft.owner_email.trim() || undefined,
						daily_brief_enabled: emailDraft.daily_brief_enabled,
						brief_hour: emailDraft.brief_hour,
					});
				}
			}

			// Move to Done: complete setup + confetti
			if (idx === STEPS.length - 2) {
				await completeSetup();
				void confetti({
					particleCount: 140,
					spread: 75,
					origin: { y: 0.45 },
					colors: ["#f5c518", "#ff6b6b", "#4ecdc4", "#45b7d1", "#f9ca24"],
				});
				setStepId("done");
				return;
			}

			goToIndex(idx + 1);
		} catch (e) {
			setAdvanceError(e instanceof Error ? e.message : "Something went wrong.");
		} finally {
			setAdvancing(false);
		}
	};

	const finish = () => {
		onDone();
	};

	// ---------------------------------------------------------------------------
	// Next button enabled-ness
	// ---------------------------------------------------------------------------
	const nextDisabled = (() => {
		if (advancing) return true;
		if (stepId === "identity") return !identityDraft.owner_name.trim();
		return false;
	})();

	// ---------------------------------------------------------------------------
	// Render
	// ---------------------------------------------------------------------------
	return (
		<div
			className="fixed inset-0 z-50 flex flex-col"
			style={{ background: "var(--color-bg)" }}>
			{/* Top stepper bar */}
			<header
				className="shrink-0 px-6 pt-5 pb-4 border-b"
				style={{
					background: "var(--color-surface)",
					borderColor: "var(--color-border)",
				}}>
				<div className="flex items-center gap-1 max-w-lg mx-auto">
					{STEPS.filter((s) => s.id !== "done").map((s, i) => {
						const done = idx > i;
						const active = stepIndex(stepId) === i;
						return (
							<div
								key={s.id}
								className="flex items-center gap-1 min-w-0">
								{/* Step dot */}
								<div
									className="flex items-center gap-1.5 min-w-0 shrink-0">
									<span
										className="w-5 h-5 rounded-full text-[10px] font-semibold flex items-center justify-center shrink-0 transition-colors"
										style={{
											background: done
												? "var(--color-moss)"
												: active
													? "var(--color-red)"
													: "var(--color-surface-2)",
											color: done || active ? "white" : "var(--color-ink-faint)",
										}}>
										{done ? "✓" : i + 1}
									</span>
									<span
										className="text-[11px] font-medium hidden sm:inline truncate"
										style={{
											color: active
												? "var(--color-ink)"
												: done
													? "var(--color-moss)"
													: "var(--color-ink-faint)",
										}}>
										{s.label}
									</span>
								</div>
								{/* Connector */}
								{i < STEPS.length - 2 && (
									<div
										className="flex-1 h-px mx-2 min-w-[8px]"
										style={{
											background: done
												? "var(--color-moss)"
												: "var(--color-border)",
										}}
									/>
								)}
							</div>
						);
					})}
				</div>
			</header>

			{/* Scrollable step content */}
			<main className="flex-1 overflow-y-auto">
				<div className="max-w-lg mx-auto px-6 py-8">
					{stepId === "identity" && (
						<IdentityStep
							draft={identityDraft}
							onChange={setIdentityDraft}
						/>
					)}
					{stepId === "ai" && (
						<AiStep
							draft={aiDraft}
							onChange={setAiDraft}
							onKeySaved={(restart) => {
								if (restart) setRestartNote(true);
							}}
						/>
					)}
					{stepId === "calendar" && (
						<CalendarStep
							draft={calendarDraft}
							onChange={setCalendarDraft}
						/>
					)}
					{stepId === "email" && (
						<EmailStep
							draft={emailDraft}
							onChange={setEmailDraft}
							onKeySaved={(restart) => {
								if (restart) setRestartNote(true);
							}}
						/>
					)}
					{stepId === "done" && <DoneStep />}
				</div>
			</main>

			{/* Restart-required notice (dismissible) */}
			{restartNote && (
				<div
					className="shrink-0 px-6 py-2 border-t flex items-center justify-between gap-3"
					style={{
						background:
							"color-mix(in srgb, var(--color-amber) 10%, var(--color-surface))",
						borderColor:
							"color-mix(in srgb, var(--color-amber) 30%, transparent)",
					}}>
					<p className="text-[11px]" style={{ color: "var(--color-amber)" }}>
						Some keys require a backend restart to take effect. You can restart
						from Settings → General after finishing setup.
					</p>
					<button
						type="button"
						onClick={() => setRestartNote(false)}
						className="shrink-0 text-[12px] px-2"
						aria-label="Dismiss restart notice"
						style={{ color: "var(--color-ink-faint)" }}>
						×
					</button>
				</div>
			)}

			{/* Error banner */}
			{advanceError && (
				<div
					className="shrink-0 px-6 py-2 border-t"
					style={{
						background:
							"color-mix(in srgb, var(--color-red) 8%, var(--color-surface))",
						borderColor:
							"color-mix(in srgb, var(--color-red) 25%, transparent)",
					}}>
					<p className="text-[12px]" style={{ color: "var(--color-red)" }}>
						{advanceError}
					</p>
				</div>
			)}

			{/* Bottom navigation */}
			<footer
				className="shrink-0 px-6 py-4 border-t flex items-center justify-between gap-3"
				style={{
					background: "var(--color-surface)",
					borderColor: "var(--color-border)",
				}}>
				{/* Left: Back */}
				<div>
					{!isFirst && !isLast && (
						<button
							type="button"
							onClick={goBack}
							disabled={advancing}
							className="btn-ghost disabled:opacity-40">
							← Back
						</button>
					)}
				</div>

				{/* Right: Skip + Next / Finish */}
				<div className="flex items-center gap-2">
					{current.skippable && !isLast && (
						<button
							type="button"
							onClick={() => void advance(true)}
							disabled={advancing}
							className="btn-ghost disabled:opacity-40">
							Skip
						</button>
					)}

					{!isLast && (
						<button
							type="button"
							onClick={() => void advance(false)}
							disabled={nextDisabled}
							className="btn-red disabled:opacity-40">
							{advancing
								? "Saving…"
								: idx === STEPS.length - 2
									? "Finish"
									: "Next →"}
						</button>
					)}

					{isLast && (
						<button
							type="button"
							onClick={finish}
							className="btn-red">
							Open Irma
						</button>
					)}
				</div>
			</footer>
		</div>
	);
}
