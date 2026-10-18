// Client for the director chat service (mawta-chat). Same origin: Caddy in
// production and the Vite dev proxy both route /chat-api/* to it.
import { ApiError } from '$lib/api/client';
import { readSse } from './sse';
import { chatToken } from './token';
import type { Message, StreamEvent, Thread } from './types';

const env = import.meta.env as Record<string, string | undefined>;
const CHAT_BASE = `${env.PUBLIC_API_BASE_URL ?? ''}/chat-api`;

async function toChatError(res: Response): Promise<ApiError> {
	try {
		const body = (await res.json()) as { error?: { code?: string; message?: string } };
		if (body?.error?.code) {
			return new ApiError(res.status, body.error.code, body.error.message ?? res.statusText);
		}
	} catch {
		// non-JSON body
	}
	return new ApiError(res.status, 'http_error', `${res.status} ${res.statusText}`);
}

// One retry with a fresh token when the chat service answers 401: the cached
// token may have just expired, or the signing key may have rotated.
async function chatFetch(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
	const token = await chatToken(retried);
	const headers = new Headers(init.headers);
	headers.set('Authorization', `Bearer ${token}`);
	if (init.body) headers.set('Content-Type', 'application/json');
	const res = await fetch(`${CHAT_BASE}${path}`, { ...init, headers });
	if (res.status === 401 && !retried) return chatFetch(path, init, true);
	return res;
}

async function chatJson<T>(path: string, init: RequestInit = {}): Promise<T> {
	const res = await chatFetch(path, init);
	if (!res.ok) throw await toChatError(res);
	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

export function listThreads(): Promise<Thread[]> {
	return chatJson<Thread[]>('/threads');
}

export function createThread(): Promise<Thread> {
	return chatJson<Thread>('/threads', { method: 'POST' });
}

export function renameThread(id: string, title: string): Promise<Thread> {
	return chatJson<Thread>(`/threads/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) });
}

export function deleteThread(id: string): Promise<void> {
	return chatJson<void>(`/threads/${id}`, { method: 'DELETE' });
}

export function listMessages(id: string): Promise<Message[]> {
	return chatJson<Message[]>(`/threads/${id}/messages`);
}

// Sends a question and calls onEvent for every protocol v1 event of the
// answer, until `fin`. Aborting the signal stops reading the answer.
export async function ask(
	id: string,
	texto: string,
	onEvent: (event: StreamEvent) => void,
	signal?: AbortSignal
): Promise<void> {
	const res = await chatFetch(`/threads/${id}/messages`, {
		method: 'POST',
		body: JSON.stringify({ texto }),
		signal,
	});
	if (!res.ok || !res.body) throw await toChatError(res);
	await readSse(res.body, (event) => onEvent(event as StreamEvent));
}
