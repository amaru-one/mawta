import { HOME_COURSES } from '$lib/mocks';

// The app is prerendered and client-only, so every dynamic route has to
// enumerate itself — nothing crawls the empty prerendered shells.
export function entries(): Array<{ courseId: string }> {
	return HOME_COURSES.map((c) => ({ courseId: c.id }));
}
