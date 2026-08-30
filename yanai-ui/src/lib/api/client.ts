// REST client for yanai-server. Requests are same-origin by default — the Vite
// dev proxy and the production reverse proxy both route /api/* to the Go server —
// so PUBLIC_API_BASE_URL only needs to be set when the API lives elsewhere.

const env = import.meta.env as Record<string, string | undefined>;

const API_BASE = env.PUBLIC_API_BASE_URL ?? '';

// Dev auth: the server has no real auth yet; every request carries the tenant
// and actor as headers. Both are UUIDs from the seeded demo tenant.
const TENANT_ID = env.PUBLIC_TENANT_ID ?? '';
const ACTOR_ID = env.PUBLIC_ACTOR_ID ?? '';

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

function authHeaders(): Record<string, string> {
	return { 'X-Tenant-ID': TENANT_ID, 'X-Actor-ID': ACTOR_ID };
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
	const res = await fetch(`${API_BASE}/api/v1${path}`, init);
	if (!res.ok) throw await toApiError(res);
	// Deletes answer 204 with no body. Parsing that as JSON throws, which made
	// a successful delete look like a failed request to every caller.
	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
	return request<T>(path, { headers: authHeaders() });
}

export function apiSend<T>(method: 'POST' | 'PUT', path: string, body?: unknown): Promise<T> {
	return request<T>(path, {
		method,
		headers:
			body === undefined ? authHeaders() : { ...authHeaders(), 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
}

// Multipart upload — no Content-Type header so the browser sets the boundary.
export function apiUpload<T>(path: string, form: FormData): Promise<T> {
	return request<T>(path, { method: 'POST', headers: authHeaders(), body: form });
}

// Voice-note audio requires the auth headers, so it can't be an <audio src> URL;
// fetch it into a Blob and hand it to the Web Audio decode path.
export async function fetchAudioBlob(voiceNoteId: string): Promise<Blob> {
	const res = await fetch(`${API_BASE}/api/v1/voice-notes/${voiceNoteId}/audio`, {
		headers: authHeaders(),
	});
	if (!res.ok) throw await toApiError(res);
	return res.blob();
}

// Empty Go slices serialize as null, never [] — normalize at every list boundary.
export function list<T>(v: T[] | null | undefined): T[] {
	return v ?? [];
}
