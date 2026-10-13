// Date helpers for the range calendar. Dates are ISO "YYYY-MM-DD" strings, read and
// written as local midnight so no timezone shifts a class day.

export const WEEKDAY_INITIALS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'] as const; // Monday first

const MONTHS_ES = [
	'enero',
	'febrero',
	'marzo',
	'abril',
	'mayo',
	'junio',
	'julio',
	'agosto',
	'septiembre',
	'octubre',
	'noviembre',
	'diciembre',
];
const WEEKDAYS_ES = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

export type YearMonth = { year: number; month: number }; // month 0-11

// What a day is, for the teacher. Only "free" days can ever be a start or an end.
export type DayKind = 'free' | 'busy' | 'holiday' | 'vacation' | 'management' | 'noclass';

export function parseISO(iso: string): Date {
	const [y, m, d] = iso.split('-').map(Number);
	return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

export function toISO(date: Date): string {
	const y = date.getFullYear();
	const m = String(date.getMonth() + 1).padStart(2, '0');
	const d = String(date.getDate()).padStart(2, '0');
	return `${y}-${m}-${d}`;
}

export function addDays(iso: string, days: number): string {
	const date = parseISO(iso);
	date.setDate(date.getDate() + days);
	return toISO(date);
}

export function yearMonthOf(iso: string): YearMonth {
	const date = parseISO(iso);
	return { year: date.getFullYear(), month: date.getMonth() };
}

export function compareYearMonth(a: YearMonth, b: YearMonth): number {
	return a.year * 12 + a.month - (b.year * 12 + b.month);
}

export function shiftMonth(ym: YearMonth, delta: number): YearMonth {
	const total = ym.year * 12 + ym.month + delta;
	return { year: Math.floor(total / 12), month: total % 12 };
}

// Monday-first weeks of the month. Padding cells outside the month are null.
export function monthGrid(ym: YearMonth): (string | null)[][] {
	const first = new Date(ym.year, ym.month, 1);
	const daysInMonth = new Date(ym.year, ym.month + 1, 0).getDate();
	const leading = (first.getDay() + 6) % 7; // Sunday(0) becomes 6
	const cells: (string | null)[] = [];
	for (let i = 0; i < leading; i++) cells.push(null);
	for (let day = 1; day <= daysInMonth; day++) {
		cells.push(toISO(new Date(ym.year, ym.month, day)));
	}
	while (cells.length % 7 !== 0) cells.push(null);
	const weeks: (string | null)[][] = [];
	for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
	return weeks;
}

export function monthTitle(ym: YearMonth): string {
	return `${MONTHS_ES[ym.month]} ${ym.year}`;
}

// "martes 6 de octubre de 2026": the accessible name of a day.
export function dayLabel(iso: string): string {
	const date = parseISO(iso);
	return `${WEEKDAYS_ES[date.getDay()]} ${date.getDate()} de ${MONTHS_ES[date.getMonth()]} de ${date.getFullYear()}`;
}
