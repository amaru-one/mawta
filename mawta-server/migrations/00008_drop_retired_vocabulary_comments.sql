-- Reescribe ejemplos de comentarios del esquema que citaban vocabulario ya retirado.
-- Solo comentarios: ninguna columna ni restricción cambia.

-- +goose Up
comment on table grading_components is 'Un balde ponderado dentro de un scheme: Participación, Práctica, Examen final. Se lista una fila por componente con su peso y el resultado del estudiante en él.';
comment on table assessments is 'Un ítem calificado para una class: "Tarea 1", "Examen final", "Participación". Se listan bajo EVALUACIONES con el peso del componente junto a cada una. "Añadir evaluación" inserta aquí.';
comment on column assessments.max_score is 'El denominador sobre el que se mide cada score de esta assessment, ej. 20 para una práctica vigesimal. Solo aplica a value_scale = ''numeric''; null cuando value_scale = ''rubric'', que no tiene nota general.';
comment on table assessment_criteria is 'A qué criterios de evaluación habla una evidencia, ej. una "Tarea 1" etiquetada contra dos criterios de "Resuelve problemas de cantidad". criterion_scores_rubric_item_fk (en criterion_scores) es compuesta sobre assessment_criteria_tenant_key, así que una marca por criterio solo puede existir para un par assessment+criterio que esta tabla realmente etiquetó.';
comment on table practice_scores is
  'Un registro personal y no oficial de un docente, creado con "Añadir evaluación" en la pantalla de notas del estudiante. Explícitamente no es una assessment: no lleva componente ni peso, internal/grading nunca lo lee, y nunca llega a computed_grades. Para qué se usa (una práctica de clase, un repaso, lo que sea) depende enteramente del docente.';
comment on column grading_scheme_versions.min_evaluated_weight_for_grade is 'Proporción mínima del peso del term que debe estar evaluada antes de mostrar siquiera una nota parcial. Evita reportar "AD" a partir de una sola práctica con 5% de peso.';
comment on column computed_grade_components.dropped_score_ids is 'Scores removidas por drop-lowest-N. Se conservan para que el docente pueda responder con precisión "por qué mi peor práctica no cuenta".';

-- +goose Down
-- Los comentarios no se restauran.
