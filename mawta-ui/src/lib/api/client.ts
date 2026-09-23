// REST client for mawta-server. Requests are same-origin by default — the Vite
// dev proxy and the production reverse proxy both route /api/* to the Go server —
// so PUBLIC_API_BASE_URL only needs to be set when the API lives elsewhere.

const env = import.meta.env as Record<string, string | undefined>;

const API_BASE = env.PUBLIC_API_BASE_URL ?? '';

export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly code: string,
		message: string,
		readonly hint?: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

// Real auth: the server issues an HttpOnly session cookie on POST
// /auth/login. Every request must carry it (credentials: 'include') — there
// are no more X-Tenant-ID/X-Actor-ID headers to attach.
type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

// Called once from the root layout. Kept out of SvelteKit-specific imports
// here so this module stays a plain fetch wrapper.
export function setUnauthorizedHandler(fn: UnauthorizedHandler): void {
	onUnauthorized = fn;
}

// The server wraps errors as {"error":{code,message,hint}}, but unmatched
// routes (404/405) and panics come back from chi as plain text.
async function toApiError(res: Response): Promise<ApiError> {
	try {
		const body = (await res.json()) as {
			error?: { code?: string; message?: string; hint?: string };
		};
		if (body?.error?.code) {
			return new ApiError(
				res.status,
				body.error.code,
				body.error.message ?? res.statusText,
				body.error.hint
			);
		}
	} catch {
		// non-JSON body
	}
	return new ApiError(res.status, 'http_error', `${res.status} ${res.statusText}`);
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
	const res = await fetch(`${API_BASE}/api/v1${path}`, { ...init, credentials: 'include' });
	if (!res.ok) {
		// Except on /auth/* itself: a wrong password IS a 401 on /auth/login,
		// and firing the redirect there would eat the error the login form
		// needs to show instead of navigating away from it.
		if (res.status === 401 && !path.startsWith('/auth/')) {
			onUnauthorized?.();
		}
		throw await toApiError(res);
	}
	// Deletes answer 204 with no body. Parsing that as JSON throws, which made
	// a successful delete look like a failed request to every caller.
	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
	return request<T>(path, {});
}

export function apiSend<T>(method: 'POST' | 'PUT', path: string, body?: unknown): Promise<T> {
	return request<T>(path, {
		method,
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
}

// Multipart upload — no Content-Type header so the browser sets the boundary.
export function apiUpload<T>(path: string, form: FormData): Promise<T> {
	return request<T>(path, { method: 'POST', body: form });
}

// Voice-note audio needs the session cookie, so it can't be a plain
// <audio src> URL; fetch it into a Blob and hand it to the Web Audio decode
// path. (Now that auth rides on a cookie rather than custom headers, a plain
// <audio src> is possible — deliberately left as a follow-up, not done here.)
export async function fetchAudioBlob(voiceNoteId: string): Promise<Blob> {
	const res = await fetch(`${API_BASE}/api/v1/voice-notes/${voiceNoteId}/audio`, {
		credentials: 'include',
	});
	if (!res.ok) throw await toApiError(res);
	return res.blob();
}

// Empty Go slices serialize as null, never [] — normalize at every list boundary.
export function list<T>(v: T[] | null | undefined): T[] {
	return v ?? [];
}
