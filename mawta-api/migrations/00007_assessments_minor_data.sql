-- Declara assessments en el registro de datos personales.
--
-- assessments.student_id existe desde 00001: una evidencia puede ser de un solo
-- estudiante (por ejemplo, una tarea de recuperación). Esa fila dice algo sobre
-- un menor, pero el comentario de la tabla no la declaraba, así que
-- privacy.minor_data_tables no la listaba y privacy.undeclared_student_references
-- no estaba vacía. Solo cambia el comentario: no toca datos ni bloquea la tabla.

-- +goose Up

comment on table assessments is 'DATOS PERSONALES DE MENORES (académico, cuando student_id está definido). Una evidencia de una class: lo que los estudiantes producen o actúan y que el docente valora contra criterios de evaluación. Nace de una evidencia planificada (planned_evidence_id) o la crea el docente con "Añadir evidencia". Se valora en una sola escala (value_scale) y nunca lleva peso: informa el juicio del docente sobre el nivel de logro de la competencia y no lo calcula. Con student_id definido es evidencia de un solo estudiante, ej. una tarea de recuperación, y por eso la tabla se declara portadora de datos de menores.';

-- +goose Down

comment on table assessments is 'Una evidencia de una class: lo que los estudiantes producen o actúan y que el docente valora contra criterios de evaluación. Nace de una evidencia planificada (planned_evidence_id) o la crea el docente con "Añadir evidencia". Se valora en una sola escala (value_scale) y nunca lleva peso: informa el juicio del docente sobre el nivel de logro de la competencia y no lo calcula.';
