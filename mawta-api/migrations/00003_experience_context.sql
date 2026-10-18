-- Evento o contexto que escribe el docente al crear una experiencia.
--
-- Es la única fuente permitida de un evento (feria, aniversario, campaña...) en lo
-- que genera el agente de planificación. Opcional: las experiencias existentes
-- quedan sin contexto, y el agente no puede inventar eventos en ellas.

-- +goose Up

alter table learning_experiences add column context_text text;

comment on column learning_experiences.context_text is
  'Evento o contexto que escribe el docente. Única fuente permitida de un evento en lo que genera el agente; nulo = ningún evento.';

-- +goose Down

alter table learning_experiences drop column if exists context_text;
