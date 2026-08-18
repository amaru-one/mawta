// MINEDU achievement-level vocabulary. All grade math happens server-side
// (computed_grades, recomputed by the worker); the client only renders codes.

export type Tier = 'AD' | 'A' | 'B' | 'C';

export const TIER_LABELS: Record<Tier, string> = {
	AD: 'Logro destacado',
	A: 'Logro esperado',
	B: 'En proceso',
	C: 'En inicio',
};
