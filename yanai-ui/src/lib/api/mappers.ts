// DTO → app-type translation. The app keeps its camelCase types in $lib/types;
// this module is the single place wire shapes are converted.

import type { AppNotification } from '$lib/types';
import type { NotificationDto } from './dto';

// "YYYY-MM-DD" → local-midnight Date (avoid the UTC shift of new Date(string)).
export function parseDateOnly(d: string): Date {
	const [y, m, day] = d.split('-').map(Number);
	return new Date(y, m - 1, day);
}

export function parseTimestamp(ts: string): Date {
	return new Date(ts);
}

// RFC3339 timestamp → "HH:MM" wall-clock label.
export function formatTimeHHMM(ts: string): string {
	const d = new Date(ts);
	const hh = String(d.getHours()).padStart(2, '0');
	const mm = String(d.getMinutes()).padStart(2, '0');
	return `${hh}:${mm}`;
}

// Server sends one display name built as "given_name paternal_surname";
// the last token is the surname.
export function splitDisplayName(name: string): { firstName: string; lastName: string } {
	const idx = name.lastIndexOf(' ');
	if (idx === -1) return { firstName: name, lastName: '' };
	return { firstName: name.slice(0, idx), lastName: name.slice(idx + 1) };
}

export function toAppNotification(dto: NotificationDto): AppNotification {
	return {
		id: dto.id,
		// Server alerts come from the risk model/rules; reminders are derived to-dos.
		type: dto.kind === 'alert' ? 'risk' : 'reminder',
		aiGenerated: dto.kind === 'alert',
		message: dto.title,
		detail: dto.body ?? undefined,
		studentName: dto.student_name ?? undefined,
		courseName: dto.class_name ?? undefined,
		createdAt: parseTimestamp(dto.created_at),
		read: dto.read_at !== null
	};
}
