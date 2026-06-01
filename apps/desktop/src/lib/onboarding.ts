/**
 * First-run setup helpers.
 *
 * Error policy for needsSetup():
 *   If the backend is unreachable we return `false` (don't gate) so a momentary
 *   hiccup doesn't trap the user in the wizard. The App's existing readiness
 *   gate handles the "backend is down" case independently.
 */

import { fetchIntegrationsStatus, patchProfile } from "./api";
import type { Profile, ProfileUpdate } from "./api";

/**
 * Returns `true` when the backend profile has `setup_complete === false`,
 * indicating the first-run wizard should be shown.
 *
 * Reuses `fetchIntegrationsStatus()` (which already exposes `setup_complete`)
 * to avoid an extra round-trip; the App gate calls it on startup anyway.
 */
export async function needsSetup(): Promise<boolean> {
	try {
		const status = await fetchIntegrationsStatus();
		return !status.setup_complete;
	} catch {
		// Backend temporarily unreachable — don't block the user in the wizard.
		return false;
	}
}

/**
 * Finalises the setup wizard by PATCHing the profile with
 * `{ ...finalPatch, setup_complete: true }`.
 *
 * Returns the full updated profile.
 */
export async function completeSetup(finalPatch?: ProfileUpdate): Promise<Profile> {
	return patchProfile({ ...finalPatch, setup_complete: true });
}
