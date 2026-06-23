// Shared guide modal — used by the API Keys tab and the setup wizard.

export interface Guide {
	title: string;
	steps: string[];
}

export function GuideModal({
	guide,
	onClose,
}: {
	guide: Guide;
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
