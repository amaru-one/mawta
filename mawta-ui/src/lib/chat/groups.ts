// Grouping and labels for the chat list and the thread's day separators.
import type { Thread } from './types';

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): number {
	return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function daysAgo(iso: string, now: Date): number {
	return Math.round((startOfDay(now) - startOfDay(new Date(iso))) / DAY_MS);
}

export type ThreadGroup = { label: string; threads: Thread[] };

export function groupThreads(threads: Thread[], now = new Date()): ThreadGroup[] {
	const order = ['Hoy', 'Ayer', 'Esta semana', 'Anteriores'];
	const groups = new Map<string, Thread[]>();
	for (const thread of threads) {
		const days = daysAgo(thread.updated_at, now);
		const label = days <= 0 ? 'Hoy' : days === 1 ? 'Ayer' : days < 7 ? 'Esta semana' : 'Anteriores';
		groups.set(label, [...(groups.get(label) ?? []), thread]);
	}
	return order
		.filter((label) => groups.has(label))
		.map((label) => ({ label, threads: groups.get(label)! }));
}

const time = new Intl.DateTimeFormat('es-PE', { hour: 'numeric', minute: '2-digit' });
const weekday = new Intl.DateTimeFormat('es-PE', { weekday: 'long' });
const shortDate = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short' });
const longDate = new Intl.DateTimeFormat('es-PE', {
	weekday: 'long',
	day: 'numeric',
	month: 'long',
});

function capitalize(text: string): string {
	return text.charAt(0).toUpperCase() + text.slice(1);
}

// "10:32" today, "Ayer", "Lunes" this week, "12 oct." before.
export function threadMeta(iso: string, now = new Date()): string {
	const days = daysAgo(iso, now);
	if (days <= 0) return time.format(new Date(iso));
	if (days === 1) return 'Ayer';
	if (days < 7) return capitalize(weekday.format(new Date(iso)));
	return shortDate.format(new Date(iso));
}

// The separator above a day's messages: "Hoy", "Ayer", "Lunes 13 de octubre".
export function dayLabel(iso: string, now = new Date()): string {
	const days = daysAgo(iso, now);
	if (days <= 0) return 'Hoy';
	if (days === 1) return 'Ayer';
	return capitalize(longDate.format(new Date(iso)));
}

export function timeLabel(iso: string): string {
	return time.format(new Date(iso));
}

export function sameDay(a: string, b: string): boolean {
	return startOfDay(new Date(a)) === startOfDay(new Date(b));
}
