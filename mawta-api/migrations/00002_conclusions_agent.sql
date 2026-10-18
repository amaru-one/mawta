-- Agente de conclusiones descriptivas y barrido de nombres en notas de voz.
--
-- Dos agentes nuevos sobre agent_generations:
--   redaction   (kind voice_note): lee una transcripción con el alumno asignado y
--                la lista de la sección como contexto, y señala cada referencia a
--                una persona. El servidor hace el reemplazo y deja una fila por
--                reemplazo en voice_note_redactions.
--   conclusions (kind conclusion): propone la conclusión descriptiva de un
--                estudiante en una competencia y un periodo, leyendo solo
--                transcripciones ya barridas.

-- +goose Up

-- ---------------------------------------------------------------------------
-- agent_generations: alcance por estudiante, competencia, periodo y nota.
-- ---------------------------------------------------------------------------
alter table agent_generations drop constraint agent_generations_agent_check;
alter table agent_generations
  add constraint agent_generations_agent_check
    check (agent in ('planning', 'redaction', 'conclusions'));

alter table agent_generations
  add column student_id    uuid,
  add column competency_id uuid,
  add column term_id       uuid,
  add column voice_note_id uuid,
  add constraint agent_generations_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  add constraint agent_generations_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  add constraint agent_generations_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  add constraint agent_generations_voice_note_fk foreign key (tenant_id, voice_note_id)
    references voice_notes (tenant_id, id),
  add constraint agent_generations_redaction_kind check (
    agent <> 'redaction' or (kind = 'voice_note' and voice_note_id is not null and student_id is not null)),
  add constraint agent_generations_conclusions_kind check (
    agent <> 'conclusions' or (kind = 'conclusion'
      and student_id is not null and competency_id is not null and term_id is not null));

-- Las conclusiones vigentes o pasadas de un estudiante: "la última propuesta
-- para esta competencia y este periodo".
create index agent_generations_conclusion_scope_idx
  on agent_generations (tenant_id, student_id, competency_id, term_id, created_at desc)
  where agent = 'conclusions';
create index agent_generations_voice_note_idx
  on agent_generations (voice_note_id) where voice_note_id is not null;

comment on table agent_generations is
  'DATOS PERSONALES DE MENORES (vía redaction y conclusions). Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen queda pendiente hasta que el docente lo acepta o lo edita. planning nunca recibe datos de estudiantes ni sugiere niveles de logro. redaction recibe la transcripción de una nota de voz con los nombres de la sección, porque reconocer un nombre mal transcrito o un apodo exige ese contexto; devuelve fragmentos, nunca texto reescrito. conclusions recibe evidencias, el nivel afirmado por el docente y transcripciones ya barridas, con el estudiante seudonimizado como [ESTUDIANTE]; nunca sugiere ni discute el nivel.';
comment on column agent_generations.agent is
  'Qué agente atiende el pedido: planning, redaction (barrido de nombres de una nota de voz) o conclusions (propuesta de conclusión descriptiva).';
comment on column agent_generations.kind is
  'Qué genera, según el agente. planning: experience, criteria, evidences o sessions. redaction: voice_note. conclusions: conclusion.';
comment on column agent_generations.input is
  'Lo que pidió el docente. Solo ids y parámetros: nunca transcripciones ni nombres.';
comment on column agent_generations.result is
  'Lo que hizo una generación completada. planning: la propuesta o los ids insertados como pendientes. redaction: conteos y el estado de atribución resultante. conclusions: la propuesta (body, secciones con citas, avisos), que vive aquí hasta que el docente la guarda como conclusión.';
comment on column agent_generations.student_id is
  'El estudiante sobre el que trabaja una generación de redaction o conclusions. Null en planning.';
comment on column agent_generations.competency_id is
  'La competencia de una generación de conclusions.';
comment on column agent_generations.term_id is
  'El periodo de una generación de conclusions.';
comment on column agent_generations.voice_note_id is
  'La nota de voz que barre una generación de redaction.';

-- ---------------------------------------------------------------------------
-- voice_notes: transcripción barrida y atribución.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- voice_note_redactions: el rastro del barrido.
-- ---------------------------------------------------------------------------
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
comment on column voice_note_redactions.student_id is
  'El estudiante al que estaba asignada la nota cuando se barrió. Si la nota se reasigna, se vuelve a barrer y estas filas quedan superseded.';
comment on column voice_note_redactions.original_text is
  'PII (menor): el fragmento tal como aparece en la transcripción, ej. un nombre mal escrito por la transcripción o un apodo.';
comment on column voice_note_redactions.start_offset is
  'Posición del fragmento en voice_notes.transcript, en caracteres (runas), desde 0.';
comment on column voice_note_redactions.end_offset is
  'Posición final, exclusiva.';
comment on column voice_note_redactions.replacement is
  'La marca que quedó en transcript_redacted: [ESTUDIANTE], [COMPAÑERO_n] o [PERSONA].';
comment on column voice_note_redactions.refers_to is
  'A quién se refiere el fragmento según el barrido: el estudiante asignado, un compañero de la sección, u otra persona (apodo no reconocible, familiar, otro docente).';
comment on column voice_note_redactions.matched_student_id is
  'El compañero de la sección al que el barrido asoció el fragmento. Obligatorio cuando refers_to = classmate.';
comment on column voice_note_redactions.method is
  'Cómo se detectó el fragmento. Por ahora solo model: el barrido lo hace un modelo con el contexto de la sección.';
comment on column voice_note_redactions.generation_id is
  'La generación de redaction que produjo la fila; de ahí salen el modelo y la versión del prompt.';
comment on column voice_note_redactions.superseded_at is
  'Se fija cuando la nota se vuelve a barrer (ej. tras reasignarla). Null significa vigente.';

create index voice_note_redactions_note_idx
  on voice_note_redactions (voice_note_id) where superseded_at is null;

select app.enable_tenant_rls('voice_note_redactions');
select app.attach_updated_at('voice_note_redactions');

-- ---------------------------------------------------------------------------
-- descriptive_conclusions: de qué generación salió el texto.
-- ---------------------------------------------------------------------------
alter table descriptive_conclusions
  add column generation_id uuid,
  add constraint dc_generation_fk foreign key (tenant_id, generation_id)
    references agent_generations (tenant_id, id);

comment on column descriptive_conclusions.generation_id is
  'La generación de conclusions de la que el docente partió al escribir este body, si partió de una. El texto sigue siendo del docente (authored_by_id); esto deja trazable qué leyó el agente para proponerlo.';

-- +goose Down

alter table descriptive_conclusions drop constraint if exists dc_generation_fk;
alter table descriptive_conclusions drop column if exists generation_id;

drop table if exists voice_note_redactions;

drop index if exists voice_notes_attribution_idx;
alter table voice_notes
  drop constraint if exists voice_notes_redacted_consistent,
  drop constraint if exists voice_notes_discard_consistent,
  drop column if exists attribution_checked_at,
  drop column if exists discard_reason,
  drop column if exists attribution_status,
  drop column if exists transcript_redacted;

delete from agent_generations where agent in ('redaction', 'conclusions');
drop index if exists agent_generations_voice_note_idx;
drop index if exists agent_generations_conclusion_scope_idx;
alter table agent_generations
  drop constraint if exists agent_generations_conclusions_kind,
  drop constraint if exists agent_generations_redaction_kind,
  drop constraint if exists agent_generations_voice_note_fk,
  drop constraint if exists agent_generations_term_fk,
  drop constraint if exists agent_generations_competency_fk,
  drop constraint if exists agent_generations_student_fk,
  drop column if exists voice_note_id,
  drop column if exists term_id,
  drop column if exists competency_id,
  drop column if exists student_id;
alter table agent_generations drop constraint agent_generations_agent_check;
alter table agent_generations
  add constraint agent_generations_agent_check check (agent in ('planning'));

comment on table agent_generations is
  'Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen se guarda pendiente (proposed_by = mawta, accepted_at null) hasta que el docente lo acepta o lo edita. Nunca sugieren niveles de logro ni reciben datos de estudiantes en la planificación.';
