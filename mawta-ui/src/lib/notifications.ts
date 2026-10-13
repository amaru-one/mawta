// Notification feed backed by GET /notifications. `aiGenerated` splits the
// feed in two: assistant-detected alerts render in the accent, plain
// reminders stay neutral.

import { list } from './api/client';
import {
	markNotificationRead as apiMarkRead,
	getNotifications,
} from './api/endpoints/notifications';
import { toAppNotification } from './api/mappers';
import { runSequential } from './batch';
import { showError } from './toast';
import { notifications } from './stores';

export async function loadNotifications(): Promise<void> {
	const dto = await getNotifications();
	notifications.set(list(dto.notifications).map(toAppNotification));
}

function setRead(ids: readonly string[], read: boolean): void {
	notifications.update(($n) => $n.map((n) => (ids.includes(n.id) ? { ...n, read } : n)));
}

// The store updates at once so the row reads as read; if the server refuses, the
// row goes back to unread and the teacher is offered a retry.
export function markNotificationRead(id: string): void {
	setRead([id], true);
	void apiMarkRead(id).catch(() => {
		setRead([id], false);
		showError('No se pudo marcar como leída', { onRetry: () => markNotificationRead(id) });
	});
}

// Marks exactly the given notifications, one request each, so a filtered view
// only touches what the teacher can see. Failures roll back and can be retried.
export async function markNotificationsRead(ids: readonly string[]): Promise<void> {
	setRead(ids, true);
	const result = await runSequential(ids, (id) => apiMarkRead(id));
	if (result.failed.length > 0) {
		setRead(result.failed, false);
		showError(`No se marcaron ${result.failed.length} de ${ids.length} notificaciones`, {
			onRetry: () => void markNotificationsRead(result.failed),
		});
	}
}
