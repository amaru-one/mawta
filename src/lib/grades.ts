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
};

export type GradeSummary = {
	percent: number;
	letter: string;
	components: ComponentGrade[];
};

const LETTER_THRESHOLDS: Array<[number, string]> = [
	[90, 'A'],
	[80, 'B'],
	[70, 'C'],
	[60, 'D'],
	[0, 'F'],
];

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

export function gradeFor(
	studentId: string,
	scores: Map<string, Score>,
	assessments: Assessment[]
): GradeSummary {
	const components = formula.components.map((component) => {
		const maxValue = maxValueFor(component, assessments);
		const saved = scores.get(scoreKey(studentId, component.id));
		const rawValue =
			saved?.value ?? Math.round((mockPercentFor(studentId, component.id) / 100) * maxValue);
		const score = maxValue > 0 ? Math.round((rawValue / maxValue) * 100) : 0;
		return { component, rawValue, maxValue, score };
	});

	const totalWeight = formula.components.reduce((sum, c) => sum + c.weight, 0);
	const weightedSum = components.reduce((sum, c) => sum + c.score * c.component.weight, 0);
	const percent = totalWeight > 0 ? Math.round(weightedSum / totalWeight) : 0;
	const letter = LETTER_THRESHOLDS.find(([min]) => percent >= min)?.[1] ?? 'F';

	return { percent, letter, components };
}

export async function loadScoresForStudent(studentId: string): Promise<void> {
	const saved = await db.getScores(studentId);
	scoresStore.update((map) => {
		const next = new Map(map);
		for (const score of saved) {
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
		record = { id: existing?.id ?? uid(), studentId, componentId, value };
		const next = new Map(map);
		next.set(key, record);
		return next;
	});
	void db.saveScore(record);
}
