import type { AssessmentKind } from '$lib/api/dto';

// The two kinds of evidencia the norm names, in the teacher's words:
// "producciones y/o actuaciones realizadas por los estudiantes" (RVM 094-2020,
// glosario p.9). One map for every screen, so a kind reads the same in the plan,
// in "Añadir evidencia" and on the student.
export const EVIDENCE_KIND_LABEL: Record<AssessmentKind, string> = {
	produccion: 'Producción',
	actuacion: 'Actuación',
};

export const EVIDENCE_KINDS = Object.keys(EVIDENCE_KIND_LABEL) as AssessmentKind[];
