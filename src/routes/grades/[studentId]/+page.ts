import { SEEDED_STUDENT_IDS } from '$lib/seed';

// The app is prerendered and client-only, so every dynamic route has to
// enumerate itself — nothing crawls the empty prerendered shells.
export function entries(): Array<{ studentId: string }> {
	return SEEDED_STUDENT_IDS.map((studentId) => ({ studentId }));
}
