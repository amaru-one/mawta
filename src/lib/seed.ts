// Seed data for first load. One course, 28 students, two planned assessments.

import { getCourses, saveAssessment, saveCourse, saveStudent } from './db';
import type { Assessment, Course, Student } from './types';

const COURSE_ID = 'course-math-8b';

const AVATAR_COLORS = ['#0075B4', '#2ECC71', '#E8713B', '#F39C12', '#8E5BA6', '#16A085'];

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
	['Alonso', 'Guzmán']
];

export async function seedIfEmpty(): Promise<string> {
	const existing = await getCourses();
	if (existing.length > 0) return existing[0].id;

	const course: Course = { id: COURSE_ID, name: 'Math 8B' };
	await saveCourse(course);

	const students: Student[] = NAMES.map(([firstName, lastName], i) => ({
		id: `student-${i + 1}`,
		courseId: COURSE_ID,
		firstName,
		lastName,
		avatar: AVATAR_COLORS[i % AVATAR_COLORS.length]
	}));
	await Promise.all(students.map(saveStudent));

	const assessments: Assessment[] = [
		{
			id: 'assessment-quiz-fractions',
			courseId: COURSE_ID,
			name: 'Quiz — fractions',
			type: 'quiz',
			maxScore: 20,
			status: 'planned'
		},
		{
			id: 'assessment-quiz-2',
			courseId: COURSE_ID,
			name: 'Quiz 2',
			type: 'quiz',
			maxScore: 20,
			status: 'planned'
		},
		{
			id: 'assessment-midterm-1',
			courseId: COURSE_ID,
			name: 'Midterm 1',
			type: 'midterm',
			maxScore: 100,
			status: 'planned'
		},
		{
			id: 'assessment-final-1',
			courseId: COURSE_ID,
			name: 'Final Exam',
			type: 'final',
			maxScore: 100,
			status: 'planned'
		}
	];
	await Promise.all(assessments.map(saveAssessment));

	return COURSE_ID;
}
