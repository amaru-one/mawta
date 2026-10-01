// Notification feed backed by GET /notifications. `aiGenerated` splits the
// feed in two: assistant-detected alerts render in the accent, plain
// reminders stay neutral.

import { list } from './api/client';
import {
	markAllNotificationsRead as apiMarkAllRead,
	markNotificationRead as apiMarkRead,
	getNotifications
} from './api/endpoints/notifications';
import { toAppNotification } from './api/mappers';
import { notifications } from './stores';

export async function loadNotifications(): Promise<void> {
	const dto = await getNotifications();
	notifications.set(list(dto.notifications).map(toAppNotification));
}

// Read state is low stakes: update the store instantly, let the API call
// settle in the background, and the next page visit or sign-in reconciles
// any failure.
export function markNotificationRead(id: string): void {
	notifications.update(($n) => $n.map((n) => (n.id === id ? { ...n, read: true } : n)));
	void apiMarkRead(id).catch(() => {});
}

export function markAllNotificationsRead(): void {
	notifications.update(($n) => $n.map((n) => ({ ...n, read: true })));
	void apiMarkAllRead().catch(() => {});
}
