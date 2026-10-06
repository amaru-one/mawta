import { ApiError } from './client';
import type { DomainErrorCode } from './dto';

// The planning contract's error codes (mawta-server/docs/api-planificacion.md,
// "Domain errors") in the app's own words. Every planning screen goes through
// planningErrorText, so a code reads the same wherever it appears.
const TEXT: Record<DomainErrorCode, string> = {
	experience_overlap: 'Las fechas se cruzan con otra experiencia de esta clase.',
	outside_term: 'La experiencia debe empezar y terminar dentro del periodo.',
	competency_not_in_subject: 'Esa competencia no es del área de esta clase.',
	competency_not_in_experience: 'Esa competencia no está en esta experiencia.',
	competency_has_criteria: 'Esa competencia todavía tiene criterios; quítalos primero.',
	capability_not_in_competency: 'Una de las capacidades no es de esta competencia.',
	criterion_needs_capability: 'Elige al menos una capacidad que mire el criterio.',
	performance_not_in_grade: 'Ese desempeño no es de esta competencia para el grado de la clase.',
	criterion_other_experience: 'Uno de los criterios no es de esta experiencia.',
	date_not_in_experience: 'Esa fecha no es un día de clase de esta experiencia.',
	evidence_not_in_experience: 'Esa evidencia no es de esta experiencia.',
	session_date_taken: 'Esa fecha ya tiene una sesión. Vuelve a cargar la pantalla.',
	experience_not_draft: 'La experiencia ya estaba guardada.',
	missing_title: 'Falta el nombre.',
	missing_idea: 'Cuenta tu idea en una o dos frases.',
	missing_competencies: 'Elige al menos una competencia.',
	missing_description: 'Escribe el criterio.',
	missing_name: 'Falta el nombre de la evidencia.',
	missing_criteria: 'Elige al menos un criterio que observe la evidencia.',
	agent_unavailable: 'Mawta no puede generar en este momento. Puedes escribirlo a mano.',
};

// planningErrorText says what went wrong: the contract code's own text, else
// the server's message (already Spanish), else the screen's fallback.
export function planningErrorText(error: unknown, fallback: string): string {
	if (error instanceof ApiError) {
		const known = TEXT[error.code as DomainErrorCode];
		if (known) return known;
		if (error.status < 500 && error.code !== 'http_error' && error.message) return error.message;
	}
	return fallback;
}

// isAgentUnavailable reports the server's 503: no model configured. The
// screens then hide "✦ Generar con Mawta" and keep manual creation only.
export function isAgentUnavailable(error: unknown): boolean {
	return error instanceof ApiError && error.code === 'agent_unavailable';
}
