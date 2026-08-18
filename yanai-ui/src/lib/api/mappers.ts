// DTO → app-type translation. The app keeps its camelCase types in $lib/types;
// this module is the single place wire shapes are converted.

import { ICON_NAMES, type IconName } from '$lib/icons';
import type { AppNotification, HomeCourse } from '$lib/types';
import type { HomeDto, NotificationDto } from './dto';

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

// Subjects carry an icon_key that happens to match our sprite names.
function toIconName(key: string | null): IconName {
	return key !== null && (ICON_NAMES as readonly string[]).includes(key)
		? (key as IconName)
		: 'book';
}

// ISO-8601 weekday from the server: 1 = Monday .. 7 = Sunday.
const WEEKDAY_LABELS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

export function toHomeCourses(dto: HomeDto): HomeCourse[] {
	const today: HomeCourse[] = (dto.today ?? []).map((t) => ({
		id: t.class_id,
		name: t.name,
		icon: toIconName(t.icon_key),
		schedule:
			t.scheduled_start_at !== null && t.scheduled_end_at !== null
				? [`${formatTimeHHMM(t.scheduled_start_at)} – ${formatTimeHHMM(t.scheduled_end_at)}`]
				: [],
		status: t.status === 'in_progress' ? 'live' : t.status === 'scheduled' ? 'pending' : 'idle',
		bucket: 'today',
		sessionId: t.session_id
	}));

	const week: HomeCourse[] = (dto.week ?? []).map((w) => ({
		id: w.class_id,
		name: w.name,
		icon: toIconName(w.icon_key),
		schedule: (w.slots ?? []).map(
			(s) => `${WEEKDAY_LABELS[s.weekday - 1] ?? ''} ${s.starts_at} – ${s.ends_at}`.trim()
		),
		status: 'idle',
		bucket: 'week',
		sessionId: null
	}));

	return [...today, ...week];
}

// Reminder icons vary by what's pending.
const CATEGORY_ICONS: Record<string, IconName> = {
	attendance_unmarked: 'clipboard-check',
	grades_pending: 'checklist',
	level_drop: 'trending-down',
	consecutive_absences: 'alert'
};

export function toAppNotification(dto: NotificationDto): AppNotification {
	// Server titles embed the student/class names, but the feed renders those
	// separately — strip them from the message so they don't display twice.
	let message = dto.title;
	if (dto.student_name !== null && message.startsWith(dto.student_name)) {
		message = message.slice(dto.student_name.length).trimStart();
	}
	if (dto.class_name !== null) {
		const suffix = `— ${dto.class_name}`;
		if (message.endsWith(suffix)) message = message.slice(0, -suffix.length).trimEnd();
	}

	return {
		id: dto.id,
		// Server alerts come from the risk model/rules; reminders are derived to-dos.
		type: dto.kind === 'alert' ? 'risk' : 'reminder',
		aiGenerated: dto.kind === 'alert',
		message,
		detail: dto.body ?? undefined,
		studentName: dto.student_name ?? undefined,
		courseName: dto.class_name ?? undefined,
		icon: CATEGORY_ICONS[dto.category],
		createdAt: parseTimestamp(dto.created_at),
		read: dto.read_at !== null
	};
}
