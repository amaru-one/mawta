-- Las evidencias materializadas desde el planeamiento se valoran con nota
-- numérica sobre 20, como cualquier otra evidencia de clase. Las que ya existen
-- se habían creado sin nota general y no se podían evaluar.

-- +goose Up
update assessments
   set value_scale = 'numeric', max_score = 20, counts_toward_internal = true
 where planned_evidence_id is not null
   and value_scale = 'rubric'
   and deleted_at is null;

-- +goose Down
-- Sin vuelta atrás: una nota ya registrada contra estas evidencias no puede
-- convertirse en evidencia sin nota general.
