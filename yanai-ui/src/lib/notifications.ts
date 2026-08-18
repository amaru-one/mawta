// Mock notification feed — no grades/risk-detection model exists yet, so this
// is seeded sample data, not a real computation. Replace with a real feed
// once grades land. In-memory only; does not persist across reloads.
//
// `aiGenerated` splits the feed in two: assistant-detected trends and tips are
// rendered in the accent (#5B5FC7), plain reminders stay neutral.

import { notifications } from './stores';
import type { AppNotification } from './types';

const minutesAgo = (n: number): Date => new Date(Date.now() - n * 60_000);

const MOCK: AppNotification[] = [
	{
		id: 'notif-1',
		type: 'risk',
		aiGenerated: true,
		message: 'bajó de A a B en las últimas 3 clases',
		studentName: 'María Torres',
		courseName: 'Matemática 8B',
		createdAt: minutesAgo(20),
		read: false,
	},
	{
		id: 'notif-2',
		type: 'risk',
		aiGenerated: true,
		message: 'acumula 3 ausencias seguidas',
		studentName: 'Sofía Ramírez',
		courseName: 'Inglés 5to B',
		createdAt: minutesAgo(120),
		read: false,
	},
	{
		id: 'notif-3',
		type: 'tip',
		aiGenerated: true,
		message:
			'Prueba un ejercicio de 5 minutos en parejas — suele levantar la participación de quienes vienen con rachas bajas.',
		courseName: 'Matemática 8B',
		createdAt: minutesAgo(60 * 20),
		read: false,
	},
	{
		id: 'notif-4',
		type: 'reminder',
		aiGenerated: false,
		message: 'Asistencia sin marcar',
		courseName: 'Comunicación 5A',
		detail: 'Clase de ayer',
		icon: 'clipboard-check',
		createdAt: minutesAgo(180),
		read: false,
	},
	{
		id: 'notif-5',
		type: 'reminder',
		aiGenerated: false,
		message: '3 notas pendientes',
		courseName: 'Matemática 8B',
		detail: 'Quiz 2',
		icon: 'checklist',
		createdAt: minutesAgo(60 * 24),
		read: false,
	},
	{
		id: 'notif-6',
		type: 'reminder',
		aiGenerated: false,
		message: 'Sin notas de voz',
		courseName: 'Tutoría 8B',
		detail: 'Sesión del lunes',
		icon: 'mic',
		createdAt: minutesAgo(60 * 48),
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
