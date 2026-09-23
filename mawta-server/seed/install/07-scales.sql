-- ---------------------------------------------------------------------------
-- Escalas de calificación.
--
-- DOS escalas, y la distinción es normativa, no cosmética:
--
--   * minedu_ad_a_b_c — la escala oficial de la RVM 094-2020. AD/A/B/C son
--     NIVELES DE LOGRO, no notas: no llevan puntaje ni marca de aprobación.
--     Es lo único que va a SIAGIE y lo que guarda competency_term_levels.
--   * vigesimal_0_20 — el sistema interno del colegio. Alimenta el promedio
--     ponderado que Mawta calcula como insumo, y NUNCA es el registro oficial.
--
-- Ninguna columna de esta tabla dice "aprobado": ser competente no se decide
-- con una nota mínima.
-- ---------------------------------------------------------------------------

insert into grade_scales
  (id, tenant_id, code, name, kind, min_value, max_value, decimals)
values
  ('c0000000-0000-4000-8000-000000000070', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'minedu_ad_a_b_c', 'Escala MINEDU AD/A/B/C', 'ordinal', 1, 4, 0),
  ('c0000000-0000-4000-8000-000000000075', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'vigesimal_0_20', 'Sistema interno vigesimal', 'numeric', 0, 20, 0);

-- Las bandas normalizadas son las que usa internal/grading para SUGERIR un
-- nivel a partir del promedio interno. La sugerencia no es el nivel: el
-- docente afirma, y puede apartarse de ella.
insert into grade_scale_levels
  (id, tenant_id, scale_id, code, label, short_label, ordinal,
   min_normalized, max_normalized, color_key)
values
  ('c0000000-0000-4000-8000-000000000074', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000070', 'C',  'En inicio',  'C',  1, 0.00, 0.55, 'rojo'),
  ('c0000000-0000-4000-8000-000000000073', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000070', 'B',  'En proceso', 'B',  2, 0.55, 0.70, 'ambar'),
  ('c0000000-0000-4000-8000-000000000072', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000070', 'A',  'Logro esperado',  'A',  3, 0.70, 0.85, 'verde'),
  ('c0000000-0000-4000-8000-000000000071', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000070', 'AD', 'Logro destacado', 'AD', 4, 0.85, 1.00, 'azul');
