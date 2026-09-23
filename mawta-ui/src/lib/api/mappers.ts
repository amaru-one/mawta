// DTO → app-type translation. The app keeps its camelCase types in $lib/types;
// this module is the single place wire shapes are converted.

import type { IconName } from '$lib/icons';
import type { AppNotification, CompetencyLevel } from '$lib/types';
import type { CompetencyLevelDto, NotificationDto } from './dto';

// "YYYY-MM-DD" → local-midnight Date (avoid the UTC shift of new Date(string)).
export function parseDateOnly(d: string): Date {
	const [y, m, day] = d.split('-').map(Number);
	return new Date(y, m - 1, day);
}

function parseTimestamp(ts: string): Date {
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

// Reminder icons vary by what's pending.
const CATEGORY_ICONS: Record<string, IconName> = {
	attendance_unmarked: 'clipboard-check',
	grades_pending: 'checklist',
	level_drop: 'trending-down',
	consecutive_absences: 'alert',
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
		read: dto.read_at !== null,
	};
}

// The teacher's asserted level is the record, and nothing else stands in for
// it (RVM 094-2020, 5.1.1.3 p.2-3). A null level means "not developed this
// period" and must be rendered blank, never as C.
export function toCompetencyLevel(dto: CompetencyLevelDto): CompetencyLevel {
	return {
		competencyId: dto.competency_id,
		code: dto.code,
		name: dto.name,
		kind: dto.kind,
		level: dto.level,
		assertedAt: dto.asserted_at !== null ? parseTimestamp(dto.asserted_at) : null,
		conclusionRequired: dto.conclusion_required,
		conclusionRequirement: dto.conclusion_requirement,
		conclusionBody: dto.conclusion_body,
		conclusionStatus: dto.conclusion_status,
	};
}
