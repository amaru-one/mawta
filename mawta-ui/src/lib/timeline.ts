// Placement for the term timeline. The track is measured in weeks: one unit per
// 7 days counted from the term's first day. Each week is split into equal slots,
// one per class day it holds, so the timeline counts class days and not calendar
// days: consecutive classes touch, and a day without class takes no space.

const DAY_MS = 86400000;

export type NonTeachingKind = 'feriado' | 'vacaciones' | 'gestion';

export type Slot = {
	/** The class day, "YYYY-MM-DD". */
	date: string;
	/** Position on the track, in weeks from the term's first day. */
	start: number;
	end: number;
};

export type Timeline = {
	weekCount: number;
	/** Whether each week holds at least one class day. */
	weekHasClasses: boolean[];
	/** Every class day in the term, in order. */
	slots: Slot[];
};

export type Run = {
	start: number;
	end: number;
	kind: NonTeachingKind;
	label: string | null;
};

export type NonTeachingRange = {
	from: string;
	to: string;
	kind: NonTeachingKind;
	label: string | null;
};

// "YYYY-MM-DD" → whole days since the Unix epoch. UTC keeps DST out of the count.
function dayNumber(date: string): number {
	const [y, m, d] = date.split('-').map(Number);
	return Math.round(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) / DAY_MS);
}

function isoOf(dayNo: number): string {
	const date = new Date(dayNo * DAY_MS);
	const m = String(date.getUTCMonth() + 1).padStart(2, '0');
	const d = String(date.getUTCDate()).padStart(2, '0');
	return `${date.getUTCFullYear()}-${m}-${d}`;
}

// The class days of each week. The schedule decides them, feriados included; if
// the schedule is missing, Monday to Friday stands in so the timeline still draws.
export function buildTimeline(
	termStart: string,
	termEnd: string,
	scheduled: string[] | null | undefined
): Timeline {
	const first = dayNumber(termStart);
	const last = dayNumber(termEnd);
	const weekCount = Math.floor((last - first) / 7) + 1;

	const meets = new Set<string>();
	if (scheduled && scheduled.length > 0) {
		for (const date of scheduled) meets.add(date);
	} else {
		for (let day = first; day <= last; day++) {
			const weekday = new Date(day * DAY_MS).getUTCDay();
			if (weekday >= 1 && weekday <= 5) meets.add(isoOf(day));
		}
	}

	const slots: Slot[] = [];
	const weekHasClasses: boolean[] = [];
	for (let week = 0; week < weekCount; week++) {
		const days: string[] = [];
		for (let offset = week * 7; offset < week * 7 + 7; offset++) {
			const day = isoOf(first + offset);
			if (first + offset <= last && meets.has(day)) days.push(day);
		}
		weekHasClasses.push(days.length > 0);
		days.forEach((date, index) => {
			slots.push({
				date,
				start: week + index / days.length,
				end: week + (index + 1) / days.length,
			});
		});
	}
	return { weekCount, weekHasClasses, slots };
}

// The track span of a stretch of dates: from the first class day in it to the
// last one. Days without class at either end are skipped. Null when no class day
// falls inside, so the experience has nothing to draw.
export function spanOf(
	timeline: Timeline,
	from: string,
	to: string
): { start: number; end: number } | null {
	const inside = timeline.slots.filter((slot) => slot.date >= from && slot.date <= to);
	const head = inside[0];
	const tail = inside[inside.length - 1];
	if (!head || !tail) return null;
	return { start: head.start, end: tail.end };
}

// Runs of class days taken by a non-teaching range, merged into one block while
// consecutive class days share a kind and label. A range that holds no class day
// draws nothing.
export function offRuns(timeline: Timeline, ranges: NonTeachingRange[]): Run[] {
	const runs: Run[] = [];
	let current: Run | null = null;
	for (const slot of timeline.slots) {
		const range = ranges.find((item) => slot.date >= item.from && slot.date <= item.to);
		if (!range) {
			current = null;
			continue;
		}
		if (current && current.kind === range.kind && current.label === range.label) {
			current.end = slot.end;
			continue;
		}
		current = { start: slot.start, end: slot.end, kind: range.kind, label: range.label };
		runs.push(current);
	}
	return runs;
}

// A track position in weeks, as a percentage of the whole track.
export function percentOf(weeks: number, weekCount: number): number {
	return (weeks / weekCount) * 100;
}
