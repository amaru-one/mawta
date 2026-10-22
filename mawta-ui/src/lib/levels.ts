// MINEDU achievement-level vocabulary. The client only renders the codes: a
// nivel de logro is asserted by the teacher, never computed from a mark.

export type Tier = 'AD' | 'A' | 'B' | 'C';

export const TIERS: Tier[] = ['AD', 'A', 'B', 'C'];

// The qualification scale as the CNEB names and defines it (Currículo Nacional
// de la Educación Básica, "escala de calificación común a todas las modalidades
// y niveles"). Every level is defined against the expected level of the
// competency, which is why the screen shows the standard next to it.
export const TIER_NAMES: Record<Tier, string> = {
	AD: 'Logro destacado',
	A: 'Logro esperado',
	B: 'En proceso',
	C: 'En inicio',
};

export const TIER_DEFINITIONS: Record<Tier, string> = {
	AD: 'Cuando el estudiante evidencia un nivel superior a lo esperado respecto a la competencia. Esto quiere decir que demuestra aprendizajes que van más allá del nivel esperado.',
	A: 'Cuando el estudiante evidencia el nivel esperado respecto a la competencia, demostrando manejo satisfactorio en todas las tareas propuestas y en el tiempo programado.',
	B: 'Cuando el estudiante está próximo o cerca al nivel esperado respecto a la competencia, para lo cual requiere acompañamiento durante un tiempo razonable para lograrlo.',
	C: 'Cuando el estudiante muestra un progreso mínimo en una competencia de acuerdo al nivel esperado. Evidencia con frecuencia dificultades en el desarrollo de las tareas, por lo que necesita mayor tiempo de acompañamiento e intervención del docente.',
};

// "ciclo_vi" -> "ciclo VI"
export function cycleLabel(cycle: string | null | undefined): string {
	if (!cycle) return 'ciclo';
	return cycle.startsWith('ciclo_') ? `ciclo ${cycle.slice(6).toUpperCase()}` : cycle;
}
