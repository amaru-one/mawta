import { apiGet, apiSend } from '../client';
import type { NotificationKind, NotificationListDto } from '../dto';

// Cursor pagination: pass the oldest created_at you already have as `before`.
export function getNotifications(opts?: {
	kind?: NotificationKind;
	limit?: number;
	before?: string;
}): Promise<NotificationListDto> {
	const qs = new URLSearchParams();
	if (opts?.kind) qs.set('kind', opts.kind);
	if (opts?.limit !== undefined) qs.set('limit', String(opts.limit));
	if (opts?.before) qs.set('before', opts.before);
	const suffix = qs.size > 0 ? `?${qs}` : '';
	return apiGet<NotificationListDto>(`/notifications${suffix}`);
}

export function markNotificationRead(id: string): Promise<{ ok: boolean }> {
	return apiSend<{ ok: boolean }>('POST', `/notifications/${id}/read`);
}

export function markAllNotificationsRead(): Promise<{ marked_read: number }> {
	return apiSend<{ marked_read: number }>('POST', '/notifications/read-all');
}
