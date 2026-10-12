import { afterNavigate, beforeNavigate, goto } from '$app/navigation';

// Guards one form against losing unsaved input. Call during component init.
//
// Rules (see the plan's "single-prompt" section):
// - Unloads (reload, tab close) cancel with the browser's native prompt only;
//   no second beforeunload handler, so the user is asked once.
// - In-app navigation opens one danger dialog. "Descartar" lets the confirmed
//   navigation through without re-prompting.
// - Same-page query changes (e.g. competencia in ?comp=) and /login are ignored.
export function guardUnsaved(isDirty: () => boolean) {
	const state = $state({ open: false });
	let target: URL | null = null;
	let bypass = false;

	beforeNavigate((navigation) => {
		if (bypass || !isDirty()) return;
		if (navigation.to?.url.pathname === '/login') return;
		const from = navigation.from?.url;
		const to = navigation.to?.url;
		if (from && to && from.pathname === to.pathname) return;
		if (navigation.willUnload) {
			navigation.cancel();
			return;
		}
		navigation.cancel();
		target = to ?? null;
		state.open = true;
	});

	afterNavigate(() => {
		bypass = false;
	});

	function confirmLeave(): void {
		state.open = false;
		const href = target?.href;
		target = null;
		if (!href) return;
		bypass = true;
		void goto(href).catch(() => {
			bypass = false;
		});
	}

	function stay(): void {
		state.open = false;
		target = null;
	}

	return { state, confirmLeave, stay };
}
