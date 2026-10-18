// The director's chat token (chat-director D002): asked from mawta-server
// with the session cookie, kept in memory only (never localStorage), renewed
// when less than five minutes are left or when the chat service answers 401,
// and dropped on logout.
import { apiGet } from '$lib/api/client';

type ChatTokenDto = { token: string; expires_at: string };

const RENEW_BEFORE_MS = 5 * 60 * 1000;

let cached: { token: string; expiresAt: number } | null = null;
let inflight: Promise<string> | null = null;

export function chatToken(forceRenew = false): Promise<string> {
	if (!forceRenew && cached && cached.expiresAt - Date.now() > RENEW_BEFORE_MS) {
		return Promise.resolve(cached.token);
	}
	// Concurrent callers share one request instead of each minting a token.
	inflight ??= apiGet<ChatTokenDto>('/auth/chat-token')
		.then((dto) => {
			cached = { token: dto.token, expiresAt: Date.parse(dto.expires_at) };
			return dto.token;
		})
		.finally(() => {
			inflight = null;
		});
	return inflight;
}

export function forgetChatToken(): void {
	cached = null;
}
