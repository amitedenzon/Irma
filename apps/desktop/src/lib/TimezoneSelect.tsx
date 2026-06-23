/**
 * Timezone picker backed by the runtime's IANA database.
 *
 * `Intl.supportedValuesOf("timeZone")` returns the full canonical list
 * (Tauri's WKWebView/Chromium support it); we fall back to ["UTC"] if the
 * API is somehow unavailable. The component guarantees the current value is
 * always selectable, even if it isn't in the runtime list (e.g. a legacy
 * value previously stored as free text).
 */

const TIMEZONES: string[] = (() => {
	const fn = (Intl as { supportedValuesOf?: (key: "timeZone") => string[] })
		.supportedValuesOf;
	if (typeof fn === "function") {
		try {
			return fn("timeZone");
		} catch {
			/* fall through to fallback */
		}
	}
	return ["UTC"];
})();

/** The host machine's current IANA timezone — a sensible default. */
export const LOCAL_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function TimezoneSelect({
	id,
	value,
	onChange,
	className,
}: {
	id?: string;
	value: string;
	onChange: (tz: string) => void;
	className?: string;
}) {
	const options =
		value && !TIMEZONES.includes(value) ? [value, ...TIMEZONES] : TIMEZONES;

	return (
		<select
			id={id}
			className={className ?? "input"}
			value={value}
			onChange={(e) => onChange(e.target.value)}>
			{options.map((tz) => (
				<option key={tz} value={tz}>
					{tz}
				</option>
			))}
		</select>
	);
}
