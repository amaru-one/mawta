import { redirect } from '@sveltejs/kit';

import type { LayoutLoad } from './$types';

// The term-planning flow stays behind PUBLIC_PLANNING_ENABLED, not only its
// entry row in the class panel: with the flag off, a direct link to any
// /plan screen goes back to the class panel. Merged code can then reach
// production without teachers landing on the flow before it is turned on.
const PLANNING_ENABLED =
	(import.meta.env as Record<string, string | undefined>).PUBLIC_PLANNING_ENABLED === 'true';

export const load: LayoutLoad = ({ params }) => {
	if (!PLANNING_ENABLED) redirect(307, `/class/${params.courseId}`);
};
