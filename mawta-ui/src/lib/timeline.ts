// Day-level placement for the term timeline. Days are counted as whole numbers
// from the term's first day, so a bar can start and end on any day, not only on
// a week boundary.

const DAY_MS = 86400000;

// "YYYY-MM-DD" → whole days since the Unix epoch. UTC keeps DST out of the count.
function dayNumber(date: string): number {
	const [y, m, d] = date.split('-').map(Number);
	return Math.round(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) / DAY_MS);
}

// Days from the term's first day to `date`; 0 is the first day.
export function dayOffset(termStart: string, date: string): number {
	return dayNumber(date) - dayNumber(termStart);
}

// Where a span of days sits on a track of `totalDays`, as percentages.
// Both ends are inclusive and are clamped to the track.
export function spanPercent(
	startDay: number,
	endDay: number,
	totalDays: number
): { left: number; width: number } {
	const first = Math.min(Math.max(startDay, 0), totalDays - 1);
	const last = Math.min(Math.max(endDay, first), totalDays - 1);
	return {
		left: (first / totalDays) * 100,
		width: ((last - first + 1) / totalDays) * 100,
	};
}
