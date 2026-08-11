// Mock notification feed — no grades/risk-detection model exists yet, so this
// is seeded sample data, not a real computation. Replace with a real feed
// once grades land. In-memory only; does not persist across reloads.

import { notifications } from './stores';
import type { AppNotification } from './types';

const MOCK: AppNotification[] = [
	{
		id: 'notif-1',
		type: 'risk',
		message: 'Missed the last 3 assessments and is at risk of failing this term.',
		studentName: 'Ana Morales',
		createdAt: new Date(Date.now() - 1000 * 60 * 40),
		read: false,
	},
	{
		id: 'notif-2',
		type: 'risk',
		message: 'Participation has dropped sharply over the last two weeks.',
		studentName: 'Diego Krause',
		createdAt: new Date(Date.now() - 1000 * 60 * 60 * 5),
		read: false,
	},
	{
		id: 'notif-3',
		type: 'tip',
		message:
			'Try a 5-minute think-pair-share — it tends to lift engagement for students with low participation streaks.',
		createdAt: new Date(Date.now() - 1000 * 60 * 60 * 20),
		read: false,
	},
	{
		id: 'notif-4',
		type: 'tip',
		message:
			'Students absent for 2+ consecutive sessions rarely catch up without a direct check-in this week.',
		createdAt: new Date(Date.now() - 1000 * 60 * 60 * 27),
		read: true,
	},
];

export function loadMockNotifications(): void {
	notifications.set(MOCK);
}

export function markNotificationRead(id: string): void {
	notifications.update((list) => list.map((n) => (n.id === id ? { ...n, read: true } : n)));
}

export function markAllNotificationsRead(): void {
	notifications.update((list) => list.map((n) => ({ ...n, read: true })));
}
