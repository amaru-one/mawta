"""Functions in schema app (triggers, guards, log_event, events partitions)."""

from alembic_utils.pg_function import PGFunction

check_criterion_capability_competency = PGFunction(
    schema="app",
    signature="check_criterion_capability_competency()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_competency uuid;
  begin
    select ec.competency_id into v_competency
      from evaluation_criteria ec
     where ec.id = new.criterion_id;

    if v_competency is distinct from new.competency_id then
      raise exception 'criterion % belongs to competency %, not %',
        new.criterion_id, v_competency, new.competency_id
        using errcode = 'foreign_key_violation',
              hint = 'Copy the criterion''s competency_id; do not supply your own.';
    end if;
    return new;
  end;
  $function$""",
)

check_criterion_experience = PGFunction(
    schema="app",
    signature="check_criterion_experience()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    if new.experience_id is null then
      return new;
    end if;

    if not exists (
      select 1
        from experience_competencies ec
       where ec.experience_id = new.experience_id
         and ec.competency_id = new.competency_id
         and ec.deleted_at is null
    ) then
      raise exception 'competency % is not worked by experience %',
        new.competency_id, new.experience_id
        using errcode = 'foreign_key_violation',
              hint = 'Link the competency to the experience in experience_competencies first.';
    end if;
    return new;
  end;
  $function$""",
)

check_criterion_has_capability = PGFunction(
    schema="app",
    signature="check_criterion_has_capability()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_criterion uuid;
  begin
    if tg_op = 'DELETE' then
      v_criterion := old.criterion_id;
    else
      v_criterion := new.criterion_id;
    end if;

    -- El criterio pudo haberse eliminado en la misma transacción; no hay nada
    -- que verificar.
    if not exists (select 1 from evaluation_criteria ec
                    where ec.id = v_criterion
                      and ec.deleted_at is null) then
      return null;
    end if;

    if not exists (
      select 1 from evaluation_criterion_capabilities x
       where x.criterion_id = v_criterion
         and x.deleted_at is null
    ) and not exists (
      select 1 from evaluation_criteria ec
       where ec.id = v_criterion
         and ec.deleted_at is null
         and ec.capability_id is not null
    ) then
      raise exception 'criterion % has no capabilities left',
        v_criterion
        using errcode = 'check_violation',
              hint = 'A criterion looks at one or more capabilities of its competency.';
    end if;
    return null;
  end;
  $function$""",
)

check_criterion_has_capability_on_write = PGFunction(
    schema="app",
    signature="check_criterion_has_capability_on_write()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    if new.deleted_at is not null then
      return null;
    end if;

    if not exists (
      select 1 from evaluation_criterion_capabilities x
       where x.criterion_id = new.id
         and x.deleted_at is null
    ) and new.capability_id is null then
      raise exception 'criterion % has no capabilities',
        new.id
        using errcode = 'check_violation',
              hint = 'Insert the criterion and its capabilities in the same transaction.';
    end if;
    return null;
  end;
  $function$""",
)

check_evidence_criterion_experience = PGFunction(
    schema="app",
    signature="check_evidence_criterion_experience()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_evidence_experience  uuid;
    v_criterion_experience uuid;
  begin
    select pe.experience_id into v_evidence_experience
      from planned_evidences pe
     where pe.id = new.evidence_id;

    select ec.experience_id into v_criterion_experience
      from evaluation_criteria ec
     where ec.id = new.criterion_id;

    if v_evidence_experience is null
       or v_criterion_experience is distinct from v_evidence_experience then
      raise exception 'criterion % does not belong to experience %',
        new.criterion_id, v_evidence_experience
        using errcode = 'foreign_key_violation',
              hint = 'A planned evidence observes criteria of its own experience only.';
    end if;
    return new;
  end;
  $function$""",
)

check_experience_competency_subject = PGFunction(
    schema="app",
    signature="check_experience_competency_subject()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_subject uuid;
  begin
    select co.subject_id into v_subject
      from learning_experiences le
      join classes cl on cl.id = le.class_id
      join courses co on co.id = cl.course_id
     where le.id = new.experience_id
       and le.deleted_at is null;

    if not exists (
      select 1 from competencies c
       where c.id = new.competency_id
         and c.deleted_at is null
         and c.subject_id = v_subject
    ) then
      raise exception 'competency % does not belong to the subject of experience %''s class',
        new.competency_id, new.experience_id
        using errcode = 'foreign_key_violation',
              hint = 'An experience works competencies of its class''s subject only.';
    end if;
    return new;
  end;
  $function$""",
)

check_experience_inside_term = PGFunction(
    schema="app",
    signature="check_experience_inside_term()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_term_starts date;
    v_term_ends   date;
  begin
    select t.starts_on, t.ends_on into v_term_starts, v_term_ends
      from terms t
     where t.id = new.term_id
       and t.deleted_at is null;

    if not found then
      raise exception 'term % not found', new.term_id
        using errcode = 'foreign_key_violation';
    end if;

    if new.starts_on < v_term_starts or new.ends_on > v_term_ends then
      raise exception 'experience % (% .. %) falls outside its term (% .. %)',
        new.id, new.starts_on, new.ends_on, v_term_starts, v_term_ends
        using errcode = 'check_violation',
              hint = 'An experience must start and end inside its term.';
    end if;
    return new;
  end;
  $function$""",
)

check_session_entry_date = PGFunction(
    schema="app",
    signature="check_session_entry_date()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_starts date;
    v_ends   date;
  begin
    select le.starts_on, le.ends_on into v_starts, v_ends
      from learning_experiences le
     where le.id = new.experience_id
       and le.deleted_at is null;

    if not found then
      raise exception 'experience % not found', new.experience_id
        using errcode = 'foreign_key_violation';
    end if;

    if new.class_date < v_starts or new.class_date > v_ends then
      raise exception 'session entry date % is outside experience % (% .. %)',
        new.class_date, new.experience_id, v_starts, v_ends
        using errcode = 'check_violation',
              hint = 'A session outline entry must fall inside its experience.';
    end if;
    return new;
  end;
  $function$""",
)

current_actor_id = PGFunction(
    schema="app",
    signature="current_actor_id()",
    definition=r"""RETURNS uuid
 LANGUAGE sql
 STABLE
AS $function$
    select nullif(current_setting('app.actor_id', true), '')::uuid;
  $function$""",
)

ensure_events_partition = PGFunction(
    schema="app",
    signature="ensure_events_partition(p_month date)",
    definition=r"""RETURNS void
 LANGUAGE plpgsql
AS $function$
  declare
    v_start date := date_trunc('month', p_month)::date;
    v_name  text := format('events_%s', to_char(v_start, 'YYYY_MM'));
  begin
    if to_regclass(v_name) is null then
      execute format(
        'create table %I partition of events for values from (%L) to (%L)',
        v_name, v_start, (v_start + interval '1 month')::date);
    end if;
  end;
  $function$""",
)

forbid_event_mutation = PGFunction(
    schema="app",
    signature="forbid_event_mutation()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    raise exception 'events is append-only (attempted % on %)', tg_op, tg_table_name
      using errcode = 'restrict_violation';
  end;
  $function$""",
)

forbid_score_mutation = PGFunction(
    schema="app",
    signature="forbid_score_mutation()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.student_id  is distinct from old.student_id
       or new.status         is distinct from old.status
       or new.raw_value      is distinct from old.raw_value
       or new.max_value      is distinct from old.max_value
       or new.scale_level_id is distinct from old.scale_level_id
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_key is a partial unique index and cannot be deferred, so two live rows for one student and evidence cannot overlap.';
    end if;
    return new;
  end;
  $function$""",
)

forbid_year_close_mutation = PGFunction(
    schema="app",
    signature="forbid_year_close_mutation()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    if tg_table_name = 'competency_year_snapshots' then
      if new.scale_level_id is distinct from old.scale_level_id
         or new.student_id     is distinct from old.student_id
         or new.competency_id  is distinct from old.competency_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.source_term_id is distinct from old.source_term_id then
        raise exception 'competency year snapshot % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'Reopening the year and re-closing it writes a new snapshot; it does not edit this one.';
      end if;
    else
      if new.situation is distinct from old.situation
         or new.student_id is distinct from old.student_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.stage is distinct from old.stage
         or new.breakdown is distinct from old.breakdown then
        raise exception 'year final situation % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'The post-recuperacion determination is a separate row (stage), not an edit of the year-end one.';
      end if;
    end if;
    return new;
  end;
  $function$""",
)

log_event = PGFunction(
    schema="app",
    signature="log_event(p_action text, p_entity_type text, p_entity_id uuid DEFAULT NULL::uuid, p_payload jsonb DEFAULT '{}'::jsonb, p_student_id uuid DEFAULT NULL::uuid, p_class_id uuid DEFAULT NULL::uuid, p_session_id uuid DEFAULT NULL::uuid)",
    definition=r"""RETURNS uuid
 LANGUAGE plpgsql
AS $function$
  declare
    v_id uuid;
  begin
    insert into events (actor_id, action, entity_type, entity_id,
                        student_id, class_id, session_id, payload,
                        request_id)
    values (app.current_actor_id(), p_action, p_entity_type, p_entity_id,
            p_student_id, p_class_id, p_session_id, p_payload,
            nullif(current_setting('app.request_id', true), ''))
    returning id into v_id;
    return v_id;
  end;
  $function$""",
)

set_updated_at = PGFunction(
    schema="app",
    signature="set_updated_at()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    new.updated_at := now();
    return new;
  end;
  $function$""",
)

sync_attendance_denormalised = PGFunction(
    schema="app",
    signature="sync_attendance_denormalised()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    select s.class_id, s.session_date
      into new.class_id, new.session_date
      from class_sessions s
     where s.id = new.session_id;

    if not found then
      raise exception 'session % not found', new.session_id
        using errcode = 'foreign_key_violation';
    end if;
    return new;
  end;
  $function$""",
)

sync_score_denormalised = PGFunction(
    schema="app",
    signature="sync_score_denormalised()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  declare
    v_assessment_status text;
    v_term_status       text;
    v_value_scale       text;
  begin
    select a.class_id, a.term_id, a.status, t.status, a.value_scale
      into new.class_id, new.term_id, v_assessment_status, v_term_status, v_value_scale
      from assessments a
      left join terms t on t.id = a.term_id
     where a.id = new.assessment_id;

    if not found then
      raise exception 'assessment % not found', new.assessment_id
        using errcode = 'foreign_key_violation';
    end if;

    if v_assessment_status = 'draft' then
      raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id
        using errcode = 'check_violation';
    end if;

    -- Un term cerrado deja de aceptar valoraciones. Esto es lo que hace que una libreta
    -- cerrada sea real y no solo una convención. Una evidencia sin term no tiene term que
    -- cerrar, así que la verificación se omite.
    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; scores cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    -- El valor tiene que ser del tipo de la escala de la evidencia.
    if v_value_scale = 'numeric' and new.scale_level_id is not null then
      raise exception 'assessment % is numeric and cannot take a level', new.assessment_id
        using errcode = 'check_violation';
    end if;
    if v_value_scale = 'ordinal' and new.raw_value is not null then
      raise exception 'assessment % is ordinal and cannot take a numeric mark', new.assessment_id
        using errcode = 'check_violation';
    end if;

    return new;
  end;
  $function$""",
)

validate_school_timezone = PGFunction(
    schema="app",
    signature="validate_school_timezone()",
    definition=r"""RETURNS trigger
 LANGUAGE plpgsql
AS $function$
  begin
    if not exists (select 1 from pg_timezone_names where name = new.timezone) then
      raise exception 'unknown IANA timezone %', new.timezone using errcode = 'check_violation';
    end if;
    return new;
  end;
  $function$""",
)

FUNCTIONS = [
    check_criterion_capability_competency,
    check_criterion_experience,
    check_criterion_has_capability,
    check_criterion_has_capability_on_write,
    check_evidence_criterion_experience,
    check_experience_competency_subject,
    check_experience_inside_term,
    check_session_entry_date,
    current_actor_id,
    ensure_events_partition,
    forbid_event_mutation,
    forbid_score_mutation,
    forbid_year_close_mutation,
    log_event,
    set_updated_at,
    sync_attendance_denormalised,
    sync_score_denormalised,
    validate_school_timezone,
]
