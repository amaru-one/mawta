-- Amplía el CHECK de grade_levels.cycle para aceptar los ciclos de primaria
-- y secundaria de la EBR. La columna existía para los ciclos I y II de
-- inicial; el catálogo CNEB (cneb.json) trae el ciclo de cada grado, y el
-- onboarding ahora lo copia a grade_levels.cycle.
--
-- Solo se amplía el CHECK: no se rellena (backfill) nada a partir de los
-- ordinales, porque adivinar el ciclo de un grado existente es exactamente
-- el tipo de suposición curricular que este proyecto no hace. Los colegios
-- existentes reciben su ciclo del sync explícito (cmd/onboard -sync), que
-- parte de un mapa grado → grado_cneb declarado, no inferido.

-- +goose Up
ALTER TABLE grade_levels DROP CONSTRAINT grade_levels_cycle_check;
ALTER TABLE grade_levels ADD CONSTRAINT grade_levels_cycle_check
  CHECK (cycle IS NULL OR cycle IN ('ciclo_i', 'ciclo_ii', 'ciclo_iii', 'ciclo_iv', 'ciclo_v', 'ciclo_vi', 'ciclo_vii'));

-- +goose Down
ALTER TABLE grade_levels DROP CONSTRAINT grade_levels_cycle_check;
ALTER TABLE grade_levels ADD CONSTRAINT grade_levels_cycle_check
  CHECK (cycle IS NULL OR cycle IN ('ciclo_i', 'ciclo_ii'));
