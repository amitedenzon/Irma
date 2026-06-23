/**
 * Step 5 — Done
 * Confirms setup is complete. The parent calls completeSetup() + confetti
 * before rendering this step (so the user sees it as the celebration screen).
 */

export function DoneStep() {
	return (
		<div className="flex flex-col items-center justify-center text-center space-y-6 py-8">
			{/* Logo mark */}
			<div
				className="w-16 h-16 rounded-2xl flex items-center justify-center"
				style={{
					background:
						"color-mix(in srgb, var(--color-red) 12%, transparent)",
					border:
						"1px solid color-mix(in srgb, var(--color-red) 25%, transparent)",
				}}>
				<span style={{ fontSize: 32 }}>🐾</span>
			</div>

			<div className="space-y-2">
				<h2
					className="display text-[24px] font-semibold"
					style={{ color: "var(--color-ink)" }}>
					Irma is ready
				</h2>
				<p
					className="text-[14px] max-w-xs mx-auto"
					style={{ color: "var(--color-ink-mute)" }}>
					Your daily assistant is configured and standing by. She'll surface
					conflicts, brief you each morning, and keep your projects on track.
				</p>
			</div>

			<div
				className="card p-4 text-left space-y-2 w-full max-w-xs"
				style={{ textAlign: "left" }}>
				<p
					className="display text-[11px] font-semibold uppercase tracking-wider"
					style={{ color: "var(--color-ink-mute)" }}>
					What's next
				</p>
				{[
					"Add your first project in the Projects tab.",
					"Check Settings to fine-tune keys or local models at any time.",
					"Ask Irma anything in the Chat tab.",
				].map((tip, i) => (
					<div key={i} className="flex gap-2.5 items-start">
						<span
							className="shrink-0 w-4 h-4 rounded-full text-[10px] font-semibold flex items-center justify-center mt-0.5"
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
							{tip}
						</p>
					</div>
				))}
			</div>
		</div>
	);
}
