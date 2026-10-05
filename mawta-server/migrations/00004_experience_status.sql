-- Estado de una experiencia de aprendizaje: borrador mientras el docente la
-- arma paso a paso, planificada cuando la confirma en "Revisar y guardar"
-- (contrato docs/api-planificacion.md, decisión 1: se guarda paso a paso).
--
-- La restricción de no solapamiento (learning_experiences_no_overlap) no mira
-- el estado: dos borradores tampoco pueden ocupar las mismas semanas.

-- +goose Up
alter table learning_experiences
  add column status text not null default 'borrador'
    check (status in ('borrador', 'planificada'));

comment on column learning_experiences.status is
  'borrador: la experiencia se está armando y cada paso ya quedó guardado. planificada: el docente la confirmó en "Revisar y guardar". El solapamiento de fechas se exige en ambos estados, así que un borrador también reserva sus semanas.';

-- +goose Down
alter table learning_experiences drop column if exists status;
