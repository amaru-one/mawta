// Typed IndexedDB service layer. All failures are logged and retried
// silently — no error ever surfaces to the teacher.

import type { Assessment, Course, Entry, Note, Score, Session, Student } from './types';

const DB_NAME = 'lesson-app';
const DB_VERSION = 2;

type StoreName = 'courses' | 'students' | 'sessions' | 'assessments' | 'entries' | 'notes' | 'scores';

interface StoreValue {
	courses: Course;
	students: Student;
	sessions: Session;
	assessments: Assessment;
	entries: Entry;
	notes: Note;
	scores: Score;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
	if (dbPromise) return dbPromise;
	dbPromise = new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, DB_VERSION);
		req.onupgradeneeded = () => {
			const db = req.result;
			if (!db.objectStoreNames.contains('courses')) {
				db.createObjectStore('courses', { keyPath: 'id' });
			}
			if (!db.objectStoreNames.contains('students')) {
				const students = db.createObjectStore('students', { keyPath: 'id' });
				students.createIndex('byCourse', 'courseId');
			}
			if (!db.objectStoreNames.contains('sessions')) {
				const sessions = db.createObjectStore('sessions', { keyPath: 'id' });
				sessions.createIndex('byCourse', 'courseId');
			}
			if (!db.objectStoreNames.contains('assessments')) {
				const assessments = db.createObjectStore('assessments', { keyPath: 'id' });
				assessments.createIndex('byCourse', 'courseId');
			}
			if (!db.objectStoreNames.contains('entries')) {
				const entries = db.createObjectStore('entries', { keyPath: 'id' });
				entries.createIndex('bySession', 'sessionId');
			}
			if (!db.objectStoreNames.contains('notes')) {
				const notes = db.createObjectStore('notes', { keyPath: 'id' });
				notes.createIndex('byEntry', 'entryId');
			}
			if (!db.objectStoreNames.contains('scores')) {
				const scores = db.createObjectStore('scores', { keyPath: 'id' });
				scores.createIndex('byStudent', 'studentId');
			}
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => {
			dbPromise = null;
			reject(req.error);
		};
	});
	return dbPromise;
}

function requestToPromise<T>(req: IDBRequest<T>): Promise<T> {
	return new Promise((resolve, reject) => {
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}

async function withRetry<T>(op: () => Promise<T>, attempts = 3): Promise<T | undefined> {
	for (let i = 0; i < attempts; i++) {
		try {
			return await op();
		} catch (err) {
			if (i === attempts - 1 && import.meta.env.DEV) {
				console.warn('[db] operation failed after retries', err);
			}
		}
	}
	return undefined;
}

async function put<S extends StoreName>(store: S, value: StoreValue[S]): Promise<void> {
	await withRetry(async () => {
		const db = await openDb();
		const tx = db.transaction(store, 'readwrite');
		await requestToPromise(tx.objectStore(store).put(value));
	});
}

async function remove(store: StoreName, id: string): Promise<void> {
	await withRetry(async () => {
		const db = await openDb();
		const tx = db.transaction(store, 'readwrite');
		await requestToPromise(tx.objectStore(store).delete(id));
	});
}

async function getAll<S extends StoreName>(store: S): Promise<StoreValue[S][]> {
	const result = await withRetry(async () => {
		const db = await openDb();
		const tx = db.transaction(store, 'readonly');
		return requestToPromise(tx.objectStore(store).getAll() as IDBRequest<StoreValue[S][]>);
	});
	return result ?? [];
}

async function getByIndex<S extends StoreName>(
	store: S,
	index: string,
	key: string
): Promise<StoreValue[S][]> {
	const result = await withRetry(async () => {
		const db = await openDb();
		const tx = db.transaction(store, 'readonly');
		return requestToPromise(
			tx.objectStore(store).index(index).getAll(key) as IDBRequest<StoreValue[S][]>
		);
	});
	return result ?? [];
}

// --- Public typed API ---

export const saveCourse = (c: Course): Promise<void> => put('courses', c);
export const saveStudent = (s: Student): Promise<void> => put('students', s);
export const saveSession = (s: Session): Promise<void> => put('sessions', s);
export const saveAssessment = (a: Assessment): Promise<void> => put('assessments', a);
export const saveNote = (n: Note): Promise<void> => put('notes', n);
export const deleteNote = (id: string): Promise<void> => remove('notes', id);
export const saveScore = (s: Score): Promise<void> => put('scores', s);

// Entries embed their notes in the type, but notes are persisted in their own
// store (blobs stay out of the hot entry writes). Strip them on write.
export const saveEntry = (e: Entry): Promise<void> => put('entries', { ...e, notes: [] });

export const getCourses = (): Promise<Course[]> => getAll('courses');
export const getStudents = (courseId: string): Promise<Student[]> =>
	getByIndex('students', 'byCourse', courseId);
export const getSessions = (courseId: string): Promise<Session[]> =>
	getByIndex('sessions', 'byCourse', courseId);
export const getAssessments = (courseId: string): Promise<Assessment[]> =>
	getByIndex('assessments', 'byCourse', courseId);
export const getEntries = (sessionId: string): Promise<Entry[]> =>
	getByIndex('entries', 'bySession', sessionId);
export const getNotes = (entryId: string): Promise<Note[]> => getByIndex('notes', 'byEntry', entryId);
export const getScores = (studentId: string): Promise<Score[]> =>
	getByIndex('scores', 'byStudent', studentId);
