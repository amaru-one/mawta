// Seed data for first load. One course, 28 students, two planned assessments.

import { getCourses, saveAssessment, saveCourse, saveStudent } from './db';
import type { Assessment, Course, Student } from './types';

const COURSE_ID = 'course-math-8b';

const NAMES: Array<[string, string]> = [
	['Ana', 'Morales'],
	['Diego', 'Krause'],
	['Lucía', 'Behrens'],
	['Mateo', 'Silva'],
	['Valentina', 'Rojas'],
	['Tomás', 'Weber'],
	['Camila', 'Fuentes'],
	['Benjamín', 'Ortiz'],
	['Isidora', 'Lagos'],
	['Vicente', 'Paredes'],
	['Emilia', 'Castro'],
	['Joaquín', 'Miranda'],
	['Antonia', 'Vergara'],
	['Gaspar', 'Núñez'],
	['Florencia', 'Reyes'],
	['Agustín', 'Soto'],
	['Josefa', 'Araya'],
	['Maximiliano', 'Pinto'],
	['Catalina', 'Herrera'],
	['Renato', 'Godoy'],
	['Amanda', 'Vidal'],
	['Cristóbal', 'Salazar'],
	['Fernanda', 'Bravo'],
	['Ignacio', 'Tapia'],
	['Martina', 'Carrasco'],
	['Sebastián', 'Leiva'],
	['Trinidad', 'Espinoza'],
	['Alonso', 'Guzmán'],
];

// Student ids are positional and stable, so the prerenderer can enumerate the
// /grades/[studentId] routes without opening IndexedDB.
export const SEEDED_STUDENT_IDS: string[] = NAMES.map((_, i) => `student-${i + 1}`);

export async function seedIfEmpty(): Promise<string> {
	const existing = await getCourses();
	if (existing.length > 0) return existing[0].id;

	const course: Course = { id: COURSE_ID, name: 'Matemática 8B' };
	await saveCourse(course);

	const students: Student[] = NAMES.map(([firstName, lastName], i) => ({
		id: `student-${i + 1}`,
		courseId: COURSE_ID,
		firstName,
		lastName,
	}));
	await Promise.all(students.map(saveStudent));

	const assessments: Assessment[] = [
		{
			id: 'assessment-quiz-fractions',
			courseId: COURSE_ID,
			name: 'Quiz 1 — fracciones',
			type: 'quiz',
			maxScore: 20,
			status: 'planned',
		},
		{
			id: 'assessment-quiz-2',
			courseId: COURSE_ID,
			name: 'Quiz 2',
			type: 'quiz',
			maxScore: 20,
			status: 'planned',
		},
		{
			id: 'assessment-midterm-1',
			courseId: COURSE_ID,
			name: 'Examen parcial',
			type: 'midterm',
			maxScore: 100,
			status: 'planned',
		},
		{
			id: 'assessment-final-1',
			courseId: COURSE_ID,
			name: 'Examen final',
			type: 'final',
			maxScore: 100,
			status: 'planned',
		},
	];
	await Promise.all(assessments.map(saveAssessment));

	return COURSE_ID;
}
