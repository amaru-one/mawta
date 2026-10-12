const ORIGIN = 'https://mawta.invalid';

// Accepts only same-origin paths. Anything that resolves elsewhere (`//host`,
// `/\host`, schemes) is rejected, so `?next=` cannot send a teacher off-site.
// Login itself is rejected too, which prevents a redirect loop.
export function safeNext(value: string | null | undefined): string | null {
	if (!value || !value.startsWith('/') || value.startsWith('/login')) return null;
	try {
		return new URL(value, ORIGIN).origin === ORIGIN ? value : null;
	} catch {
		return null;
	}
}

export function loginHref(from?: string | null): string {
	const next = safeNext(from);
	return next ? `/login?next=${encodeURIComponent(next)}` : '/login';
}
