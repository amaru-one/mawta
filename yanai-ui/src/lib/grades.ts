// Grade computation and score persistence. The formula (weights, components)
// comes from grade-formula.json — in the real system this would be served by
// the backend. Scores are teacher-entered and persisted to IndexedDB; any
// component the teacher hasn't scored yet falls back to a stable mock value
// (hashed per student+component) as placeholder sample data.

import * as db from './db';
import gradeFormula from './grade-formula.json';
import { scoreKey, scores as scoresStore } from './stores';
import type { Assessment, GradeComponent, GradeFormula, Score } from './types';

const formula = gradeFormula as GradeFormula;

export type ComponentGrade = {
	component: GradeComponent;
	rawValue: number; // raw points for 'assessment' components; 0-100 percent for 'participation'
	maxValue: number; // assessment.maxScore, or 100 for 'participation'
	score: number; // rawValue normalized to 0-100
	scored: boolean; // false when still showing placeholder sample data
};

// MINEDU achievement tiers. AD = logro destacado, A = logro esperado,
// B = en proceso, C = en inicio.
export type Tier = 'AD' | 'A' | 'B' | 'C';

export type GradeSummary = {
	percent: number;
	tier: Tier;
	label: string;
	components: ComponentGrade[];
};

// Cutoffs are a product decision, kept in one place so they stay tunable.
export const TIER_THRESHOLDS: Array<[number, Tier]> = [
	[90, 'AD'],
	[70, 'A'],
	[55, 'B'],
	[0, 'C'],
];

export const TIER_LABELS: Record<Tier, string> = {
	AD: 'Logro destacado',
	A: 'Logro esperado',
	B: 'En proceso',
	C: 'En inicio',
};

// Low to high — used to work out whether a trend is up or down.
const TIER_ORDER: Tier[] = ['C', 'B', 'A', 'AD'];

export const tierFor = (percent: number): Tier =>
	TIER_THRESHOLDS.find(([min]) => percent >= min)?.[1] ?? 'C';

const uid = (): string =>
	typeof crypto !== 'undefined' && 'randomUUID' in crypto
		? crypto.randomUUID()
		: `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;

function hashString(value: string): number {
	let hash = 0;
	for (let i = 0; i < value.length; i++) {
		hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
	}
	return hash;
}

function mockPercentFor(studentId: string, componentId: string): number {
	return 55 + (hashString(`${studentId}:${componentId}`) % 46); // stable range: 55-100
}

function maxValueFor(component: GradeComponent, assessments: Assessment[]): number {
	if (component.source === 'participation') return 100;
	return assessments.find((a) => a.id === component.assessmentId)?.maxScore ?? 100;
}

// `ignoreComponentId` lets the caller recompute the grade as it stood before a
// given component was scored — see trendFor.
function summarize(
	studentId: string,
	scores: Map<string, Score>,
	assessments: Assessment[],
	ignoreComponentId?: string
): GradeSummary {
	const components = formula.components.map((component) => {
		const maxValue = maxValueFor(component, assessments);
		const saved =
			component.id === ignoreComponentId
				? undefined
				: scores.get(scoreKey(studentId, component.id));
		const rawValue =
			saved?.value ?? Math.round((mockPercentFor(studentId, component.id) / 100) * maxValue);
		const score = maxValue > 0 ? Math.round((rawValue / maxValue) * 100) : 0;
		return { component, rawValue, maxValue, score, scored: saved !== undefined };
	});

	const totalWeight = formula.components.reduce((sum, c) => sum + c.weight, 0);
	const weightedSum = components.reduce((sum, c) => sum + c.score * c.component.weight, 0);
	const percent = totalWeight > 0 ? Math.round(weightedSum / totalWeight) : 0;
	const tier = tierFor(percent);

	return { percent, tier, label: TIER_LABELS[tier], components };
}

export function gradeFor(
	studentId: string,
	scores: Map<string, Score>,
	assessments: Assessment[]
): GradeSummary {
	return summarize(studentId, scores, assessments);
}

export type Trend = {
	from: Tier;
	to: Tier;
	direction: 'up' | 'down';
};

// The tier the student held before their most recently edited score, when that
// edit actually moved them. Returns null if nothing has been scored yet, or if
// the last edit left the tier unchanged.
export function trendFor(
	studentId: string,
	scores: Map<string, Score>,
	assessments: Assessment[]
): Trend | null {
	let latest: Score | null = null;
	for (const component of formula.components) {
		const saved = scores.get(scoreKey(studentId, component.id));
		if (!saved) continue;
		if (!latest || (saved.updatedAt ?? 0) > (latest.updatedAt ?? 0)) latest = saved;
	}
	if (!latest) return null;

	const to = summarize(studentId, scores, assessments).tier;
	const from = summarize(studentId, scores, assessments, latest.componentId).tier;
	if (from === to) return null;

	return {
		from,
		to,
		direction: TIER_ORDER.indexOf(to) > TIER_ORDER.indexOf(from) ? 'up' : 'down',
	};
}

export async function loadScoresForStudent(studentId: string): Promise<void> {
	await loadScoresForStudents([studentId]);
}

// The roster needs every student's tier at once.
export async function loadScoresForStudents(studentIds: string[]): Promise<void> {
	const saved = await Promise.all(studentIds.map((id) => db.getScores(id)));
	scoresStore.update((map) => {
		const next = new Map(map);
		for (const score of saved.flat()) {
			next.set(scoreKey(score.studentId, score.componentId), score);
		}
		return next;
	});
}

export function saveScore(studentId: string, componentId: string, value: number): void {
	const key = scoreKey(studentId, componentId);
	let record!: Score;
	scoresStore.update((map) => {
		const existing = map.get(key);
		record = { id: existing?.id ?? uid(), studentId, componentId, value, updatedAt: Date.now() };
		const next = new Map(map);
		next.set(key, record);
		return next;
	});
	void db.saveScore(record);
}
