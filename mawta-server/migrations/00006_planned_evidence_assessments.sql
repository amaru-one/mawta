-- Puente entre el planeamiento y la evaluación real. Una evidencia planificada
-- (planned_evidences) es una promesa; la evidencia calificable es una
-- assessment. Sin este vínculo, las evidencias de una experiencia nunca
-- llegaban a los alumnos y no se podían evaluar.
--
-- Una experiencia planificada materializa cada evidencia aceptada como una
-- assessment (ver repo.SyncExperience). Esta columna recuerda de cuál
-- evidencia planificada viene, para que la sincronización sea idempotente.

-- +goose Up
alter table assessments
  add column planned_evidence_id uuid;

alter table assessments
  add constraint assessments_planned_evidence_fk
    foreign key (tenant_id, planned_evidence_id)
    references planned_evidences (tenant_id, id);

comment on column assessments.planned_evidence_id is
  'La evidencia planificada de la que esta assessment se materializó al planificar la experiencia. Null para la evidencia registrada a mano. A lo sumo una assessment viva por evidencia planificada (assessments_planned_evidence_key).';

create unique index assessments_planned_evidence_key
  on assessments (planned_evidence_id)
  where planned_evidence_id is not null and deleted_at is null;

-- +goose Down
drop index if exists assessments_planned_evidence_key;
alter table assessments drop constraint if exists assessments_planned_evidence_fk;
alter table assessments drop column if exists planned_evidence_id;
