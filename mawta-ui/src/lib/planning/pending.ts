import type { ExperienceDto } from '$lib/api/dto';

export interface PendingCounts {
	criteria: number;
	evidences: number;
	sessions: number;
	total: number;
}

// Mawta proposals are items with no accepted_at yet. Counted per step from the
// lists the experience already carries, so each step can say what it still owes.
export function pendingCounts(
	experience: Pick<ExperienceDto, 'criteria' | 'evidences' | 'sessions'> | null | undefined
): PendingCounts {
	const criteria = (experience?.criteria ?? []).filter((c) => c.accepted_at === null).length;
	const evidences = (experience?.evidences ?? []).filter((e) => e.accepted_at === null).length;
	const sessions = (experience?.sessions ?? []).filter((s) => s.accepted_at === null).length;
	return { criteria, evidences, sessions, total: criteria + evidences + sessions };
}
