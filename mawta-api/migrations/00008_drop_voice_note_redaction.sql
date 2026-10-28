-- Elimina el barrido de nombres de las notas de voz (D004: IA local, sin seudónimos).
--
-- El agente redaction existía para que el agente de conclusiones no enviara
-- nombres de alumnos a un proveedor externo. Con los modelos corriendo en el
-- colegio deja de tener sentido: conclusiones lee la transcripción tal cual y
-- el guard de salida sigue impidiendo que la conclusión nombre a alguien.
--
-- También vacía el historial del chat del director: los hilos de prueba se
-- guardaron en el formato de Anthropic y el chat pasa al formato compatible
-- con OpenAI. Los checkpoints viejos de LangGraph quedan huérfanos y nunca se
-- vuelven a leer.

-- +goose Up

drop table voice_note_redactions;

delete from agent_generations where agent = 'redaction';
drop index agent_generations_voice_note_idx;
alter table agent_generations
  drop constraint agent_generations_redaction_kind,
  drop constraint agent_generations_voice_note_fk,
  drop column voice_note_id;
alter table agent_generations drop constraint agent_generations_agent_check;
alter table agent_generations
  add constraint agent_generations_agent_check check (agent in ('planning', 'conclusions'));

comment on table agent_generations is
  'DATOS PERSONALES DE MENORES (vía conclusions). Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen queda pendiente hasta que el docente lo acepta o lo edita. planning nunca recibe datos de estudiantes ni sugiere niveles de logro. conclusions recibe evidencias, el nivel afirmado por el docente y las transcripciones de las notas de voz; nunca sugiere ni discute el nivel.';
comment on column agent_generations.agent is
  'Qué agente atiende el pedido: planning o conclusions (propuesta de conclusión descriptiva).';
comment on column agent_generations.kind is
  'Qué genera, según el agente. planning: experience, criteria, evidences o sessions. conclusions: conclusion.';
comment on column agent_generations.result is
  'Lo que hizo una generación completada. planning: la propuesta o los ids insertados como pendientes. conclusions: la propuesta (body, secciones con citas, avisos), que vive aquí hasta que el docente la guarda como conclusión.';
comment on column agent_generations.student_id is
  'El estudiante sobre el que trabaja una generación de conclusions. Null en planning.';

drop index voice_notes_attribution_idx;
alter table voice_notes
  drop constraint voice_notes_redacted_consistent,
  drop constraint voice_notes_discard_consistent,
  drop column attribution_checked_at,
  drop column discard_reason,
  drop column attribution_status,
  drop column transcript_redacted;

-- chat.messages y chat.question_bank se borran en cascada.
delete from chat.threads;

-- +goose Down

alter table voice_notes
  add column transcript_redacted    text,
  add column attribution_status     text not null default 'pending'
    check (attribution_status in ('pending', 'ok', 'discarded', 'confirmed', 'reassigned')),
  add column discard_reason         text
    check (discard_reason in ('mentions_other_student', 'unreadable')),
  add column attribution_checked_at timestamptz,
  add constraint voice_notes_discard_consistent
    check ((attribution_status = 'discarded') = (discard_reason is not null)),
  add constraint voice_notes_redacted_consistent
    check (attribution_status not in ('ok', 'confirmed', 'reassigned') or transcript_redacted is not null);

comment on column voice_notes.transcript_redacted is
  'PII (menor): la transcripción después del barrido de nombres: el estudiante asignado es [ESTUDIANTE], los compañeros de la sección [COMPAÑERO_n] y cualquier otra persona [PERSONA]. Es lo único que lee el agente de conclusiones. Sigue siendo habla libre sobre un menor.';
comment on column voice_notes.attribution_status is
  'Si la nota se puede usar como evidencia del estudiante asignado. pending: aún no se barre. ok: barrida y atribuida. discarded: el barrido indica que no es de este estudiante o no se entiende (ver discard_reason); queda fuera de las conclusiones sin preguntarle al docente. confirmed: el docente dijo que sí es de este estudiante. reassigned: el docente la movió a otro estudiante y se volvió a barrer.';
comment on column voice_notes.discard_reason is
  'Por qué se descartó. mentions_other_student: nombra solo a compañeros de la sección y nunca al estudiante asignado. unreadable: la transcripción está vacía o no tiene sentido.';
comment on column voice_notes.attribution_checked_at is
  'Cuándo se fijó attribution_status por última vez.';

create index voice_notes_attribution_idx
  on voice_notes (student_id, attribution_status) where deleted_at is null;

alter table agent_generations drop constraint agent_generations_agent_check;
alter table agent_generations
  add constraint agent_generations_agent_check
    check (agent in ('planning', 'redaction', 'conclusions'));
alter table agent_generations
  add column voice_note_id uuid,
  add constraint agent_generations_voice_note_fk foreign key (tenant_id, voice_note_id)
    references voice_notes (tenant_id, id),
  add constraint agent_generations_redaction_kind check (
    agent <> 'redaction' or (kind = 'voice_note' and voice_note_id is not null and student_id is not null));
create index agent_generations_voice_note_idx
  on agent_generations (voice_note_id) where voice_note_id is not null;

comment on table agent_generations is
  'DATOS PERSONALES DE MENORES (vía redaction y conclusions). Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen queda pendiente hasta que el docente lo acepta o lo edita. planning nunca recibe datos de estudiantes ni sugiere niveles de logro. redaction recibe la transcripción de una nota de voz con los nombres de la sección, porque reconocer un nombre mal transcrito o un apodo exige ese contexto; devuelve fragmentos, nunca texto reescrito. conclusions recibe evidencias, el nivel afirmado por el docente y transcripciones ya barridas, con el estudiante seudonimizado como [ESTUDIANTE]; nunca sugiere ni discute el nivel.';
comment on column agent_generations.agent is
  'Qué agente atiende el pedido: planning, redaction (barrido de nombres de una nota de voz) o conclusions (propuesta de conclusión descriptiva).';
comment on column agent_generations.kind is
  'Qué genera, según el agente. planning: experience, criteria, evidences o sessions. redaction: voice_note. conclusions: conclusion.';
comment on column agent_generations.result is
  'Lo que hizo una generación completada. planning: la propuesta o los ids insertados como pendientes. redaction: conteos y el estado de atribución resultante. conclusions: la propuesta (body, secciones con citas, avisos), que vive aquí hasta que el docente la guarda como conclusión.';
comment on column agent_generations.student_id is
  'El estudiante sobre el que trabaja una generación de redaction o conclusions. Null en planning.';
comment on column agent_generations.voice_note_id is
  'La nota de voz que barre una generación de redaction.';

create table voice_note_redactions (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  voice_note_id       uuid not null,
  generation_id       uuid not null,
  student_id          uuid not null,
  original_text       text not null,
  start_offset        integer not null check (start_offset >= 0),
  end_offset          integer not null,
  replacement         text not null,
  refers_to           text not null
                        check (refers_to in ('assigned_student', 'classmate', 'other_person')),
  matched_student_id  uuid,
  method              text not null default 'model' check (method in ('model')),
  superseded_at       timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint voice_note_redactions_tenant_id_key unique (tenant_id, id),
  constraint voice_note_redactions_voice_note_fk foreign key (tenant_id, voice_note_id)
    references voice_notes (tenant_id, id),
  constraint voice_note_redactions_generation_fk foreign key (tenant_id, generation_id)
    references agent_generations (tenant_id, id),
  constraint voice_note_redactions_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint voice_note_redactions_matched_student_fk foreign key (tenant_id, matched_student_id)
    references students (tenant_id, id),
  constraint voice_note_redactions_offsets check (end_offset > start_offset),
  constraint voice_note_redactions_classmate_matched
    check ((refers_to = 'classmate') <= (matched_student_id is not null))
);

comment on table voice_note_redactions is
  'DATOS PERSONALES DE MENORES (nombres dentro de notas de voz). Una fila por cada reemplazo que hizo el barrido en una transcripción: qué texto original, en qué posición, por qué marca se cambió y a quién se asoció. Existe para que una persona pueda revisar, con una consulta, cada decisión del barrido comparando transcript con transcript_redacted. El modelo solo señala fragmentos; el servidor calcula las posiciones y hace el reemplazo.';
comment on column voice_note_redactions.original_text is
  'PII (menor): el fragmento tal como aparece en la transcripción, ej. un nombre mal escrito por la transcripción o un apodo.';

create index voice_note_redactions_note_idx
  on voice_note_redactions (voice_note_id) where superseded_at is null;

select app.enable_tenant_rls('voice_note_redactions');
select app.attach_updated_at('voice_note_redactions');
