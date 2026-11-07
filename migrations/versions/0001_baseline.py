# pyright: reportAttributeAccessIssue=false
# (alembic_utils adds op.create_entity / op.drop_entity at runtime, so pyright cannot see them.)
"""Baseline: the single-school schema (no tenants), replacing the goose migrations.

Revision ID: 0001
Revises:
Create Date: 2026-11-05

Built from goose migrations 00001-00009 with multi-tenancy removed: no tenant_id, the tenants
table is now the one-row school table, RLS only keeps owner_only on the chat tables (now
permissive), and the chat_api views no longer join on tenant_id.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic_utils.pg_function import PGFunction
from alembic_utils.pg_policy import PGPolicy
from alembic_utils.pg_trigger import PGTrigger
from alembic_utils.pg_view import PGView
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

app_check_criterion_capability_competency = PGFunction(
    schema="app",
    signature="check_criterion_capability_competency()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_competency uuid;\n  begin\n    select ec.competency_id into v_competency\n      from evaluation_criteria ec\n     where ec.id = new.criterion_id;\n\n    if v_competency is distinct from new.competency_id then\n      raise exception 'criterion % belongs to competency %, not %',\n        new.criterion_id, v_competency, new.competency_id\n        using errcode = 'foreign_key_violation',\n              hint = 'Copy the criterion''s competency_id; do not supply your own.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_check_criterion_experience = PGFunction(
    schema="app",
    signature="check_criterion_experience()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    if new.experience_id is null then\n      return new;\n    end if;\n\n    if not exists (\n      select 1\n        from experience_competencies ec\n       where ec.experience_id = new.experience_id\n         and ec.competency_id = new.competency_id\n         and ec.deleted_at is null\n    ) then\n      raise exception 'competency % is not worked by experience %',\n        new.competency_id, new.experience_id\n        using errcode = 'foreign_key_violation',\n              hint = 'Link the competency to the experience in experience_competencies first.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_check_criterion_has_capability = PGFunction(
    schema="app",
    signature="check_criterion_has_capability()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_criterion uuid;\n  begin\n    if tg_op = 'DELETE' then\n      v_criterion := old.criterion_id;\n    else\n      v_criterion := new.criterion_id;\n    end if;\n\n    -- El criterio pudo haberse eliminado en la misma transacción; no hay nada\n    -- que verificar.\n    if not exists (select 1 from evaluation_criteria ec\n                    where ec.id = v_criterion\n                      and ec.deleted_at is null) then\n      return null;\n    end if;\n\n    if not exists (\n      select 1 from evaluation_criterion_capabilities x\n       where x.criterion_id = v_criterion\n         and x.deleted_at is null\n    ) and not exists (\n      select 1 from evaluation_criteria ec\n       where ec.id = v_criterion\n         and ec.deleted_at is null\n         and ec.capability_id is not null\n    ) then\n      raise exception 'criterion % has no capabilities left',\n        v_criterion\n        using errcode = 'check_violation',\n              hint = 'A criterion looks at one or more capabilities of its competency.';\n    end if;\n    return null;\n  end;\n  $function$",
)

app_check_criterion_has_capability_on_write = PGFunction(
    schema="app",
    signature="check_criterion_has_capability_on_write()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    if new.deleted_at is not null then\n      return null;\n    end if;\n\n    if not exists (\n      select 1 from evaluation_criterion_capabilities x\n       where x.criterion_id = new.id\n         and x.deleted_at is null\n    ) and new.capability_id is null then\n      raise exception 'criterion % has no capabilities',\n        new.id\n        using errcode = 'check_violation',\n              hint = 'Insert the criterion and its capabilities in the same transaction.';\n    end if;\n    return null;\n  end;\n  $function$",
)

app_check_evidence_criterion_experience = PGFunction(
    schema="app",
    signature="check_evidence_criterion_experience()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_evidence_experience  uuid;\n    v_criterion_experience uuid;\n  begin\n    select pe.experience_id into v_evidence_experience\n      from planned_evidences pe\n     where pe.id = new.evidence_id;\n\n    select ec.experience_id into v_criterion_experience\n      from evaluation_criteria ec\n     where ec.id = new.criterion_id;\n\n    if v_evidence_experience is null\n       or v_criterion_experience is distinct from v_evidence_experience then\n      raise exception 'criterion % does not belong to experience %',\n        new.criterion_id, v_evidence_experience\n        using errcode = 'foreign_key_violation',\n              hint = 'A planned evidence observes criteria of its own experience only.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_check_experience_competency_subject = PGFunction(
    schema="app",
    signature="check_experience_competency_subject()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_subject uuid;\n  begin\n    select co.subject_id into v_subject\n      from learning_experiences le\n      join classes cl on cl.id = le.class_id\n      join courses co on co.id = cl.course_id\n     where le.id = new.experience_id\n       and le.deleted_at is null;\n\n    if not exists (\n      select 1 from competencies c\n       where c.id = new.competency_id\n         and c.deleted_at is null\n         and c.subject_id = v_subject\n    ) then\n      raise exception 'competency % does not belong to the subject of experience %''s class',\n        new.competency_id, new.experience_id\n        using errcode = 'foreign_key_violation',\n              hint = 'An experience works competencies of its class''s subject only.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_check_experience_inside_term = PGFunction(
    schema="app",
    signature="check_experience_inside_term()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_term_starts date;\n    v_term_ends   date;\n  begin\n    select t.starts_on, t.ends_on into v_term_starts, v_term_ends\n      from terms t\n     where t.id = new.term_id\n       and t.deleted_at is null;\n\n    if not found then\n      raise exception 'term % not found', new.term_id\n        using errcode = 'foreign_key_violation';\n    end if;\n\n    if new.starts_on < v_term_starts or new.ends_on > v_term_ends then\n      raise exception 'experience % (% .. %) falls outside its term (% .. %)',\n        new.id, new.starts_on, new.ends_on, v_term_starts, v_term_ends\n        using errcode = 'check_violation',\n              hint = 'An experience must start and end inside its term.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_check_session_entry_date = PGFunction(
    schema="app",
    signature="check_session_entry_date()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_starts date;\n    v_ends   date;\n  begin\n    select le.starts_on, le.ends_on into v_starts, v_ends\n      from learning_experiences le\n     where le.id = new.experience_id\n       and le.deleted_at is null;\n\n    if not found then\n      raise exception 'experience % not found', new.experience_id\n        using errcode = 'foreign_key_violation';\n    end if;\n\n    if new.class_date < v_starts or new.class_date > v_ends then\n      raise exception 'session entry date % is outside experience % (% .. %)',\n        new.class_date, new.experience_id, v_starts, v_ends\n        using errcode = 'check_violation',\n              hint = 'A session outline entry must fall inside its experience.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_current_actor_id = PGFunction(
    schema="app",
    signature="current_actor_id()",
    definition="RETURNS uuid\n LANGUAGE sql\n STABLE\nAS $function$\n    select nullif(current_setting('app.actor_id', true), '')::uuid;\n  $function$",
)

app_ensure_events_partition = PGFunction(
    schema="app",
    signature="ensure_events_partition(p_month date)",
    definition="RETURNS void\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_start date := date_trunc('month', p_month)::date;\n    v_name  text := format('events_%s', to_char(v_start, 'YYYY_MM'));\n  begin\n    if to_regclass(v_name) is null then\n      execute format(\n        'create table %I partition of events for values from (%L) to (%L)',\n        v_name, v_start, (v_start + interval '1 month')::date);\n    end if;\n  end;\n  $function$",
)

app_forbid_event_mutation = PGFunction(
    schema="app",
    signature="forbid_event_mutation()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    raise exception 'events is append-only (attempted % on %)', tg_op, tg_table_name\n      using errcode = 'restrict_violation';\n  end;\n  $function$",
)

app_forbid_score_mutation = PGFunction(
    schema="app",
    signature="forbid_score_mutation()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    if new.assessment_id  is distinct from old.assessment_id\n       or new.student_id  is distinct from old.student_id\n       or new.status         is distinct from old.status\n       or new.raw_value      is distinct from old.raw_value\n       or new.max_value      is distinct from old.max_value\n       or new.scale_level_id is distinct from old.scale_level_id\n       or new.recorded_by_id is distinct from old.recorded_by_id\n       or new.recorded_at    is distinct from old.recorded_at then\n      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id\n        using errcode = 'restrict_violation',\n              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_key is a partial unique index and cannot be deferred, so two live rows for one student and evidence cannot overlap.';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_forbid_year_close_mutation = PGFunction(
    schema="app",
    signature="forbid_year_close_mutation()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    if tg_table_name = 'competency_year_snapshots' then\n      if new.scale_level_id is distinct from old.scale_level_id\n         or new.student_id     is distinct from old.student_id\n         or new.competency_id  is distinct from old.competency_id\n         or new.academic_year_id is distinct from old.academic_year_id\n         or new.source_term_id is distinct from old.source_term_id then\n        raise exception 'competency year snapshot % is immutable', old.id\n          using errcode = 'restrict_violation',\n                hint = 'Reopening the year and re-closing it writes a new snapshot; it does not edit this one.';\n      end if;\n    else\n      if new.situation is distinct from old.situation\n         or new.student_id is distinct from old.student_id\n         or new.academic_year_id is distinct from old.academic_year_id\n         or new.stage is distinct from old.stage\n         or new.breakdown is distinct from old.breakdown then\n        raise exception 'year final situation % is immutable', old.id\n          using errcode = 'restrict_violation',\n                hint = 'The post-recuperacion determination is a separate row (stage), not an edit of the year-end one.';\n      end if;\n    end if;\n    return new;\n  end;\n  $function$",
)

app_log_event = PGFunction(
    schema="app",
    signature="log_event(p_action text, p_entity_type text, p_entity_id uuid DEFAULT NULL::uuid, p_payload jsonb DEFAULT '{}'::jsonb, p_student_id uuid DEFAULT NULL::uuid, p_class_id uuid DEFAULT NULL::uuid, p_session_id uuid DEFAULT NULL::uuid)",
    definition="RETURNS uuid\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_id uuid;\n  begin\n    insert into events (actor_id, action, entity_type, entity_id,\n                        student_id, class_id, session_id, payload,\n                        request_id)\n    values (app.current_actor_id(), p_action, p_entity_type, p_entity_id,\n            p_student_id, p_class_id, p_session_id, p_payload,\n            nullif(current_setting('app.request_id', true), ''))\n    returning id into v_id;\n    return v_id;\n  end;\n  $function$",
)

app_set_updated_at = PGFunction(
    schema="app",
    signature="set_updated_at()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    new.updated_at := now();\n    return new;\n  end;\n  $function$",
)

app_sync_attendance_denormalised = PGFunction(
    schema="app",
    signature="sync_attendance_denormalised()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    select s.class_id, s.session_date\n      into new.class_id, new.session_date\n      from class_sessions s\n     where s.id = new.session_id;\n\n    if not found then\n      raise exception 'session % not found', new.session_id\n        using errcode = 'foreign_key_violation';\n    end if;\n    return new;\n  end;\n  $function$",
)

app_sync_score_denormalised = PGFunction(
    schema="app",
    signature="sync_score_denormalised()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  declare\n    v_assessment_status text;\n    v_term_status       text;\n    v_value_scale       text;\n  begin\n    select a.class_id, a.term_id, a.status, t.status, a.value_scale\n      into new.class_id, new.term_id, v_assessment_status, v_term_status, v_value_scale\n      from assessments a\n      left join terms t on t.id = a.term_id\n     where a.id = new.assessment_id;\n\n    if not found then\n      raise exception 'assessment % not found', new.assessment_id\n        using errcode = 'foreign_key_violation';\n    end if;\n\n    if v_assessment_status = 'draft' then\n      raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id\n        using errcode = 'check_violation';\n    end if;\n\n    -- Un term cerrado deja de aceptar valoraciones. Esto es lo que hace que una libreta\n    -- cerrada sea real y no solo una convención. Una evidencia sin term no tiene term que\n    -- cerrar, así que la verificación se omite.\n    if v_term_status in ('closed', 'archived') then\n      raise exception 'term % is closed; scores cannot be added or changed', new.term_id\n        using errcode = 'restrict_violation',\n              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';\n    end if;\n\n    -- El valor tiene que ser del tipo de la escala de la evidencia.\n    if v_value_scale = 'numeric' and new.scale_level_id is not null then\n      raise exception 'assessment % is numeric and cannot take a level', new.assessment_id\n        using errcode = 'check_violation';\n    end if;\n    if v_value_scale = 'ordinal' and new.raw_value is not null then\n      raise exception 'assessment % is ordinal and cannot take a numeric mark', new.assessment_id\n        using errcode = 'check_violation';\n    end if;\n\n    return new;\n  end;\n  $function$",
)

app_validate_school_timezone = PGFunction(
    schema="app",
    signature="validate_school_timezone()",
    definition="RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n  begin\n    if not exists (select 1 from pg_timezone_names where name = new.timezone) then\n      raise exception 'unknown IANA timezone %', new.timezone using errcode = 'check_violation';\n    end if;\n    return new;\n  end;\n  $function$",
)


public_academic_years_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.academic_years",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.academic_years FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_agent_generations_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.agent_generations",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.agent_generations FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_assessment_criteria_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.assessment_criteria",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.assessment_criteria FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_assessments_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.assessments",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.assessments FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_attendance_records_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.attendance_records",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.attendance_records FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_attendance_records_sync_denormalised = PGTrigger(
    schema="public",
    signature="sync_denormalised",
    on_entity="public.attendance_records",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF session_id ON public.attendance_records FOR EACH ROW EXECUTE FUNCTION app.sync_attendance_denormalised()",
)

public_capabilities_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.capabilities",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.capabilities FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_class_schedules_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.class_schedules",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.class_schedules FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_class_sessions_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.class_sessions",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.class_sessions FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_class_teachers_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.class_teachers",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.class_teachers FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_classes_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.classes",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.classes FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_competencies_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.competencies",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.competencies FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_competency_exemptions_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.competency_exemptions",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.competency_exemptions FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_competency_term_levels_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.competency_term_levels",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.competency_term_levels FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_competency_year_snapshots_forbid_mutation = PGTrigger(
    schema="public",
    signature="forbid_mutation",
    on_entity="public.competency_year_snapshots",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.competency_year_snapshots FOR EACH ROW EXECUTE FUNCTION app.forbid_year_close_mutation()",
)

public_competency_year_snapshots_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.competency_year_snapshots",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.competency_year_snapshots FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_courses_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.courses",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.courses FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_descriptive_conclusions_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.descriptive_conclusions",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.descriptive_conclusions FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_evaluation_criteria_check_criterion_experience = PGTrigger(
    schema="public",
    signature="check_criterion_experience",
    on_entity="public.evaluation_criteria",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF experience_id, competency_id ON public.evaluation_criteria FOR EACH ROW EXECUTE FUNCTION app.check_criterion_experience()",
)

public_evaluation_criteria_check_criterion_on_write = PGTrigger(
    schema="public",
    signature="check_criterion_on_write",
    on_entity="public.evaluation_criteria",
    is_constraint=True,
    definition="AFTER INSERT OR UPDATE OF deleted_at, capability_id ON public.evaluation_criteria DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_criterion_has_capability_on_write()",
)

public_evaluation_criteria_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.evaluation_criteria",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.evaluation_criteria FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_evaluation_criterion_capabilities_check_criterion_capabilities = PGTrigger(
    schema="public",
    signature="check_criterion_capabilities",
    on_entity="public.evaluation_criterion_capabilities",
    is_constraint=True,
    definition="AFTER INSERT OR DELETE OR UPDATE ON public.evaluation_criterion_capabilities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_criterion_has_capability()",
)

public_evaluation_criterion_capabilities_check_criterion_capability_competency = PGTrigger(
    schema="public",
    signature="check_criterion_capability_competency",
    on_entity="public.evaluation_criterion_capabilities",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF criterion_id, competency_id ON public.evaluation_criterion_capabilities FOR EACH ROW EXECUTE FUNCTION app.check_criterion_capability_competency()",
)

public_evaluation_criterion_capabilities_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.evaluation_criterion_capabilities",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.evaluation_criterion_capabilities FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_events_forbid_mutation = PGTrigger(
    schema="public",
    signature="forbid_mutation",
    on_entity="public.events",
    is_constraint=False,
    definition="BEFORE DELETE OR UPDATE ON public.events FOR EACH ROW EXECUTE FUNCTION app.forbid_event_mutation()",
)

public_experience_competencies_check_competency_subject = PGTrigger(
    schema="public",
    signature="check_competency_subject",
    on_entity="public.experience_competencies",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE ON public.experience_competencies FOR EACH ROW EXECUTE FUNCTION app.check_experience_competency_subject()",
)

public_experience_competencies_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.experience_competencies",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.experience_competencies FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_grade_level_performances_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.grade_level_performances",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.grade_level_performances FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_grade_levels_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.grade_levels",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.grade_levels FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_grade_scale_levels_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.grade_scale_levels",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.grade_scale_levels FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_grade_scales_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.grade_scales",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.grade_scales FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_jobs_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.jobs",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.jobs FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_learning_experiences_check_inside_term = PGTrigger(
    schema="public",
    signature="check_inside_term",
    on_entity="public.learning_experiences",
    is_constraint=True,
    definition="AFTER INSERT OR UPDATE OF term_id, starts_on, ends_on ON public.learning_experiences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_experience_inside_term()",
)

public_learning_experiences_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.learning_experiences",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.learning_experiences FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_learning_standards_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.learning_standards",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.learning_standards FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_memberships_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.memberships",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.memberships FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_non_teaching_days_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.non_teaching_days",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.non_teaching_days FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_notifications_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.notifications",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.notifications FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_planned_evidence_criteria_check_evidence_criterion_experience = PGTrigger(
    schema="public",
    signature="check_evidence_criterion_experience",
    on_entity="public.planned_evidence_criteria",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF evidence_id, criterion_id ON public.planned_evidence_criteria FOR EACH ROW EXECUTE FUNCTION app.check_evidence_criterion_experience()",
)

public_planned_evidence_criteria_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.planned_evidence_criteria",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.planned_evidence_criteria FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_planned_evidences_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.planned_evidences",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.planned_evidences FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_school_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.school",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.school FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_school_validate_timezone = PGTrigger(
    schema="public",
    signature="validate_timezone",
    on_entity="public.school",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF timezone ON public.school FOR EACH ROW EXECUTE FUNCTION app.validate_school_timezone()",
)

public_scores_forbid_mutation = PGTrigger(
    schema="public",
    signature="forbid_mutation",
    on_entity="public.scores",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.scores FOR EACH ROW EXECUTE FUNCTION app.forbid_score_mutation()",
)

public_scores_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.scores",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.scores FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_scores_sync_denormalised = PGTrigger(
    schema="public",
    signature="sync_denormalised",
    on_entity="public.scores",
    is_constraint=False,
    definition="BEFORE INSERT ON public.scores FOR EACH ROW EXECUTE FUNCTION app.sync_score_denormalised()",
)

public_section_memberships_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.section_memberships",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.section_memberships FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_sections_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.sections",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.sections FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_session_outline_entries_check_session_entry_date = PGTrigger(
    schema="public",
    signature="check_session_entry_date",
    on_entity="public.session_outline_entries",
    is_constraint=False,
    definition="BEFORE INSERT OR UPDATE OF experience_id, class_date ON public.session_outline_entries FOR EACH ROW EXECUTE FUNCTION app.check_session_entry_date()",
)

public_session_outline_entries_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.session_outline_entries",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.session_outline_entries FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_standard_level_mappings_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.standard_level_mappings",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.standard_level_mappings FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_students_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.students",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.students FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_subjects_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.subjects",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.subjects FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_teachers_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.teachers",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.teachers FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_terms_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.terms",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.terms FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

chat_threads_set_updated_at = PGTrigger(
    schema="chat",
    signature="set_updated_at",
    on_entity="chat.threads",
    is_constraint=False,
    definition="BEFORE UPDATE ON chat.threads FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_users_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.users",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_voice_note_redactions_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.voice_note_redactions",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.voice_note_redactions FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_voice_notes_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.voice_notes",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.voice_notes FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

public_year_final_situations_forbid_mutation = PGTrigger(
    schema="public",
    signature="forbid_mutation",
    on_entity="public.year_final_situations",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.year_final_situations FOR EACH ROW EXECUTE FUNCTION app.forbid_year_close_mutation()",
)

public_year_final_situations_set_updated_at = PGTrigger(
    schema="public",
    signature="set_updated_at",
    on_entity="public.year_final_situations",
    is_constraint=False,
    definition="BEFORE UPDATE ON public.year_final_situations FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)


chat_api_school = PGView(
    schema="chat_api",
    signature="school",
    definition="SELECT id,\n    name,\n    city,\n    region,\n    timezone\n   FROM school t\n  WHERE deleted_at IS NULL",
)

chat_api_sections = PGView(
    schema="chat_api",
    signature="sections",
    definition="SELECT s.id,\n    ay.year AS academic_year,\n    ay.status AS academic_year_status,\n    g.label AS grade,\n    g.long_label AS grade_long,\n    g.stage,\n    s.label AS section,\n    s.name,\n    s.shift,\n    s.status\n   FROM sections s\n     JOIN grade_levels g ON g.id = s.grade_level_id\n     JOIN academic_years ay ON ay.id = s.academic_year_id\n  WHERE s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL",
)

chat_api_terms = PGView(
    schema="chat_api",
    signature="terms",
    definition="SELECT t.id,\n    ay.year AS academic_year,\n    ay.status AS academic_year_status,\n    t.stage,\n    t.sequence,\n    t.name,\n    t.short_name,\n    t.starts_on,\n    t.ends_on,\n    t.status,\n    (now() AT TIME ZONE tn.timezone)::date >= t.starts_on AND (now() AT TIME ZONE tn.timezone)::date <= t.ends_on AS is_current,\n    (EXISTS ( SELECT 1\n           FROM competency_term_levels l\n          WHERE l.term_id = t.id AND l.superseded_at IS NULL AND l.deleted_at IS NULL)) AS has_levels\n   FROM terms t\n     JOIN academic_years ay ON ay.id = t.academic_year_id\n     CROSS JOIN school tn\n  WHERE t.deleted_at IS NULL AND ay.deleted_at IS NULL",
)

chat_api_classes = PGView(
    schema="chat_api",
    signature="classes",
    definition="SELECT c.id,\n    ay.year AS academic_year,\n    ay.status AS academic_year_status,\n    g.label AS grade,\n    g.long_label AS grade_long,\n    g.ordinal AS grade_ordinal,\n    g.stage,\n    s.id AS section_id,\n    s.label AS section,\n    s.name AS section_name,\n    s.shift,\n    su.code AS subject_code,\n    su.name AS subject_name,\n    su.is_tutoria,\n    titular.display_name AS teacher,\n    tutor.display_name AS tutor\n   FROM classes c\n     JOIN sections s ON s.id = c.section_id\n     JOIN grade_levels g ON g.id = s.grade_level_id\n     JOIN academic_years ay ON ay.id = s.academic_year_id\n     JOIN courses co ON co.id = c.course_id\n     JOIN subjects su ON su.id = co.subject_id\n     CROSS JOIN school tn\n     LEFT JOIN LATERAL ( SELECT te.display_name\n           FROM class_teachers ct\n             JOIN teachers te ON te.id = ct.teacher_id\n          WHERE ct.class_id = c.id AND ct.role = 'titular'::text AND ct.deleted_at IS NULL AND te.deleted_at IS NULL AND ct.starts_on <= (now() AT TIME ZONE tn.timezone)::date AND (ct.ends_on IS NULL OR ct.ends_on >= (now() AT TIME ZONE tn.timezone)::date)\n          ORDER BY ct.starts_on DESC\n         LIMIT 1) titular ON true\n     LEFT JOIN teachers tutor ON tutor.id = s.tutor_teacher_id AND tutor.deleted_at IS NULL\n  WHERE c.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL AND co.deleted_at IS NULL AND su.deleted_at IS NULL",
)

chat_api_students = PGView(
    schema="chat_api",
    signature="students",
    definition="SELECT st.id AS student_id,\n    st.given_name,\n    st.preferred_name,\n    st.paternal_surname,\n    st.maternal_surname,\n    concat_ws(' '::text, COALESCE(st.preferred_name, st.given_name), st.paternal_surname, st.maternal_surname) AS full_name,\n    ay.year AS academic_year,\n    ay.status AS academic_year_status,\n    g.label AS grade,\n    g.long_label AS grade_long,\n    g.ordinal AS grade_ordinal,\n    g.stage,\n    s.id AS section_id,\n    s.label AS section,\n    s.name AS section_name,\n    sm.joined_on,\n    sm.left_on,\n    sm.status AS membership_status\n   FROM section_memberships sm\n     JOIN students st ON st.id = sm.student_id\n     JOIN sections s ON s.id = sm.section_id\n     JOIN grade_levels g ON g.id = s.grade_level_id\n     JOIN academic_years ay ON ay.id = sm.academic_year_id\n  WHERE sm.deleted_at IS NULL AND st.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL",
)

chat_api_competencies = PGView(
    schema="chat_api",
    signature="competencies",
    definition="SELECT c.id,\n    su.code AS subject_code,\n    su.name AS subject_name,\n    su.sort_order AS subject_order,\n    c.code,\n    c.name,\n    c.sort_order\n   FROM competencies c\n     JOIN subjects su ON su.id = c.subject_id\n  WHERE (c.kind = ANY (ARRAY['area'::text, 'adicional_area'::text])) AND c.is_active AND NOT su.is_tutoria AND c.deleted_at IS NULL AND su.deleted_at IS NULL",
)

chat_api_levels = PGView(
    schema="chat_api",
    signature="levels",
    definition="SELECT l.id,\n    st.id AS student_id,\n    concat_ws(' '::text, COALESCE(st.preferred_name, st.given_name), st.paternal_surname, st.maternal_surname) AS full_name,\n    st.paternal_surname,\n    st.maternal_surname,\n    ay.year AS academic_year,\n    ay.status AS academic_year_status,\n    g.label AS grade,\n    g.long_label AS grade_long,\n    g.ordinal AS grade_ordinal,\n    g.stage,\n    s.id AS section_id,\n    s.label AS section,\n    s.name AS section_name,\n    su.code AS subject_code,\n    su.name AS subject_name,\n    su.sort_order AS subject_order,\n    c.code AS competency_code,\n    c.name AS competency_name,\n    c.sort_order AS competency_order,\n    t.id AS term_id,\n    t.sequence AS term_sequence,\n    t.name AS term_name,\n    t.short_name AS term_short_name,\n    sl.code AS level,\n    sl.ordinal AS level_ordinal\n   FROM competency_term_levels l\n     JOIN students st ON st.id = l.student_id\n     JOIN competencies c ON c.id = l.competency_id\n     JOIN subjects su ON su.id = c.subject_id\n     JOIN terms t ON t.id = l.term_id\n     JOIN academic_years ay ON ay.id = l.academic_year_id\n     JOIN grade_scale_levels sl ON sl.id = l.scale_level_id\n     JOIN classes cl ON cl.id = l.class_id\n     JOIN sections s ON s.id = cl.section_id\n     JOIN grade_levels g ON g.id = s.grade_level_id\n  WHERE l.superseded_at IS NULL AND l.deleted_at IS NULL AND (c.kind = ANY (ARRAY['area'::text, 'adicional_area'::text])) AND NOT su.is_tutoria AND st.deleted_at IS NULL AND c.deleted_at IS NULL AND su.deleted_at IS NULL AND t.deleted_at IS NULL AND ay.deleted_at IS NULL AND cl.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL",
)

privacy_pii_columns = PGView(
    schema="privacy",
    signature="pii_columns",
    definition="SELECT n.nspname AS schema_name,\n    c.relname AS table_name,\n    a.attname AS column_name,\n    format_type(a.atttypid, a.atttypmod) AS data_type,\n        CASE\n            WHEN d.description ~~ 'PII (menor y adulto)%'::text THEN 'minor_and_adult'::text\n            WHEN d.description ~~ 'PII (menor)%'::text THEN 'minor'::text\n            WHEN d.description ~~ 'PII (adulto)%'::text THEN 'adult'::text\n            ELSE 'unclassified'::text\n        END AS subject,\n    NULLIF(TRIM(BOTH FROM \"substring\"(d.description, 'PII \\([^)]*\\):\\s*([^.]*)'::text)), ''::text) AS category,\n    d.description AS note\n   FROM pg_class c\n     JOIN pg_namespace n ON n.oid = c.relnamespace\n     JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped\n     JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum\n  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::\"char\", 'p'::\"char\"])) AND d.description ~~ 'PII %'::text",
)

privacy_minor_data_tables = PGView(
    schema="privacy",
    signature="minor_data_tables",
    definition="SELECT n.nspname AS schema_name,\n    c.relname AS table_name,\n    d.description AS note\n   FROM pg_class c\n     JOIN pg_namespace n ON n.oid = c.relnamespace\n     JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0\n  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::\"char\", 'p'::\"char\"])) AND d.description ~~ '%DATOS PERSONALES DE MENORES%'::text",
)

privacy_undeclared_student_references = PGView(
    schema="privacy",
    signature="undeclared_student_references",
    definition="SELECT c.relname AS table_name,\n    a.attname AS column_name\n   FROM pg_class c\n     JOIN pg_namespace n ON n.oid = c.relnamespace\n     JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped\n     LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0\n  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::\"char\", 'p'::\"char\"])) AND NOT c.relispartition AND a.attname = 'student_id'::name AND COALESCE(d.description, ''::text) !~~ '%DATOS PERSONALES DE MENORES%'::text AND c.relname <> 'events'::name",
)


chat_messages_owner_only = PGPolicy(
    schema="chat",
    signature="owner_only",
    on_entity="chat.messages",
    definition="AS PERMISSIVE FOR ALL TO public USING ((user_id = app.current_actor_id())) WITH CHECK ((user_id = app.current_actor_id()))",
)

chat_threads_owner_only = PGPolicy(
    schema="chat",
    signature="owner_only",
    on_entity="chat.threads",
    definition="AS PERMISSIVE FOR ALL TO public USING ((user_id = app.current_actor_id())) WITH CHECK ((user_id = app.current_actor_id()))",
)


def upgrade() -> None:
    # Extensions, schemas, the timerange type, roles and default privileges.
    op.execute("create extension if not exists btree_gist")
    op.execute("create extension if not exists pg_trgm")
    op.execute("create schema if not exists app")
    op.execute("create schema if not exists privacy")
    op.execute("create schema if not exists chat_api")
    op.execute("create schema if not exists chat")
    op.execute("create type public.timerange as range (subtype = time)")
    op.execute(
        """do $$
begin
  create role mawta_app login;
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$"""
    )
    op.execute(
        """do $$
begin
  create role mawta_chat login connection limit 10;
  alter role mawta_chat set statement_timeout = '15s';
  alter role mawta_chat set lock_timeout = '2s';
  alter role mawta_chat set idle_in_transaction_session_timeout = '30s';
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$"""
    )
    op.execute(
        """do $$
begin
  create role mawta_chat_api nologin;
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$"""
    )
    op.execute("grant usage on schema public, app, privacy to mawta_app")
    op.execute(
        "alter default privileges in schema public grant select, insert, update, delete on tables to mawta_app"
    )
    op.execute(
        "alter default privileges in schema public grant usage, select on sequences to mawta_app"
    )
    op.execute("alter default privileges in schema privacy grant select on tables to mawta_app")
    op.execute("grant usage on schema app to mawta_chat, mawta_chat_api")
    op.execute("grant usage on schema chat_api, chat to mawta_chat")

    # Functions first: triggers call them.
    op.create_entity(app_check_criterion_capability_competency)
    op.create_entity(app_check_criterion_experience)
    op.create_entity(app_check_criterion_has_capability)
    op.create_entity(app_check_criterion_has_capability_on_write)
    op.create_entity(app_check_evidence_criterion_experience)
    op.create_entity(app_check_experience_competency_subject)
    op.create_entity(app_check_experience_inside_term)
    op.create_entity(app_check_session_entry_date)
    op.create_entity(app_current_actor_id)
    op.create_entity(app_ensure_events_partition)
    op.create_entity(app_forbid_event_mutation)
    op.create_entity(app_forbid_score_mutation)
    op.create_entity(app_forbid_year_close_mutation)
    op.create_entity(app_log_event)
    op.create_entity(app_set_updated_at)
    op.create_entity(app_sync_attendance_denormalised)
    op.create_entity(app_sync_score_denormalised)
    op.create_entity(app_validate_school_timezone)

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "academic_years",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "term_structure",
            sa.Text(),
            server_default=sa.text("'bimestre'::text"),
            nullable=False,
            comment="Cómo se subdivide el año: bimestre, trimestre o semestre. Un colegio puede usar una estructura distinta de un año a otro.",
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'planned'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text]))",
            name="academic_years_status_check",
        ),
        sa.CheckConstraint(
            "(term_structure = ANY (ARRAY['bimestre'::text, 'trimestre'::text, 'semestre'::text]))",
            name="academic_years_term_structure_check",
        ),
        sa.CheckConstraint("((year >= 2000) AND (year <= 2100))", name="academic_years_year_check"),
        sa.CheckConstraint("(ends_on > starts_on)", name="academic_years_range_valid"),
        sa.PrimaryKeyConstraint("id", name="academic_years_pkey"),
        comment="Un año escolar del colegio, ej. 2026. En Perú va aproximadamente de marzo a diciembre.",
    )
    op.create_index(
        "academic_years_year_key",
        "academic_years",
        ["year"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "pseudonyms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(entity_type = ANY (ARRAY['student'::text, 'teacher'::text]))",
            name="pseudonyms_entity_type_check",
        ),
        sa.CheckConstraint(
            "((char_length(alias) >= 1) AND (char_length(alias) <= 40))",
            name="pseudonyms_alias_check",
        ),
        sa.PrimaryKeyConstraint("id", name="pseudonyms_pkey"),
        sa.UniqueConstraint("alias", name="pseudonyms_alias_key"),
        sa.UniqueConstraint("entity_type", "entity_id", name="pseudonyms_entity_key"),
        schema="chat",
        comment="Seudónimos estables por colegio (D001): el modelo nunca recibe nombres reales de alumnos ni profesores, solo estos alias. entity_id apunta a students.id o teachers.id según entity_type; no lleva FK porque cubre dos tablas.",
    )
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Cuándo ocurrió la acción, en UTC. También es la clave de partición, así que forma parte de la llave primaria.",
        ),
        sa.Column("actor_type", sa.Text(), server_default=sa.text("'user'::text"), nullable=False),
        sa.Column(
            "actor_id",
            sa.UUID(),
            nullable=True,
            comment="La fila de users que actuó. Null para actores system y job. No es una FK: los events sobreviven a las filas que referencian, y un event nunca debe bloquearse ni propagarse en cascada por un cambio en el actor.",
        ),
        sa.Column("actor_teacher_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            sa.Text(),
            nullable=False,
            comment="Verbo en forma entidad.verbo: student.read, score.recorded, session.started, attendance.marked, voice_note.saved. La columna más importante para el entrenamiento de modelos, así que es una taxonomía de texto libre en vez de un enum restringido que necesitaría una migración por cada verbo nuevo.",
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column(
            "student_id",
            sa.UUID(),
            nullable=True,
            comment='Sujeto desnormalizado de la acción. Presente para que "todo lo que le pasó a este estudiante" sea un solo recorrido de índice en vez de una búsqueda en jsonb, y para que una solicitud de acceso bajo la Ley 29733 pueda responderse directamente.',
        ),
        sa.Column(
            "class_id",
            sa.UUID(),
            nullable=True,
            comment="Contexto de class desnormalizado, para series de actividad por class sin desempaquetar payload.",
        ),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("term_id", sa.UUID(), nullable=True),
        sa.Column(
            "request_id",
            sa.Text(),
            nullable=True,
            comment="Correlaciona los events escritos durante una misma solicitud a la API, que es lo que convierte una lista de filas en una secuencia causal.",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Detalle específico de la acción. Deliberadamente sin esquema: restringirlo convertiría agregar una acción en una migración.",
        ),
        sa.CheckConstraint(
            "(actor_type = ANY (ARRAY['user'::text, 'system'::text, 'job'::text, 'model'::text, 'import'::text]))",
            name="events_actor_type_check",
        ),
        sa.PrimaryKeyConstraint("id", "occurred_at", name="events_pkey"),
        comment="Registro de solo inserción de cada acción relevante, incluyendo cada lectura de un registro de estudiante. Particionado por mes e indexado para acceso como serie de tiempo porque es el corpus de entrenamiento para detección de riesgo y proyección de notas, no solo un registro de auditoría. Nunca se actualiza, nunca se elimina — los meses antiguos se desconectan (DETACH).",
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "events_action_time_idx",
        "events",
        ["action", sa.literal_column("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "events_class_time_idx",
        "events",
        ["class_id", sa.literal_column("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "events_entity_idx",
        "events",
        ["entity_type", "entity_id", sa.literal_column("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "events_student_time_idx",
        "events",
        ["student_id", sa.literal_column("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "events_time_idx", "events", [sa.literal_column("occurred_at DESC")], unique=False
    )
    op.create_table(
        "grade_levels",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column(
            "label",
            sa.Text(),
            nullable=False,
            comment='Forma corta usada dentro de un nombre de clase, ej. "5to" en "Inglés 5to B".',
        ),
        sa.Column(
            "long_label",
            sa.Text(),
            nullable=False,
            comment='Forma de encabezado de sección, ej. "5TO GRADO".',
        ),
        sa.Column("stage", sa.Text(), server_default=sa.text("'secundaria'::text"), nullable=False),
        sa.Column(
            "cycle",
            sa.Text(),
            nullable=True,
            comment="Ciclo I o Ciclo II, con sentido solo cuando stage = 'inicial'. Ciclo I cubre 0-2 años, Ciclo II cubre 3-5 años; cada uno tiene su propia obligatoriedad de conclusión descriptiva.",
        ),
        sa.Column(
            "ordinal",
            sa.SmallInteger(),
            nullable=False,
            comment="Orden de clasificación para la lista de clases agrupadas. Distinto de code, que puede no ordenarse de forma natural.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(cycle = ANY (ARRAY['ciclo_i'::text, 'ciclo_ii'::text, 'ciclo_iii'::text, 'ciclo_iv'::text, 'ciclo_v'::text, 'ciclo_vi'::text, 'ciclo_vii'::text]))",
            name="grade_levels_cycle_check",
        ),
        sa.CheckConstraint(
            "(stage = ANY (ARRAY['inicial'::text, 'primaria'::text, 'secundaria'::text, 'otro'::text]))",
            name="grade_levels_stage_check",
        ),
        sa.PrimaryKeyConstraint("id", name="grade_levels_pkey"),
        comment="Los grados tal como los nombra el colegio. Modelado como filas para que un colegio pueda usar 1ro-5to de secundaria, grados 1-11, o Year 7-11 sin cambiar el esquema.",
    )
    op.create_index(
        "grade_levels_code_key",
        "grade_levels",
        ["code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "grade_levels_ordinal_key",
        "grade_levels",
        ["ordinal"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "grade_scales",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="Solo afecta la presentación. ordinal muestra el código del nivel, numeric muestra el valor, percentage muestra un porcentaje. Las tres se normalizan de forma idéntica.",
        ),
        sa.Column(
            "min_value",
            sa.Numeric(precision=8, scale=4),
            nullable=False,
            comment="El valor más bajo que la escala puede expresar: 0 para vigesimal, y para una escala ordinal el piso numérico de su banda más baja.",
        ),
        sa.Column("max_value", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column(
            "decimals",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Precisión de presentación. Lo vigesimal normalmente se reporta como número entero aunque las scores en crudo sean decimales.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['ordinal'::text, 'numeric'::text, 'percentage'::text]))",
            name="grade_scales_kind_check",
        ),
        sa.CheckConstraint(
            "((decimals >= 0) AND (decimals <= 4))", name="grade_scales_decimals_check"
        ),
        sa.CheckConstraint("(max_value > min_value)", name="grade_scales_range_valid"),
        sa.PrimaryKeyConstraint("id", name="grade_scales_pkey"),
        comment="Cómo expresa un colegio una nota. ordinal = MINEDU AD/A/B/C, numeric = vigesimal 0-20, percentage = 0-100. Toda escala se mapea al mismo eje normalizado 0-1.",
    )
    op.create_index(
        "grade_scales_code_key",
        "grade_scales",
        ["code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="Qué handler ejecuta el job. Los tipos vigentes son 'voice_note.transcribe' (transcripción de voz a texto en español para una nota grabada) y 'agent.generate' (una generación de los agentes de Mawta). Texto libre sin CHECK: las filas de tipos retirados fallan como 'unknown job kind' en vez de reescribirse.",
        ),
        sa.Column("queue", sa.Text(), server_default=sa.text("'default'::text"), nullable=False),
        sa.Column(
            "priority",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
            comment="El menor corre primero. La transcripción de una nota que el docente está viendo tiene prioridad sobre un trabajo de mantenimiento nocturno.",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'available'::text"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default=sa.text("20"), nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="El momento más temprano en que este job puede reclamarse. Sirve tanto para programación como para el backoff exponencial.",
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempted_by",
            sa.Text(),
            nullable=True,
            comment="Identidad del worker que sostiene el lease actual, para diagnosticar un job atascado.",
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Arreglo de solo inserción de registros de fallo, uno por intento. Se conserva completo porque un job que eventualmente tuvo éxito tras tres fallos de transcripción es en sí mismo una señal sobre la calidad del audio.",
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "unique_key",
            sa.Text(),
            nullable=True,
            comment="Clave de deduplicación. Evita que una ráfaga de ediciones de score encole cuarenta recomputaciones de notas idénticas para el mismo estudiante.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "((status = ANY (ARRAY['completed'::text, 'cancelled'::text, 'discarded'::text])) = (finalized_at IS NOT NULL))",
            name="jobs_finalized_consistent",
        ),
        sa.CheckConstraint("(jsonb_typeof(errors) = 'array'::text)", name="jobs_errors_is_array"),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['available'::text, 'running'::text, 'retryable'::text, 'scheduled'::text, 'completed'::text, 'cancelled'::text, 'discarded'::text]))",
            name="jobs_status_check",
        ),
        sa.CheckConstraint("((priority >= 1) AND (priority <= 4))", name="jobs_priority_check"),
        sa.CheckConstraint("(attempts >= 0)", name="jobs_attempts_check"),
        sa.CheckConstraint("(max_attempts > 0)", name="jobs_max_attempts_check"),
        sa.PrimaryKeyConstraint("id", name="jobs_pkey"),
        comment="La cola de trabajo, en Postgres. La transcripción de notas de voz y las generaciones de los agentes pasan por aquí. Se reclama con SELECT ... FOR UPDATE SKIP LOCKED, que es la única razón por la que una cola en la base de datos primaria es viable a esta escala.",
    )
    op.create_index(
        "jobs_claim_idx",
        "jobs",
        ["queue", "priority", "run_after", "id"],
        unique=False,
        postgresql_where=sa.text(
            "(status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text]))"
        ),
    )
    op.create_index(
        "jobs_finalized_idx",
        "jobs",
        ["finalized_at"],
        unique=False,
        postgresql_where=sa.text("(finalized_at IS NOT NULL)"),
    )
    op.create_index(
        "jobs_kind_idx", "jobs", ["kind", sa.literal_column("created_at DESC")], unique=False
    )
    op.create_index(
        "jobs_unique_key_idx",
        "jobs",
        ["kind", "unique_key"],
        unique=True,
        postgresql_where=sa.text(
            "((unique_key IS NOT NULL) AND (status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text, 'running'::text])))"
        ),
    )
    op.create_table(
        "school",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column(
            "modular_code",
            sa.Text(),
            nullable=True,
            comment="Código modular MINEDU de la institución educativa, cuando tiene uno. Null para colegios privados fuera del registro.",
        ),
        sa.Column("kind", sa.Text(), server_default=sa.text("'publica'::text"), nullable=False),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column(
            "timezone",
            sa.Text(),
            server_default=sa.text("'America/Lima'::text"),
            nullable=False,
            comment='Zona horaria IANA del colegio. Todos los timestamps se almacenan en UTC; este es el único lugar donde se define un día calendario local, y es contra el que se calcula "HOY".',
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "singleton",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Siempre true: el índice único school_singleton_key garantiza que la base tenga un solo colegio.",
        ),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['publica'::text, 'privada'::text, 'parroquial'::text, 'internacional'::text]))",
            name="school_kind_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'suspended'::text, 'closed'::text]))",
            name="school_status_check",
        ),
        sa.CheckConstraint("singleton", name="school_singleton_check"),
        sa.PrimaryKeyConstraint("id", name="school_pkey"),
        comment="El colegio (institución educativa) de esta base de datos. Hay una sola fila: cada colegio tiene su propia base.",
    )
    op.create_index(
        "school_modular_code_key",
        "school",
        ["modular_code"],
        unique=True,
        postgresql_where=sa.text("((modular_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index("school_singleton_key", "school", ["singleton"], unique=True)
    op.create_table(
        "standard_level_mappings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "modality",
            sa.Text(),
            nullable=False,
            comment="Modalidad del servicio educativo: ebr (Educación Básica Regular), ebe (Educación Básica Especial), eja (Educación Básica Alternativa).",
        ),
        sa.Column(
            "cycle",
            sa.Text(),
            nullable=False,
            comment="Ciclo de la modalidad. En EBR: ciclo_i (0-2 años), ciclo_ii (3-5), ciclo_iii (1ro-2do primaria), ciclo_iv (3ro-4to), ciclo_v (5to-6to), ciclo_vi (1ro-2do secundaria), ciclo_vii (3ro-5to).",
        ),
        sa.Column(
            "expected_level",
            sa.SmallInteger(),
            nullable=False,
            comment="El nivel (1-8) del estándar de aprendizaje que cierra ese ciclo. Un ciclo termina en un nivel: este mapeo es la única fuente de esa correspondencia.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(cycle = ANY (ARRAY['ciclo_i'::text, 'ciclo_ii'::text, 'ciclo_iii'::text, 'ciclo_iv'::text, 'ciclo_v'::text, 'ciclo_vi'::text, 'ciclo_vii'::text]))",
            name="standard_level_mappings_cycle_check",
        ),
        sa.CheckConstraint(
            "(modality = ANY (ARRAY['ebr'::text, 'ebe'::text, 'eja'::text]))",
            name="standard_level_mappings_modality_check",
        ),
        sa.CheckConstraint(
            "((expected_level >= 1) AND (expected_level <= 8))",
            name="standard_level_mappings_expected_level_check",
        ),
        sa.PrimaryKeyConstraint("id", name="standard_level_mappings_pkey"),
        comment='Qué nivel de estándar (1-8) corresponde a cada combinación de modalidad y ciclo, ej. (ebr, ciclo_vii) → 7. Permite resolver "el estándar de fin de ciclo de esta class" a partir del grado, sin codificarlo en Go ni asumir que todos los colegios siguen la EBR regular.',
    )
    op.create_index(
        "standard_level_mappings_key",
        "standard_level_mappings",
        ["modality", "cycle"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "student_code",
            sa.Text(),
            nullable=True,
            comment="PII (menor): identificador. Código de matrícula interno del colegio.",
        ),
        sa.Column(
            "siagie_code",
            sa.Text(),
            nullable=True,
            comment='PII (menor): identificador. El código SIAGIE de 14 dígitos, el identificador nacional de MINEDU para estudiantes, ej. "12345678920001". Nulable: no todos los estudiantes tienen uno asignado todavía. Único en el colegio.',
        ),
        sa.Column("given_name", sa.Text(), nullable=False, comment="PII (menor): nombre."),
        sa.Column(
            "paternal_surname",
            sa.Text(),
            nullable=False,
            comment="PII (menor): nombre. La convención peruana mantiene los dos apellidos por separado; concatenarlos pierde información.",
        ),
        sa.Column("maternal_surname", sa.Text(), nullable=True, comment="PII (menor): nombre."),
        sa.Column(
            "preferred_name",
            sa.Text(),
            nullable=True,
            comment="PII (menor): nombre. Cómo llama realmente el docente al estudiante.",
        ),
        sa.Column(
            "birthdate",
            sa.Date(),
            nullable=True,
            comment="PII (menor): sensible. Está presente porque la edad determina tanto la ubicación curricular como el régimen de consentimiento; no se necesita para las pantallas principales de la aplicación.",
        ),
        sa.Column("sex", sa.Text(), nullable=True, comment="PII (menor): sensible."),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column(
            "document_number",
            sa.Text(),
            nullable=True,
            comment="PII (menor): identificador estatal. DNI o equivalente. La columna de mayor riesgo en el esquema.",
        ),
        sa.Column("enrolled_on", sa.Date(), nullable=True),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "inclusion_support",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="DATOS PERSONALES DE MENORES (sensible). True cuando el estudiante enfrenta barreras educativas y recibe apoyos educativos / ajustes razonables. Hace obligatoria una conclusión descriptiva en todo periodo sin importar el nivel alcanzado, y esa conclusión debe indicar los apoyos brindados (RVM 048-2024, 5.1.1.3 p.7 último párrafo). Deliberadamente es una bandera, no un diagnóstico: el esquema registra la obligación, no la condición.",
        ),
        sa.CheckConstraint(
            "(document_type = ANY (ARRAY['DNI'::text, 'CE'::text, 'PAS'::text, 'PTP'::text, 'otro'::text]))",
            name="students_document_type_check",
        ),
        sa.CheckConstraint(
            "(sex = ANY (ARRAY['F'::text, 'M'::text, 'X'::text, 'unspecified'::text]))",
            name="students_sex_check",
        ),
        sa.CheckConstraint(
            "(siagie_code ~ '^[0-9]{14}$'::text)", name="students_siagie_code_check"
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'withdrawn'::text, 'transferred'::text, 'graduated'::text]))",
            name="students_status_check",
        ),
        sa.CheckConstraint(
            "((document_type IS NULL) = (document_number IS NULL))", name="students_document_pair"
        ),
        sa.CheckConstraint(
            "((left_on IS NULL) OR (enrolled_on IS NULL) OR (left_on >= enrolled_on))",
            name="students_left_after_enrolled",
        ),
        sa.PrimaryKeyConstraint("id", name="students_pkey"),
        comment="DATOS PERSONALES DE MENORES. Cada fila es un niño o niña. Contiene: nombres legales, fecha de nacimiento, sexo y documento nacional de identidad. Se procesa bajo la Ley 29733 (Perú) con consentimiento parental que conserva el colegio. Cada lectura debe registrarse en events (action='student.read').",
    )
    op.create_index(
        "students_code_key",
        "students",
        ["student_code"],
        unique=True,
        postgresql_where=sa.text("((student_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "students_document_key",
        "students",
        ["document_type", "document_number"],
        unique=True,
        postgresql_where=sa.text("((document_number IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "students_name_trgm_idx",
        "students",
        [
            sa.literal_column(
                "((((COALESCE(given_name, ''::text) || ' '::text) || COALESCE(paternal_surname, ''::text)) || ' '::text) || COALESCE(maternal_surname, ''::text))"
            ).label("full_name")
        ],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"full_name": "gin_trgm_ops"},
    )
    op.create_index(
        "students_siagie_code_key",
        "students",
        ["siagie_code"],
        unique=True,
        postgresql_where=sa.text("((siagie_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "subjects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "area_curricular",
            sa.Text(),
            nullable=True,
            comment='Área curricular MINEDU a la que pertenece la asignatura, ej. "Ciencias Sociales" para Historia y Geografía. Se mantiene en español: es un término propio del currículo nacional, no una categoría genérica.',
        ),
        sa.Column(
            "icon_key",
            sa.Text(),
            nullable=True,
            comment="Clave estable para el ícono de las tarjetas de clase (calculadora, libro, banco, mundo). Se almacena en vez de derivarse del nombre, para que renombrar una asignatura no cambie su ícono.",
        ),
        sa.Column(
            "is_tutoria",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment='Tutoría se programa como una asignatura pero no se califica en la escala de logro. "Tutoría 5to A" aparece entre las clases; debe excluirse de los agregados de distribución de logro.',
        ),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="subjects_pkey"),
        comment="Un curso o asignatura del colegio: Matemática, Comunicación, Inglés, Historia, Geografía, Tutoría.",
    )
    op.create_index(
        "subjects_code_key",
        "subjects",
        ["code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "email",
            sa.Text(),
            nullable=False,
            comment="PII (adulto): contacto. Se pasa a minúsculas al escribir; la unicidad se aplica sobre lower(email).",
        ),
        sa.Column("given_name", sa.Text(), nullable=False),
        sa.Column("family_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True, comment="PII (adulto): contacto."),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "username",
            sa.Text(),
            nullable=True,
            comment="PII (adulto): el identificador de inicio de sesión. Único globalmente sobre lower(username), igual que email y por la misma razón — una persona, una credencial, un colegio (ver memberships_one_school_per_user). Se pasa a minúsculas al escribir; users_username_shape lo restringe a [a-z0-9._-]{3,64} para que lower() sea una identidad verdadera. Email sigue siendo un dato de contacto y nunca es un inicio de sesión.",
        ),
        sa.Column(
            "password_hash",
            sa.Text(),
            nullable=True,
            comment="Hash bcrypt (costo desde BCRYPT_COST, por defecto 12) de la contraseña de la cuenta. Nunca se registra en logs, nunca se devuelve en ningún endpoint, solo lo lee internal/repo/auth.go. Null significa que la cuenta no tiene contraseña y no puede iniciar sesión; users_credential_complete mantiene eso emparejado con un username null.",
        ),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo se estableció la contraseña por última vez. Cada fila de user_sessions del usuario se revoca (reason = 'password_change') cuando cambia.",
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Último inicio de sesión exitoso, escrito por repo.RecordLoginSuccess.",
        ),
        sa.Column(
            "failed_login_count",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Inicios de sesión fallidos consecutivos desde el último éxito. Se reinicia a 0 en un éxito. Al llegar a LOGIN_MAX_FAILURES la cuenta se bloquea mediante locked_until, sin importar la contraseña en el siguiente intento.",
        ),
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Expiración del bloqueo. Mientras esté en el futuro, todo intento de inicio de sesión para esta cuenta se rechaza con account_locked sin importar la contraseña.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((username IS NULL) OR (username ~ '^[a-z0-9._-]{3,64}$'::text))",
            name="users_username_shape",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'deactivated'::text]))",
            name="users_status_check",
        ),
        sa.CheckConstraint(
            "((username IS NULL) = (password_hash IS NULL))", name="users_credential_complete"
        ),
        sa.CheckConstraint("(failed_login_count >= 0)", name="users_failed_login_count_check"),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        comment="PII (adulto). Principales de autenticación: los cuatro roles de membership (teacher, student, supervisor, admin). Contiene la credencial (username + password_hash). No contiene datos de menores — los estudiantes no son usuarios y no tienen inicio de sesión: memberships.role puede decir 'student', pero ninguna fila de students se vincula jamás a una fila de users.",
    )
    op.create_index(
        "users_email_key",
        "users",
        [sa.literal_column("(lower(email))")],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "users_username_key",
        "users",
        [sa.literal_column("(lower(username))")],
        unique=True,
        postgresql_where=sa.text("((username IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "threads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "title",
            sa.Text(),
            server_default=sa.text("'Nuevo chat'::text"),
            nullable=False,
            comment="PII (adulto): texto libre. Lo genera el chat a partir de la primera pregunta (ya seudonimizada) o lo escribe el director al renombrar.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((char_length(title) >= 1) AND (char_length(title) <= 200))",
            name="threads_title_check",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="threads_user_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="threads_pkey"),
        schema="chat",
        comment="Un chat del director. Un director tiene varios; cada uno empieza con contexto limpio. RLS por colegio y, además, una política restrictiva por usuario: un director solo ve sus propios chats.",
    )
    op.create_index(
        "threads_user_idx",
        "threads",
        ["user_id", sa.literal_column("updated_at DESC")],
        unique=False,
        schema="chat",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "competencies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "subject_id",
            sa.UUID(),
            nullable=True,
            comment="El área curricular o taller al que pertenece esta competencia. Null solo para kind = 'transversal': las dos competencias transversales CNEB no están adscritas a un área ni a un solo docente (5.1.1.3 p.8), y cada IE decide cómo se asigna su nivel.",
        ),
        sa.Column(
            "code",
            sa.Text(),
            nullable=False,
            comment="Código del currículo nacional cuando existe, o un código propio del colegio si no.",
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Text(),
            server_default=sa.text("'area'::text"),
            nullable=False,
            comment="Qué cuenta esta competencia para la promoción (RVM 094-2020 num. 5.1.3 p.9-11). 'area': una competencia CNEB de un área curricular o taller — cuenta. 'adicional_area': una competencia agregada por el colegio y organizada en un área curricular — cuenta (5.1.3 p.11). 'adicional_libre': una competencia agregada por el colegio no organizada en un área — no cuenta (p.10). 'transversal': una de las dos competencias transversales CNEB — nunca cuenta (p.9), y no lleva subject_id.",
        ),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((kind = 'transversal'::text) = (subject_id IS NULL))",
            name="competencies_transversal_has_no_subject",
        ),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['area'::text, 'transversal'::text, 'adicional_area'::text, 'adicional_libre'::text]))",
            name="competencies_kind_check",
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="competencies_subject_fk"),
        sa.PrimaryKeyConstraint("id", name="competencies_pkey"),
        comment='Una competencia MINEDU dentro de una asignatura, ej. "Se comunica oralmente en inglés como lengua extranjera". Las evidencias (assessments) llegan aquí a través de sus criterios de evaluación.',
    )
    op.create_index(
        "competencies_subject_code_key",
        "competencies",
        ["subject_id", "code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "competencies_transversal_code_key",
        "competencies",
        ["code"],
        unique=True,
        postgresql_where=sa.text("((subject_id IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "courses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("grade_level_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column(
            "weekly_hours",
            sa.Numeric(precision=4, scale=2),
            nullable=True,
            comment="Horas semanales nominales según el plan de estudios. La cifra real viene de class_schedules; este es el plan contra el cual comparar.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(weekly_hours >= (0)::numeric)", name="courses_weekly_hours_check"),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="courses_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="courses_grade_level_fk"
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="courses_subject_fk"),
        sa.PrimaryKeyConstraint("id", name="courses_pkey"),
        sa.UniqueConstraint(
            "academic_year_id", "grade_level_id", "id", name="courses_year_grade_key"
        ),
        sa.UniqueConstraint("academic_year_id", "id", name="courses_year_key"),
        comment="Una asignatura dictada en un grado en un año determinado. Se ubica entre subjects y classes para que el currículo y la política de calificación se definan una vez por grado, no una vez por section.",
    )
    op.create_index(
        "courses_natural_key_coded",
        "courses",
        ["academic_year_id", "subject_id", "grade_level_id", "code"],
        unique=True,
        postgresql_where=sa.text("((code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "courses_natural_key_no_code",
        "courses",
        ["academic_year_id", "subject_id", "grade_level_id"],
        unique=True,
        postgresql_where=sa.text("((code IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "grade_scale_levels",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scale_id", sa.UUID(), nullable=False),
        sa.Column(
            "code",
            sa.Text(),
            nullable=False,
            comment='Lo que se imprime en la etiqueta: "AD", "A", "B", "C".',
        ),
        sa.Column(
            "label",
            sa.Text(),
            nullable=False,
            comment='Texto completo: "Logro destacado", "Logro esperado", "En proceso", "En inicio". Se muestran el label y el code juntos.',
        ),
        sa.Column("short_label", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column(
            "min_normalized",
            sa.Numeric(precision=6, scale=5),
            nullable=False,
            comment="Límite inferior inclusivo en el eje 0-1. Las bandas son semiabiertas [min, max), así que un valor cae en exactamente una banda.",
        ),
        sa.Column(
            "max_normalized",
            sa.Numeric(precision=6, scale=5),
            nullable=False,
            comment="Límite superior exclusivo, salvo en la banda más alta, que la búsqueda trata como cerrada para que un puntaje perfecto tenga un nivel.",
        ),
        sa.Column("color_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("scale_id"), "="),
            (sa.text("numrange(min_normalized, max_normalized, '[)'::text)"), "&&"),
            where=sa.text("(deleted_at IS NULL)"),
            using="gist",
            name="grade_scale_levels_no_gap_overlap",
        ),
        sa.CheckConstraint(
            "((max_normalized >= (0)::numeric) AND (max_normalized <= (1)::numeric))",
            name="grade_scale_levels_max_normalized_check",
        ),
        sa.CheckConstraint(
            "((min_normalized >= (0)::numeric) AND (min_normalized <= (1)::numeric))",
            name="grade_scale_levels_min_normalized_check",
        ),
        sa.CheckConstraint(
            "(max_normalized > min_normalized)", name="grade_scale_levels_band_valid"
        ),
        sa.ForeignKeyConstraint(
            ["scale_id"], ["grade_scales.id"], name="grade_scale_levels_scale_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="grade_scale_levels_pkey"),
        comment='Las bandas de una escala. Para AD/A/B/C estas son las notas reportadas; para una escala numérica son las bandas de color detrás del número. "Distribución de logros" agrupa por esta tabla, y "Logro esperado / A" lee label y code de una sola fila.',
    )
    op.create_index(
        "grade_scale_levels_lookup_idx",
        "grade_scale_levels",
        ["scale_id", "min_normalized", "max_normalized"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "grade_scale_levels_scale_code_key",
        "grade_scale_levels",
        ["scale_id", "code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(role = ANY (ARRAY['teacher'::text, 'student'::text, 'supervisor'::text, 'admin'::text, 'director'::text]))",
            name="memberships_role_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'revoked'::text]))",
            name="memberships_status_check",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="memberships_user_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="memberships_pkey"),
        comment="Qué usuario actúa en qué colegio, y con qué rol. El join que hace visible una fila de users bajo RLS, y la fila a la que resuelve un inicio de sesión. Cuatro roles: 'teacher' (el único que hoy puede completar un inicio de sesión), 'student', 'supervisor', 'admin'. Los otros tres están modelados — las verificaciones de permisos se escriben de forma genérica contra role — para poder habilitarlos más adelante solo ampliando domain.LoginEnabledRoles; un intento de inicio de sesión de uno de ellos hoy se rechaza con role_not_enabled. memberships_one_school_per_user limita a un usuario a exactamente un membership activo, así que el flujo de inicio de sesión nunca tiene que elegir entre varios.",
    )
    op.create_index(
        "memberships_one_school_per_user",
        "memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("((deleted_at IS NULL) AND (status <> 'revoked'::text))"),
    )
    op.create_index(
        "memberships_user_idx",
        "memberships",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "memberships_user_key",
        "memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "non_teaching_days",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="feriado: fecha cívica o feriado nacional/regional. vacaciones: día dentro de un periodo de vacaciones del año escolar. gestion: día de gestión pedagógica o administrativa (los colegios lo usan para reuniones y planificación, sin estudiantes).",
        ),
        sa.Column(
            "label",
            sa.Text(),
            nullable=True,
            comment='Nombre opcional para mostrar, ej. "San Pedro y San Pablo" o "Vacaciones de medio año". Null cuando el tipo basta.',
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['feriado'::text, 'vacaciones'::text, 'gestion'::text]))",
            name="non_teaching_days_kind_check",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="non_teaching_days_year_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="non_teaching_days_pkey"),
        sa.UniqueConstraint("academic_year_id", "id", name="non_teaching_days_year_key"),
        comment="Los días sin clase de un año escolar: feriados, vacaciones y días de gestión. Se cargan por onboarding (el colegio los declara, la app no los inventa) y sirven para excluir del conteo de sesiones de una experiencia las fechas que no son clase. Un rango de vacaciones se carga como una fila por día: el conteo y la exclusión son por fecha, y un rango obligaría a un chequeo de solapamiento de rangos para algo que es, en el fondo, un conjunto de fechas.",
    )
    op.create_index(
        "non_teaching_days_year_day_key",
        "non_teaching_days",
        ["academic_year_id", "day"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "non_teaching_days_year_idx",
        "non_teaching_days",
        ["academic_year_id", "day"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "capabilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "code",
            sa.Text(),
            nullable=False,
            comment="Código del currículo nacional cuando existe, o un código propio del colegio si no.",
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="capabilities_competency_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="capabilities_pkey"),
        sa.UniqueConstraint("competency_id", "id", name="capabilities_competency_key"),
        comment='Una capacidad MINEDU, ej. "Utiliza estrategias y conocimientos matemáticos" bajo la competencia "Resuelve problemas de cantidad".',
    )
    op.create_index(
        "capabilities_competency_code_key",
        "capabilities",
        ["competency_id", "code"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column(
            "protocol_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="PII (menor y adulto): texto libre. Bloques del protocolo v1 (estado, texto, tabla, grafico, error, fin) tal como los vio el modelo: los nombres de alumnos y profesores van seudonimizados (D001) y se restauran solo al mostrar.",
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="PII (menor y adulto): resultados de herramientas. Herramientas llamadas en el turno, con argumentos y resultados, seudonimizados igual que blocks.",
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(author = ANY (ARRAY['director'::text, 'mawta'::text]))", name="messages_author_check"
        ),
        sa.CheckConstraint("(jsonb_typeof(blocks) = 'array'::text)", name="messages_blocks_check"),
        sa.CheckConstraint(
            "(jsonb_typeof(tool_calls) = 'array'::text)", name="messages_tool_calls_check"
        ),
        sa.CheckConstraint("(input_tokens >= 0)", name="messages_input_tokens_check"),
        sa.CheckConstraint("(latency_ms >= 0)", name="messages_latency_ms_check"),
        sa.CheckConstraint("(output_tokens >= 0)", name="messages_output_tokens_check"),
        sa.CheckConstraint("(protocol_version >= 1)", name="messages_protocol_version_check"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["chat.threads.id"], name="messages_thread_fk", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="messages_user_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="messages_pkey"),
        schema="chat",
        comment="Cada mensaje de un chat, del director o de Mawta, con todo lo necesario para auditarlo y mejorar el chat después: bloques, herramientas usadas, modelo, tokens y latencia. user_id es el dueño del chat (desnormalizado) para la política restrictiva por usuario.",
    )
    op.create_index(
        "messages_thread_idx", "messages", ["thread_id", "created_at"], unique=False, schema="chat"
    )
    op.create_table(
        "learning_standards",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "level",
            sa.SmallInteger(),
            nullable=False,
            comment="Nivel del estándar, 1-8: un nivel por fin de ciclo de la EBR. El mapeo (modalidad, ciclo) → nivel vive en standard_level_mappings.",
        ),
        sa.Column(
            "official_text",
            sa.Text(),
            nullable=False,
            comment="El texto literal del CNEB. Nunca se redacta ni se parafrasea en la app.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((level >= 1) AND (level <= 8))", name="learning_standards_level_check"
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="learning_standards_competency_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="learning_standards_pkey"),
        sa.UniqueConstraint("competency_id", "id", name="learning_standards_competency_key"),
        comment="Los estándares de aprendizaje del CNEB: por competencia y nivel (1-8), con su texto oficial. Son la referencia con la que se redacta la conclusión descriptiva de fin de ciclo, nunca una fuente de criterios: el criterio proviene del desempeño de grado, el estándar describe el punto de llegada del ciclo.",
    )
    op.create_index(
        "learning_standards_competency_level_key",
        "learning_standards",
        ["competency_id", "level"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "teachers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("employee_code", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "title",
            sa.Text(),
            nullable=True,
            comment='Etiqueta de rol, ej. "Docente de Secundaria". Texto libre: los colegios lo redactan de forma inconsistente y es solo para mostrar.',
        ),
        sa.Column(
            "hired_on",
            sa.Date(),
            nullable=True,
            comment='Fecha de inicio en este colegio. A partir de este valor se muestra "Desde marzo 2021 · 5 años".',
        ),
        sa.Column(
            "weekly_hours_contracted",
            sa.Numeric(precision=5, scale=2),
            nullable=True,
            comment='Horas semanales contratadas. El valor mostrado como "30h Semanales" se calcula en cambio a partir de class_schedules; esta es la cifra del contrato contra la cual conciliar.',
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'on_leave'::text, 'inactive'::text]))",
            name="teachers_status_check",
        ),
        sa.CheckConstraint(
            "(weekly_hours_contracted >= (0)::numeric)",
            name="teachers_weekly_hours_contracted_check",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["memberships.id"], name="teachers_membership_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="teachers_pkey"),
        comment="PII (adulto). Perfil docente por colegio. display_name, title y hired_on se muestran directamente; el correo y el inicio de sesión viven en la fila de users vinculada.",
    )
    op.create_index(
        "teachers_employee_code_key",
        "teachers",
        ["employee_code"],
        unique=True,
        postgresql_where=sa.text("((employee_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "teachers_membership_key",
        "teachers",
        ["membership_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "token_hash",
            sa.LargeBinary(),
            nullable=False,
            comment="sha256 del token en crudo. El token en crudo solo existe en el header Set-Cookie y en el almacén de cookies del navegador — nunca se guarda, se registra en logs ni se devuelve de nuevo. sha256 en vez de bcrypt a propósito: la entrada son 256 bits de crypto/rand, ya inadivinables, así que no necesita factor de trabajo, y esto se lee en cada solicitud.",
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Text(),
            nullable=False,
            comment="Copiado del membership al iniciar sesión y verificado de nuevo contra el membership vigente en cada solicitud (internal/httpapi.sessionAuth), de modo que un rol revocado o degradado después del inicio de sesión surte efecto de inmediato en lugar de esperar a que expire la sesión.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Se actualiza como máximo una vez por hora por sesión (repo.TouchSession), no en cada solicitud — escribir en cada solicitud convertiría cada GET en una transacción de lectura-escritura.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Expiración absoluta, establecida al iniciar sesión a partir de SESSION_TTL. Nunca se extiende. La expiración por inactividad es una verificación aparte, calculada en Go a partir de last_seen_at contra SESSION_IDLE_TIMEOUT.",
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_reason",
            sa.Text(),
            nullable=True,
            comment="logout (iniciado por el usuario), expired/idle (revocado de forma perezosa al momento de la validación — no hay un scheduler en este código, ver internal/worker/SPEC.md, así que nada las depura de forma proactiva), password_change (cada sesión del usuario, al cambiar la contraseña), admin (reservado para una futura revocación iniciada por un administrador).",
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.CheckConstraint(
            "(revoked_reason = ANY (ARRAY['logout'::text, 'expired'::text, 'idle'::text, 'password_change'::text, 'admin'::text]))",
            name="user_sessions_revoked_reason_check",
        ),
        sa.CheckConstraint(
            "(role = ANY (ARRAY['teacher'::text, 'student'::text, 'supervisor'::text, 'admin'::text, 'director'::text]))",
            name="user_sessions_role_check",
        ),
        sa.CheckConstraint(
            "((revoked_at IS NULL) = (revoked_reason IS NULL))",
            name="user_sessions_revocation_consistent",
        ),
        sa.CheckConstraint("(expires_at > created_at)", name="user_sessions_expires_after_created"),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["memberships.id"], name="user_sessions_membership_fk"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="user_sessions_user_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="user_sessions_pkey"),
        comment="Sesiones del lado del servidor. El navegador guarda un token opaco de 256 bits en una cookie HttpOnly; aquí solo se almacena su sha256, así que leer esta tabla no permite suplantar a nadie. El único lector es el repositorio de autenticación de la API, siempre por token_hash exacto.",
    )
    op.create_index(
        "user_sessions_expiry_idx",
        "user_sessions",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("(revoked_at IS NULL)"),
    )
    op.create_index("user_sessions_token_hash_key", "user_sessions", ["token_hash"], unique=True)
    op.create_index(
        "user_sessions_user_idx",
        "user_sessions",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("(revoked_at IS NULL)"),
    )
    op.create_table(
        "question_bank",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
            comment="PII (menor y adulto): texto libre. La pregunta tal como la vio el modelo, seudonimizada (D001).",
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "tool_name",
            sa.Text(),
            nullable=True,
            comment="Herramienta que respondió, o la que habría hecho falta cuando status = necesita_tool.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['respondida'::text, 'necesita_tool'::text, 'parcial'::text, 'fuera_de_alcance'::text]))",
            name="question_bank_status_check",
        ),
        sa.CheckConstraint("(char_length(question) > 0)", name="question_bank_question_check"),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat.messages.id"],
            name="question_bank_message_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="question_bank_pkey"),
        schema="chat",
        comment="Banco de preguntas: cada pregunta del director y cómo terminó. necesita_tool marca las que el chat no pudo responder por falta de una herramienta; fuera_de_alcance, las que no le corresponden. Es a la vez el backlog de herramientas y la suite de evaluación.",
    )
    op.create_index(
        "question_bank_status_idx",
        "question_bank",
        ["status", "created_at"],
        unique=False,
        schema="chat",
    )
    op.create_table(
        "competency_exemptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            comment='Por qué se otorgó la exoneración, ej. "Objeción religiosa" o una excepción médica para Educación Física.',
        ),
        sa.Column(
            "document_ref",
            sa.Text(),
            nullable=True,
            comment="Referencia al documento de autorización de la UGEL, cuando el colegio conserva uno en archivo.",
        ),
        sa.Column(
            "authorized_by_id",
            sa.UUID(),
            nullable=True,
            comment="El miembro del personal que registró la exoneración en Mawta. No es la autoridad de la UGEL en sí — document_ref es donde se rastrea esa autorización.",
        ),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="competency_exemptions_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["authorized_by_id"], ["teachers.id"], name="competency_exemptions_authorized_by_fk"
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="competency_exemptions_competency_fk"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="competency_exemptions_student_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="competency_exemptions_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico, oficial). Una exoneración autorizada por la UGEL de una competencia para un estudiante en un año escolar (RVM 094-2020: exoneraciones de competencias asociadas a las áreas curriculares, ej. Educación Religiosa, Educación Física). El cierre de año lee esto para excluir el área del conteo de PRO/PER/RR en vez de tratarla como no evaluada.",
    )
    op.create_index(
        "competency_exemptions_key",
        "competency_exemptions",
        ["student_id", "competency_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "grade_level_performances",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column("grade_level_id", sa.UUID(), nullable=False),
        sa.Column(
            "sort_order",
            sa.SmallInteger(),
            nullable=False,
            comment="Posición del desempeño dentro de su competencia y grado. Los programas listan los desempeños en un orden pedagógico; ese orden se conserva para mostrarlos tal como aparecen en el documento oficial.",
        ),
        sa.Column(
            "official_text",
            sa.Text(),
            nullable=False,
            comment="El texto literal del programa (RM 649-2016). Nunca se redacta ni se parafrasea en la app: el currículo no se inventa.",
        ),
        sa.Column(
            "en_proceso",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment='La postura del desempeño frente al estándar del ciclo: true = "en proceso hacia" el nivel esperado, false = "logra" el nivel esperado. Los programas de un grado intermedio describen avances hacia el estándar del fin de ciclo; los del grado final del ciclo describen el logro.',
        ),
        sa.Column(
            "expected_standard_level",
            sa.SmallInteger(),
            nullable=False,
            comment="Nivel (1-8) del estándar de aprendizaje al que este desempeño apunta. Los programas lo declaran por grado; se guarda por fila para que el desempeño se lea junto al estándar correcto sin re-derivarlo del ciclo.",
        ),
        sa.Column(
            "suggested_capability_id",
            sa.UUID(),
            nullable=True,
            comment="INFERIDO, NO OFICIAL. Los programas no etiquetan desempeños por capacidad: este vínculo es una pista que se calcula al cargar el currículo y que el docente puede ignorar. Nunca reemplaza el juicio del docente sobre qué capacidades mira un criterio. La FK compuesta (competency_id, suggested_capability_id) garantiza que la pista apunte a una capacidad de la misma competencia.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((expected_standard_level >= 1) AND (expected_standard_level <= 8))",
            name="grade_level_performances_expected_standard_level_check",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id", "suggested_capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="grade_level_performances_suggested_capability_fk",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="grade_level_performances_competency_fk"
        ),
        sa.ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="grade_level_performances_grade_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="grade_level_performances_pkey"),
        sa.UniqueConstraint("competency_id", "id", name="grade_level_performances_competency_key"),
        sa.UniqueConstraint("grade_level_id", "id", name="grade_level_performances_grade_key"),
        comment="Los desempeños de grado del programa oficial: por competencia y por grado, con su texto oficial y su postura frente al estándar del ciclo. Es la única fuente de la que un criterio puede derivar (decisión 2 del flujo): un criterio es el precisado del docente de uno de estos textos en la situación de la experiencia.",
    )
    op.create_index(
        "grade_level_performances_grade_idx",
        "grade_level_performances",
        ["grade_level_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "grade_level_performances_order_key",
        "grade_level_performances",
        ["competency_id", "grade_level_id", "sort_order"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "sections",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("grade_level_id", sa.UUID(), nullable=False),
        sa.Column(
            "label", sa.Text(), nullable=False, comment='Solo la letra de la section, ej. "B".'
        ),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            comment='Forma de presentación que combina grado y letra, ej. "5to B". Se almacena en vez de derivarse porque cada colegio usa su propio espaciado y abreviaturas.',
        ),
        sa.Column(
            "tutor_teacher_id",
            sa.UUID(),
            nullable=True,
            comment="Tutor de aula. Distinto del docente de la clase de Tutoría, que se programa por separado.",
        ),
        sa.Column("shift", sa.Text(), server_default=sa.text("'manana'::text"), nullable=False),
        sa.Column("capacity", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(shift = ANY (ARRAY['manana'::text, 'tarde'::text, 'noche'::text, 'completo'::text]))",
            name="sections_shift_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'archived'::text]))", name="sections_status_check"
        ),
        sa.CheckConstraint("(capacity > 0)", name="sections_capacity_check"),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="sections_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="sections_grade_level_fk"
        ),
        sa.ForeignKeyConstraint(["tutor_teacher_id"], ["teachers.id"], name="sections_tutor_fk"),
        sa.PrimaryKeyConstraint("id", name="sections_pkey"),
        sa.UniqueConstraint(
            "academic_year_id", "grade_level_id", "id", name="sections_year_grade_key"
        ),
        sa.UniqueConstraint("academic_year_id", "id", name="sections_year_key"),
        comment='Un grupo de estudiantes que avanza junto en todas las asignaturas durante un año escolar, ej. "5to B". El roster: un estudiante pertenece a una section, y por lo tanto a cada class dictada a esa section.',
    )
    op.create_index(
        "sections_natural_key",
        "sections",
        ["academic_year_id", "grade_level_id", "label"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "sections_tutor_idx",
        "sections",
        ["tutor_teacher_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "terms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column(
            "stage",
            sa.Text(),
            nullable=True,
            comment="A qué nivel educativo aplica este term, para un colegio que usa estructuras de periodo distintas por nivel (ej. Primaria en trimestres, Secundaria en bimestres, en el mismo año escolar). Null significa que el term aplica a todos los niveles — el caso común de un colegio con un solo calendario.",
        ),
        sa.Column(
            "sequence",
            sa.SmallInteger(),
            nullable=False,
            comment="Posición ordinal dentro del año, acotada a (academic_year_id, stage). Bimestre II es sequence 2. Limitado a 6 para que un valor mal escrito no pueda crear un term fantasma.",
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'planned'::text"), nullable=False),
        sa.Column(
            "grades_due_on",
            sa.Date(),
            nullable=True,
            comment='Fecha límite para registrar notas. Impulsa los recordatorios de "notas pendientes".',
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo se cerró el term. Un term cerrado rechaza nuevas scores, que es lo que evita que una nota ya reportada cambie después.",
        ),
        sa.Column("closed_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("academic_year_id"), "="),
            (sa.text("COALESCE(stage, ''::text)"), "="),
            (sa.text("daterange(starts_on, ends_on, '[]'::text)"), "&&"),
            where=sa.text("(deleted_at IS NULL)"),
            using="gist",
            name="terms_no_overlap",
        ),
        sa.CheckConstraint(
            "((status = ANY (ARRAY['closed'::text, 'archived'::text])) = (closed_at IS NOT NULL))",
            name="terms_closed_consistent",
        ),
        sa.CheckConstraint(
            "(stage = ANY (ARRAY['inicial'::text, 'primaria'::text, 'secundaria'::text, 'otro'::text]))",
            name="terms_stage_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text, 'archived'::text]))",
            name="terms_status_check",
        ),
        sa.CheckConstraint("((sequence >= 1) AND (sequence <= 6))", name="terms_sequence_check"),
        sa.CheckConstraint("(ends_on > starts_on)", name="terms_range_valid"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="terms_year_fk"),
        sa.ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="terms_closed_by_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="terms_pkey"),
        sa.UniqueConstraint("academic_year_id", "id", name="terms_year_key"),
        comment='Un bimestre, trimestre o semestre dentro de una fila de academic_years. name se muestra como ("Bimestre II"); acota a un solo term todo un panel de actividad.',
    )
    op.create_index(
        "terms_one_active_key",
        "terms",
        ["academic_year_id", sa.literal_column("(COALESCE(stage, ''::text))")],
        unique=True,
        postgresql_where=sa.text("((status = 'active'::text) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "terms_range_idx",
        "terms",
        ["starts_on", "ends_on"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "terms_year_sequence_key",
        "terms",
        ["academic_year_id", sa.literal_column("(COALESCE(stage, ''::text))"), "sequence"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "year_final_situations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column(
            "grade_level_id",
            sa.UUID(),
            nullable=False,
            comment='El grado en que estaba el estudiante, porque la regla misma depende de esto: 1.°, 3.° y 4.° promueven con "B en la mitad o más de cada área", mientras que 2.° y 5.° — los grados de fin de ciclo — requieren "A o AD en la mitad o más de tres áreas y B en el resto" (cuadro 5.1.3.A, 048-2024).',
        ),
        sa.Column("situation", sa.Text(), nullable=False),
        sa.Column(
            "stage",
            sa.Text(),
            server_default=sa.text("'year_end'::text"),
            nullable=False,
            comment="'year_end': la situación al cierre del periodo lectivo, donde PRO/PER/RR son las tres posibles. 'post_recuperacion': recalculada tras el acompañamiento o evaluación de recuperación, que la norma trata como una determinación aparte que produce su propia acta (5.2.1.A p.4-6) — ahí solo PRO o PER son situaciones legales, nunca RR de nuevo, y yfs_post_recuperacion_situation_check lo hace cumplir.",
        ),
        sa.Column(
            "breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Los conteos por área a partir de los cuales se tomó la decisión, capturados como JSON: qué competencias se consideraron, en qué nivel, y qué áreas cumplieron la condición.",
        ),
        sa.Column(
            "closed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("closed_by_id", sa.UUID(), nullable=True),
        sa.Column("document_ref", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((stage <> 'post_recuperacion'::text) OR (situation = ANY (ARRAY['PRO'::text, 'PER'::text])))",
            name="yfs_post_recuperacion_situation_check",
        ),
        sa.CheckConstraint(
            "(situation = ANY (ARRAY['PRO'::text, 'PER'::text, 'RR'::text]))",
            name="year_final_situations_situation_check",
        ),
        sa.CheckConstraint(
            "(stage = ANY (ARRAY['year_end'::text, 'post_recuperacion'::text]))",
            name="year_final_situations_stage_check",
        ),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="yfs_year_fk"),
        sa.ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="yfs_closed_by_fk"),
        sa.ForeignKeyConstraint(["grade_level_id"], ["grade_levels.id"], name="yfs_grade_level_fk"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="yfs_student_fk"),
        sa.PrimaryKeyConstraint("id", name="year_final_situations_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico, oficial). La situación final que lleva el Acta Oficial: PRO (promovido), PER (permanece) o RR (requiere recuperación) — las siglas que la norma nombra en 5.1.2.1.c p.5. Inmutable una vez escrita.",
    )
    op.create_index(
        "yfs_key",
        "year_final_situations",
        ["student_id", "academic_year_id", "stage"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "classes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column(
            "grade_level_id",
            sa.UUID(),
            nullable=False,
            comment="Copiado del grado de la course/section que dicta. No es una fuente independiente de verdad: existe para que classes_course_fk/classes_section_fk puedan ser compuestas sobre él y así impedir una class que mezcle una course de un grado con una section de otro.",
        ),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            comment='Nombre para mostrar. Se almacena porque es la cadena sobre la que buscan los docentes, y porque "Historia 5to C" y "Math 8B" no siguen una única regla de derivación.',
        ),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("default_room", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'archived'::text, 'cancelled'::text]))",
            name="classes_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "grade_level_id", "course_id"],
            ["courses.academic_year_id", "courses.grade_level_id", "courses.id"],
            name="classes_course_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "grade_level_id", "section_id"],
            ["sections.academic_year_id", "sections.grade_level_id", "sections.id"],
            name="classes_section_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="classes_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="classes_grade_level_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="classes_pkey"),
        sa.UniqueConstraint("academic_year_id", "id", name="classes_year_key"),
        comment='Una course dictada a una section: "Inglés 5to B". La unidad en la que realmente trabaja el docente — casi toda la aplicación se enfoca en una sola class. classes_course_fk/classes_section_fk son compuestas sobre academic_year_id y grade_level_id, así que una class no puede apuntar a una course o section de un año distinto al suyo, ni combinar una course y una section de grados distintos entre sí.',
    )
    op.create_index(
        "classes_course_section_key",
        "classes",
        ["course_id", "section_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "classes_name_trgm_idx",
        "classes",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "classes_section_idx",
        "classes",
        ["section_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "section_memberships",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column(
            "left_on",
            sa.Date(),
            nullable=True,
            comment="Fecha de fin exclusiva. Null mientras el estudiante sigue en la section. Un estudiante que se va a mitad de bimestre conserva toda fila previa de asistencia y de score.",
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("student_id"), "="),
            (sa.column("academic_year_id"), "="),
            (sa.text("daterange(joined_on, left_on, '[)'::text)"), "&&"),
            where=sa.text("(deleted_at IS NULL)"),
            using="gist",
            name="section_memberships_one_at_a_time",
        ),
        sa.CheckConstraint(
            "((status = 'active'::text) = (left_on IS NULL))",
            name="section_memberships_active_consistent",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'withdrawn'::text, 'transferred'::text, 'promoted'::text]))",
            name="section_memberships_status_check",
        ),
        sa.CheckConstraint(
            "((left_on IS NULL) OR (left_on >= joined_on))", name="section_memberships_range_valid"
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="section_memberships_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name="section_memberships_section_fk"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="section_memberships_student_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="section_memberships_pkey"),
        comment="DATOS PERSONALES DE MENORES (asociación). El roster temporal: qué estudiante estuvo en qué section, durante qué fechas dentro de un año escolar. El roster de una clase se deriva de aquí, así que los denominadores de asistencia siempre se evalúan a la fecha de la sesión y no a la fecha de hoy.",
    )
    op.create_index(
        "section_memberships_section_idx",
        "section_memberships",
        ["section_id", "joined_on", "left_on"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "section_memberships_student_idx",
        "section_memberships",
        ["student_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "class_schedules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column(
            "weekday",
            sa.SmallInteger(),
            nullable=False,
            comment="Día de la semana ISO-8601, 1 = lunes .. 7 = domingo. Coincide con extract(isodow), para que el generador pueda hacer join sin aritmética.",
        ),
        sa.Column(
            "starts_at",
            sa.Time(),
            nullable=False,
            comment='Hora local de reloj en la zona horaria del colegio. Deliberadamente no es timestamptz: "10:00 los lunes" debe sobrevivir a un cambio de horario tipo DST, y el instante UTC concreto se materializa en class_sessions.',
        ),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.Column("room", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("class_id"), "="),
            (sa.column("weekday"), "="),
            (sa.text("timerange(starts_at, ends_at, '[)'::text)"), "&&"),
            (sa.text("daterange(effective_from, effective_to, '[)'::text)"), "&&"),
            where=sa.text("(deleted_at IS NULL)"),
            using="gist",
            name="class_schedules_no_overlap",
        ),
        sa.CheckConstraint(
            "((effective_to IS NULL) OR (effective_to > effective_from))",
            name="class_schedules_range_valid",
        ),
        sa.CheckConstraint(
            "((weekday >= 1) AND (weekday <= 7))", name="class_schedules_weekday_check"
        ),
        sa.CheckConstraint("(ends_at > starts_at)", name="class_schedules_time_valid"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="class_schedules_class_fk"),
        sa.PrimaryKeyConstraint("id", name="class_schedules_pkey"),
        comment="El patrón semanal recurrente de una class: una fila por franja semanal. Distinto de class_sessions, que son las instancias concretas con fecha. Un cambio de horario cierra la fila antigua con effective_to y abre una nueva, así que las sesiones pasadas se siguen explicando por sí mismas.",
    )
    op.create_index(
        "class_schedules_class_idx",
        "class_schedules",
        ["class_id", "weekday"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "class_schedules_effective_idx",
        "class_schedules",
        ["effective_from", "effective_to"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "class_teachers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'titular'::text"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("class_id"), "="),
            (sa.text("daterange(starts_on, ends_on, '[)'::text)"), "&&"),
            where=sa.text("((role = 'titular'::text) AND (deleted_at IS NULL))"),
            using="gist",
            name="class_teachers_one_titular",
        ),
        sa.CheckConstraint(
            "(role = ANY (ARRAY['titular'::text, 'auxiliar'::text, 'practicante'::text, 'reemplazo'::text]))",
            name="class_teachers_role_check",
        ),
        sa.CheckConstraint(
            "((ends_on IS NULL) OR (ends_on >= starts_on))", name="class_teachers_range_valid"
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="class_teachers_class_fk"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name="class_teachers_teacher_fk"),
        sa.PrimaryKeyConstraint("id", name="class_teachers_pkey"),
        comment="Quién dicta una class, en qué calidad, durante qué fechas. Una class tiene exactamente un titular a la vez y cualquier número de auxiliares.",
    )
    op.create_index(
        "class_teachers_key",
        "class_teachers",
        ["class_id", "teacher_id", "starts_on"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "class_teachers_teacher_idx",
        "class_teachers",
        ["teacher_id", "starts_on", "ends_on"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "competency_term_levels",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "academic_year_id",
            sa.UUID(),
            nullable=False,
            comment="Copiado del academic_year_id de la class desde la que se afirmó el nivel. Existe para que ctl_recuperacion_key pueda acotar la unicidad de las filas sin term (recuperación) a un año, ya que term_id nulo no sirve por sí solo para eso, y para que ctl_term_year_fk/ctl_class_year_fk sean compuestas sobre esta columna — así una fila del año 2026 no puede apuntar a un term o class de otro año.",
        ),
        sa.Column(
            "term_id",
            sa.UUID(),
            nullable=True,
            comment="El periodo regular para el que se afirmó este nivel. Nulable: un nivel proveniente de recuperación pedagógica o evaluación de subsanación puede afirmarse sin un term regular detrás. ctl_regular_key cubre las filas con term; ctl_recuperacion_key cubre las filas sin term, acotadas por academic_year_id en su lugar — un índice único no puede comparar dos NULL como iguales, así que term_id solo no bastaría para dar la misma garantía a esas filas.",
        ),
        sa.Column(
            "class_id",
            sa.UUID(),
            nullable=True,
            comment="Desde qué class afirmó el docente, para trazabilidad y permisos. No forma parte de la identidad del registro: la norma conoce competencias y periodos, no classes, y una competencia obtiene exactamente un nivel por periodo.",
        ),
        sa.Column(
            "scale_level_id",
            sa.UUID(),
            nullable=False,
            comment="El nivel afirmado, como una fila de grade_scale_levels (AD/A/B/C en la escala ordinal MINEDU). El único valor que es oficial.",
        ),
        sa.Column(
            "asserted_by_id",
            sa.UUID(),
            nullable=True,
            comment="El docente que hizo el juicio. Nulable: una competencia transversal no está adscrita a un solo docente, así que su nivel puede afirmarse sin uno.",
        ),
        sa.Column(
            "asserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Se establece cuando una corrección reemplaza esta fila. Null significa vigente. Se escribe antes de insertar el reemplazo, ya que ctl_regular_key/ctl_recuperacion_key admiten solo una fila vigente por estudiante, competencia y term (o año, sin term).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "class_id"],
            ["classes.academic_year_id", "classes.id"],
            name="ctl_class_year_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="ctl_term_year_fk",
        ),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="ctl_year_fk"),
        sa.ForeignKeyConstraint(["asserted_by_id"], ["teachers.id"], name="ctl_asserted_by_fk"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="ctl_competency_fk"),
        sa.ForeignKeyConstraint(["scale_level_id"], ["grade_scale_levels.id"], name="ctl_level_fk"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="ctl_student_fk"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["competency_term_levels.id"], name="ctl_supersedes_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="competency_term_levels_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico, oficial). El nivel de logro de una competencia para un estudiante en un periodo — la fila que va a SIAGIE y, al cierre del año, decide la situación final. Escrito por el juicio de un docente sobre la evidencia del periodo (5.1.1.3 p.2-3), nunca por un cálculo. Una competencia no desarrollada ni evaluada explícitamente en el periodo simplemente no tiene fila (5.1.2.2 p.1) — la ausencia es significativa y no debe leerse como C.",
    )
    op.create_index(
        "ctl_class_term_idx",
        "competency_term_levels",
        ["class_id", "term_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "ctl_recuperacion_key",
        "competency_term_levels",
        ["student_id", "competency_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text(
            "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.create_index(
        "ctl_regular_key",
        "competency_term_levels",
        ["student_id", "competency_id", "term_id"],
        unique=True,
        postgresql_where=sa.text(
            "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.create_index(
        "ctl_student_idx",
        "competency_term_levels",
        ["student_id", "term_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "learning_experiences",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column(
            "academic_year_id",
            sa.UUID(),
            nullable=False,
            comment="Copiado del term. No es una fuente independiente de verdad: existe para que learning_experiences_term_fk sea compuesta sobre él, lo que hace estructuralmente imposible que una experiencia apunte a un term de otro año escolar.",
        ),
        sa.Column("term_id", sa.UUID(), nullable=False),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            comment='Título con el que el docente reconoce la experiencia, ej. "La feria matemática del 5to B".',
        ),
        sa.Column(
            "idea_text",
            sa.Text(),
            nullable=False,
            comment='La idea original del docente, tal como la escribió en "Tengo una idea". Es la semilla de la experiencia y no se reescribe: la propuesta de Mawta se acepta o se edita aparte.',
        ),
        sa.Column(
            "situation_text",
            sa.Text(),
            nullable=True,
            comment="La situación significativa en la que la experiencia se desarrolla (CNEB). Null mientras aún no se ha redactado: la propuesta de Mawta puede llenarla, y el docente siempre decide.",
        ),
        sa.Column(
            "starts_on",
            sa.Date(),
            nullable=False,
            comment="Primer día de la experiencia, inclusive. Debe caer dentro del term (check_experience_inside_term) y no solaparse con otra experiencia de la misma class (learning_experiences_no_overlap).",
        ),
        sa.Column(
            "ends_on",
            sa.Date(),
            nullable=False,
            comment="Último día de la experiencia, inclusive. Misma regla que starts_on.",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'borrador'::text"),
            nullable=False,
            comment='borrador: la experiencia se está armando y cada paso ya quedó guardado. planificada: el docente la confirmó en "Revisar y guardar". El solapamiento de fechas se exige en ambos estados, así que un borrador también reserva sus semanas.',
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "context_text",
            sa.Text(),
            nullable=True,
            comment="Evento o contexto que escribe el docente. Única fuente permitida de un evento en lo que genera el agente; nulo = ningún evento.",
        ),
        postgresql.ExcludeConstraint(
            (sa.column("class_id"), "="),
            (sa.text("daterange(starts_on, ends_on, '[]'::text)"), "&&"),
            where=sa.text("(deleted_at IS NULL)"),
            using="gist",
            name="learning_experiences_no_overlap",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['borrador'::text, 'planificada'::text]))",
            name="learning_experiences_status_check",
        ),
        sa.CheckConstraint("(starts_on <= ends_on)", name="learning_experiences_range_valid"),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="learning_experiences_term_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="learning_experiences_year_fk"
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="learning_experiences_class_fk"),
        sa.PrimaryKeyConstraint("id", name="learning_experiences_pkey"),
        sa.UniqueConstraint("academic_year_id", "id", name="learning_experiences_year_key"),
        sa.UniqueConstraint("class_id", "id", name="learning_experiences_class_key"),
        comment="Una experiencia de aprendizaje: la unidad con la que un docente planifica un periodo para una class. Nace de la idea del docente (idea_text), se concreta en una situación (situation_text) y trabaja una o más competencias del área de la class (experience_competencies). Vive dentro de un term y sus fechas no pueden solaparse con las de otra experiencia de la misma class.",
    )
    op.create_index(
        "learning_experiences_class_range_idx",
        "learning_experiences",
        ["class_id", "starts_on", "ends_on"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "learning_experiences_term_idx",
        "learning_experiences",
        ["term_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "class_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "academic_year_id",
            sa.UUID(),
            nullable=False,
            comment="Copiado del academic_year_id de la class al crear la sesión. class_sessions_class_fk/class_sessions_term_fk son compuestas sobre esta columna, así que una sesión no puede apuntar a un term de un año distinto al de su class.",
        ),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column(
            "schedule_id",
            sa.UUID(),
            nullable=True,
            comment="La franja recurrente de la que proviene esta instancia. Null para una sesión puntual agregada a mano, para que una clase de reposición ad hoc sea representable sin inventar una regla semanal.",
        ),
        sa.Column("term_id", sa.UUID(), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'scheduled'::text"), nullable=False),
        sa.Column(
            "topic",
            sa.Text(),
            nullable=True,
            comment='Qué cubre la sesión, ej. "Present perfect tense". Se muestra tanto para la próxima sesión como para las pasadas.',
        ),
        sa.Column("room", sa.Text(), nullable=True),
        sa.Column("started_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "attendance_taken_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Null significa que la asistencia nunca se marcó, que es exactamente lo que activa el recordatorio de "Asistencia sin marcar". Distinto de una sesión donde todos estuvieron ausentes.',
        ),
        sa.Column("attendance_taken_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((status = ANY (ARRAY['in_progress'::text, 'completed'::text])) <= (actual_start_at IS NOT NULL))",
            name="class_sessions_started_consistent",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['scheduled'::text, 'in_progress'::text, 'completed'::text, 'cancelled'::text, 'rescheduled'::text]))",
            name="class_sessions_status_check",
        ),
        sa.CheckConstraint(
            "((actual_end_at IS NULL) OR (actual_start_at IS NULL) OR (actual_end_at >= actual_start_at))",
            name="class_sessions_actual_valid",
        ),
        sa.CheckConstraint(
            "((attendance_taken_at IS NULL) = (attendance_taken_by_id IS NULL))",
            name="class_sessions_attendance_consistent",
        ),
        sa.CheckConstraint(
            "(scheduled_end_at > scheduled_start_at)", name="class_sessions_window_valid"
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "class_id"],
            ["classes.academic_year_id", "classes.id"],
            name="class_sessions_class_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="class_sessions_term_fk",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="class_sessions_year_fk"
        ),
        sa.ForeignKeyConstraint(
            ["attendance_taken_by_id"], ["teachers.id"], name="class_sessions_attendance_by_fk"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["class_schedules.id"], name="class_sessions_schedule_fk"
        ),
        sa.ForeignKeyConstraint(
            ["started_by_id"], ["teachers.id"], name="class_sessions_started_by_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="class_sessions_pkey"),
        comment='Una instancia con fecha concreta de una class. Ciclo de vida scheduled -> in_progress -> completed, con cancelled y rescheduled como alternativas terminales. La tarjeta "HOY · SIN INICIAR" es una fila scheduled para hoy; el botón "Iniciar clase" la mueve a in_progress y registra actual_start_at.',
    )
    op.create_index(
        "class_sessions_attendance_pending_idx",
        "class_sessions",
        ["session_date"],
        unique=False,
        postgresql_where=sa.text(
            "((attendance_taken_at IS NULL) AND (status = ANY (ARRAY['in_progress'::text, 'completed'::text])) AND (deleted_at IS NULL))"
        ),
    )
    op.create_index(
        "class_sessions_class_date_idx",
        "class_sessions",
        ["class_id", sa.literal_column("session_date DESC")],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "class_sessions_class_start_key",
        "class_sessions",
        ["class_id", "scheduled_start_at"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "class_sessions_date_idx",
        "class_sessions",
        ["session_date", "status"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "class_sessions_term_idx",
        "class_sessions",
        ["term_id", "status"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "competency_year_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("scale_level_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_term_id",
            sa.UUID(),
            nullable=True,
            comment="El último periodo en que se trabajó esta competencia — de donde se copió el nivel. Nulable: la fila de competency_term_levels de origen puede no llevar term (un nivel afirmado a partir de evidencia de recuperación), en cuyo caso no hay periodo regular que registrar aquí.",
        ),
        sa.Column(
            "source_level_id",
            sa.UUID(),
            nullable=False,
            comment="La fila exacta de competency_term_levels copiada, para poder rastrear el snapshot hasta el docente que la afirmó.",
        ),
        sa.Column(
            "closed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("closed_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="cys_year_fk"),
        sa.ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="cys_closed_by_fk"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="cys_competency_fk"),
        sa.ForeignKeyConstraint(["scale_level_id"], ["grade_scale_levels.id"], name="cys_level_fk"),
        sa.ForeignKeyConstraint(
            ["source_level_id"], ["competency_term_levels.id"], name="cys_source_level_fk"
        ),
        sa.ForeignKeyConstraint(["source_term_id"], ["terms.id"], name="cys_source_term_fk"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="cys_student_fk"),
        sa.PrimaryKeyConstraint("id", name="competency_year_snapshots_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico, oficial). El nivel de cierre de año, congelado, de una competencia, tomado del último periodo en que se trabajó (5.1.2.2 p.3). Inmutable una vez escrito: es a partir de esto que se emiten el Acta Oficial y el Certificado de Estudios.",
    )
    op.create_index(
        "cys_key",
        "competency_year_snapshots",
        ["student_id", "competency_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "evaluation_criteria",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "capability_id",
            sa.UUID(),
            nullable=True,
            comment="DEPRECATED: el vínculo criterio ↔ capacidad vive en evaluation_criterion_capabilities, que permite varias capacidades por criterio. Esta columna se mantiene (nullable, no eliminada) para que el código actual siga corriendo mientras las pantallas nuevas la reemplazan; la migración copió su valor a la tabla de join.",
        ),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "experience_id",
            sa.UUID(),
            nullable=True,
            comment="La experiencia a la que pertenece este criterio. Null para los criterios globales por competencia que ya existían: siguen siendo válidos y visibles en las pantallas actuales hasta que el flujo de planificación los reemplace.",
        ),
        sa.Column(
            "performance_id",
            sa.UUID(),
            nullable=True,
            comment="El desempeño de grado del que este criterio deriva (decisión 2 del flujo): un criterio es el precisado del docente de ese desempeño en la situación de la experiencia. Null cuando el docente lo escribió sin partir de un desempeño cargado. La FK compuesta (competency_id, performance_id) prueba que el desempeño es de la misma competencia del criterio.",
        ),
        sa.Column(
            "proposed_by",
            sa.Text(),
            server_default=sa.text("'teacher'::text"),
            nullable=False,
            comment="Quién redactó el criterio: 'mawta' (propuesta del asistente) o 'teacher' (el docente). El default es 'teacher' para que los criterios existentes, migrados sin este dato, no aparezcan como propuestas de la máquina.",
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo el docente aceptó o editó la propuesta. Null mientras la propuesta está pendiente: una propuesta de Mawta no es un criterio hasta que el docente la acepta o la edita.",
        ),
        sa.CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="evaluation_criteria_proposed_by_check",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id", "capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="evaluation_criteria_capability_fk",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id", "performance_id"],
            ["grade_level_performances.competency_id", "grade_level_performances.id"],
            name="evaluation_criteria_performance_fk",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="evaluation_criteria_competency_fk"
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="evaluation_criteria_experience_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="evaluation_criteria_pkey"),
        comment='Un criterio de evaluación: el precisado propio del docente de un desempeño, ej. "Explica su punto de vista citando el texto" bajo la capacidad "Reflexiona y evalúa la forma, el contenido y contexto del texto". Esta es la capa que los docentes cargan en el sistema para evaluar una competencia.',
    )
    op.create_index(
        "evaluation_criteria_capability_idx",
        "evaluation_criteria",
        ["capability_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "evaluation_criteria_competency_idx",
        "evaluation_criteria",
        ["competency_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "evaluation_criteria_experience_idx",
        "evaluation_criteria",
        ["experience_id"],
        unique=False,
        postgresql_where=sa.text("((experience_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "evaluation_criteria_performance_idx",
        "evaluation_criteria",
        ["performance_id"],
        unique=False,
        postgresql_where=sa.text("((performance_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "experience_competencies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experience_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="experience_competencies_competency_fk"
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["learning_experiences.id"],
            name="experience_competencies_experience_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="experience_competencies_pkey"),
        sa.UniqueConstraint("competency_id", "id", name="experience_competencies_competency_key"),
        sa.UniqueConstraint("experience_id", "id", name="experience_competencies_experience_key"),
        comment="Qué competencias trabaja una experiencia de aprendizaje. Una experiencia trabaja una o más competencias del área de la class (decisión 1 del flujo); esta tabla es ese vínculo N:M y es lo que hace computable el seguimiento entre periodos: qué competencia se trabajó en qué term es una consulta sobre esta tabla, sin tabla resumen.",
    )
    op.create_index(
        "experience_competencies_competency_idx",
        "experience_competencies",
        ["competency_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "experience_competencies_pair_key",
        "experience_competencies",
        ["experience_id", "competency_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "planned_evidences",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experience_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment='Los dos tipos que nombra la norma: "Evidencias. Producciones y/o actuaciones realizadas por los estudiantes" (RVM 094-2020, glosario p.9). produccion: algo que los estudiantes elaboran (maqueta, informe, portafolio, una prueba escrita). actuacion: algo que hacen frente a otros (exposición, debate, demostración). Es el mismo vocabulario que assessments.kind, así que la evidencia planificada se materializa con su tipo sin traducirlo.',
        ),
        sa.Column(
            "value_scale",
            sa.Text(),
            server_default=sa.text("'numeric'::text"),
            nullable=False,
            comment="Cómo se valorará esta evidencia cuando se materialice como assessment: numeric (nota sobre max_score) u ordinal (AD/A/B/C). Se elige al planificar, porque los criterios y la tarea se comunican a los estudiantes con anticipación.",
        ),
        sa.Column(
            "max_score",
            sa.Numeric(precision=8, scale=4),
            server_default=sa.text("20"),
            nullable=True,
            comment="El máximo de la nota cuando value_scale = numeric (por defecto 20). Null cuando es ordinal.",
        ),
        sa.Column(
            "session_entry_id",
            sa.UUID(),
            nullable=True,
            comment="La entrada del esquema de sesiones donde se planea recoger esta evidencia. Null cuando aún no se ha ubicado en una sesión. La FK es compuesta (experience_id, session_entry_id), así que la evidencia no puede ubicarse en una sesión de otra experiencia.",
        ),
        sa.Column(
            "proposed_by",
            sa.Text(),
            server_default=sa.text("'teacher'::text"),
            nullable=False,
            comment="Quién propuso la evidencia: 'mawta' (el asistente) o 'teacher' (el docente). El default es 'teacher'.",
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((value_scale = 'numeric'::text) = (max_score IS NOT NULL))",
            name="planned_evidences_max_score_matches_scale",
        ),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['produccion'::text, 'actuacion'::text]))",
            name="planned_evidences_kind_check",
        ),
        sa.CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="planned_evidences_proposed_by_check",
        ),
        sa.CheckConstraint(
            "(value_scale = ANY (ARRAY['numeric'::text, 'ordinal'::text]))",
            name="planned_evidences_value_scale_check",
        ),
        sa.CheckConstraint("(max_score > (0)::numeric)", name="planned_evidences_max_score_check"),
        sa.ForeignKeyConstraint(
            ["experience_id", "session_entry_id"],
            ["session_outline_entries.experience_id", "session_outline_entries.id"],
            name="planned_evidences_session_entry_fk",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="planned_evidences_experience_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="planned_evidences_pkey"),
        sa.UniqueConstraint("experience_id", "id", name="planned_evidences_experience_key"),
        comment="Una evidencia planificada dentro de una experiencia: qué se va a observar (name), de qué tipo (kind) y contra qué criterios (planned_evidence_criteria). Es una PROMESA, no la evidencia real: la evidencia valorable es la assessment en la que se materializa al planificar la experiencia (assessments.planned_evidence_id).",
    )
    op.create_index(
        "planned_evidences_experience_idx",
        "planned_evidences",
        ["experience_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column(
            "term_id",
            sa.UUID(),
            nullable=True,
            comment="El term al que pertenece esta evidencia. Nulable: una recuperación pedagógica o evaluación de subsanación suele ocurrir fuera del periodo lectivo regular, así que no tiene term que cerrar.",
        ),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "student_id",
            sa.UUID(),
            nullable=True,
            comment="Null significa que la evidencia aplica a toda la class, que es el caso original y sigue siendo el más común. Si está definido, es evidencia solo para ese estudiante, ej. una tarea de recuperación dada a uno solo.",
        ),
        sa.Column(
            "kind",
            sa.Text(),
            server_default=sa.text("'produccion'::text"),
            nullable=False,
            comment="Producción (algo que los estudiantes elaboran) o actuación (algo que hacen frente a otros): los dos tipos de evidencia que nombra la RVM 094-2020 (glosario p.9). Mismo vocabulario que planned_evidences.kind.",
        ),
        sa.Column(
            "value_scale",
            sa.Text(),
            server_default=sa.text("'numeric'::text"),
            nullable=False,
            comment="Cómo se valora esta evidencia, y es una propiedad de la evidencia, no de la pantalla. 'numeric': una nota cruda sobre max_score (el máximo lo fija el docente), que la interfaz presenta como porcentaje. 'ordinal': un nivel AD/A/B/C sobre esa evidencia. Ninguno de los dos es un nivel de logro: el nivel de una competencia se afirma en competency_term_levels por un docente que ha leído todo el periodo, y nada puede derivarlo de estos valores.",
        ),
        sa.Column(
            "max_score",
            sa.Numeric(precision=8, scale=4),
            nullable=True,
            comment="El denominador sobre el que se mide cada score de esta evidencia, ej. 20 o 18. Solo aplica a value_scale = 'numeric'; null cuando es 'ordinal'.",
        ),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Fecha límite. Define qué evidencias cuentan como pendientes de valorar en el dashboard de la class.",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'draft'::text"),
            nullable=False,
            comment="draft es invisible para el docente en la pantalla de valoración. Una evidencia debe publicarse antes de poder recibir scores.",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "planned_evidence_id",
            sa.UUID(),
            nullable=True,
            comment="La evidencia planificada de la que esta assessment se materializó al planificar la experiencia. Null para la evidencia registrada a mano. A lo sumo una assessment viva por evidencia planificada (assessments_planned_evidence_key).",
        ),
        sa.CheckConstraint(
            "((status = 'closed'::text) = (closed_at IS NOT NULL))",
            name="assessments_closed_consistent",
        ),
        sa.CheckConstraint(
            "((status = ANY (ARRAY['published'::text, 'closed'::text])) <= (published_at IS NOT NULL))",
            name="assessments_published_consistent",
        ),
        sa.CheckConstraint(
            "((value_scale = 'numeric'::text) = (max_score IS NOT NULL))",
            name="assessments_max_score_matches_scale",
        ),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['produccion'::text, 'actuacion'::text]))",
            name="assessments_kind_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['draft'::text, 'published'::text, 'closed'::text, 'cancelled'::text]))",
            name="assessments_status_check",
        ),
        sa.CheckConstraint(
            "(value_scale = ANY (ARRAY['numeric'::text, 'ordinal'::text]))",
            name="assessments_value_scale_check",
        ),
        sa.CheckConstraint("(max_score > (0)::numeric)", name="assessments_max_score_check"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="assessments_class_fk"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["teachers.id"], name="assessments_created_by_fk"
        ),
        sa.ForeignKeyConstraint(
            ["planned_evidence_id"],
            ["planned_evidences.id"],
            name="assessments_planned_evidence_fk",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="assessments_session_fk"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="assessments_student_fk"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], name="assessments_term_fk"),
        sa.PrimaryKeyConstraint("id", name="assessments_pkey"),
        comment='DATOS PERSONALES DE MENORES (académico, cuando student_id está definido). Una evidencia de una class: lo que los estudiantes producen o actúan y que el docente valora contra criterios de evaluación. Nace de una evidencia planificada (planned_evidence_id) o la crea el docente con "Añadir evidencia". Se valora en una sola escala (value_scale) y nunca lleva peso: informa el juicio del docente sobre el nivel de logro de la competencia y no lo calcula. Con student_id definido es evidencia de un solo estudiante, ej. una tarea de recuperación, y por eso la tabla se declara portadora de datos de menores.',
    )
    op.create_index(
        "assessments_class_term_idx",
        "assessments",
        ["class_id", "term_id", "status"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "assessments_due_idx",
        "assessments",
        ["due_at"],
        unique=False,
        postgresql_where=sa.text("((status = 'published'::text) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "assessments_planned_evidence_key",
        "assessments",
        ["planned_evidence_id"],
        unique=True,
        postgresql_where=sa.text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "assessments_session_idx",
        "assessments",
        ["session_id"],
        unique=False,
        postgresql_where=sa.text("((session_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "assessments_student_idx",
        "assessments",
        ["class_id", "term_id", "student_id"],
        unique=False,
        postgresql_where=sa.text("((student_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "class_id",
            sa.UUID(),
            nullable=False,
            comment="Desnormalizado desde la sesión. Presente para que las tasas de asistencia por class no necesiten un join, y se mantiene por trigger en vez de por la aplicación.",
        ),
        sa.Column(
            "session_date",
            sa.Date(),
            nullable=False,
            comment="Desnormalizado desde la sesión. La regla de ausencias consecutivas recorre los registros de un estudiante en orden de fecha; sin esto el recorrido necesitaría un join y un ordenamiento en cada evaluación.",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="excused y justified son distintos: excused significa que el colegio autorizó la ausencia por adelantado, justified significa que se aceptó un motivo válido después. Ambas son ausencias para la familia, ninguna cuenta en contra del estudiante.",
        ),
        sa.Column("minutes_late", sa.SmallInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Text(),
            server_default=sa.text("'manual'::text"),
            nullable=False,
            comment='Cómo se creó la fila. bulk marca un toque de "Todos presentes", lo cual vale la pena distinguir de los toques individuales al juzgar qué tan confiable es el dato.',
        ),
        sa.Column("recorded_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((minutes_late IS NULL) OR (status = 'late'::text))",
            name="attendance_records_late_consistent",
        ),
        sa.CheckConstraint(
            "(source = ANY (ARRAY['manual'::text, 'bulk'::text, 'import'::text, 'auto'::text]))",
            name="attendance_records_source_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['present'::text, 'late'::text, 'absent'::text, 'excused'::text, 'justified'::text]))",
            name="attendance_records_status_check",
        ),
        sa.CheckConstraint("(minutes_late >= 0)", name="attendance_records_minutes_late_check"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="attendance_records_class_fk"),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"], ["teachers.id"], name="attendance_records_recorded_by_fk"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="attendance_records_session_fk"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="attendance_records_student_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="attendance_records_pkey"),
        comment='DATOS PERSONALES DE MENORES (conductuales). Una fila por estudiante por sesión. Se registran con un toque a la vez o en bloque vía "Todos presentes"; de aquí se lee la "Asistencia 94%".',
    )
    op.create_index(
        "attendance_records_class_date_idx",
        "attendance_records",
        ["class_id", "session_date"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "attendance_records_session_idx",
        "attendance_records",
        ["session_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "attendance_records_session_student_key",
        "attendance_records",
        ["session_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "attendance_records_student_date_idx",
        "attendance_records",
        ["student_id", sa.literal_column("session_date DESC")],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "evaluation_criterion_capabilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("criterion_id", sa.UUID(), nullable=False),
        sa.Column(
            "competency_id",
            sa.UUID(),
            nullable=False,
            comment="Desnormalizado desde el criterio. No es una fuente independiente de verdad: existe para que la FK compuesta (competency_id, capability_id) haga estructuralmente imposible vincular una capacidad de otra competencia.",
        ),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competency_id", "capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="evaluation_criterion_capabilities_capability_fk",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"],
            ["evaluation_criteria.id"],
            name="evaluation_criterion_capabilities_criterion_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="evaluation_criterion_capabilities_pkey"),
        sa.UniqueConstraint(
            "criterion_id", "id", name="evaluation_criterion_capabilities_criterion_key"
        ),
        comment="Qué capacidades mira un criterio de evaluación. Un criterio mira una o más capacidades de su competencia (N:M, decisión 2 del flujo): ser competente es usar las capacidades de forma combinada, así que un criterio puede mirar más de una. competency_id se desnormaliza del criterio para que la FK compuesta hacia capabilities pueda probar que la capacidad pertenece a la misma competencia.",
    )
    op.create_index(
        "evaluation_criterion_capabilities_capability_idx",
        "evaluation_criterion_capabilities",
        ["capability_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "evaluation_criterion_capabilities_pair_key",
        "evaluation_criterion_capabilities",
        ["criterion_id", "capability_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "planned_evidence_criteria",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("criterion_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["criterion_id"],
            ["evaluation_criteria.id"],
            name="planned_evidence_criteria_criterion_fk",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["planned_evidences.id"], name="planned_evidence_criteria_evidence_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="planned_evidence_criteria_pkey"),
        sa.UniqueConstraint("criterion_id", "id", name="planned_evidence_criteria_criterion_key"),
        sa.UniqueConstraint("evidence_id", "id", name="planned_evidence_criteria_evidence_key"),
        comment="Qué criterios observa una evidencia planificada. Los criterios pueden venir de competencias distintas de la misma experiencia: una misma evidencia puede observar varias competencias (decisión 11 del flujo). El requisito de que el criterio pertenezca a la misma experiencia se exige por trigger: la FK compuesta hacia evaluation_criteria no puede ver experience_id.",
    )
    op.create_index(
        "planned_evidence_criteria_criterion_idx",
        "planned_evidence_criteria",
        ["criterion_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "planned_evidence_criteria_pair_key",
        "planned_evidence_criteria",
        ["evidence_id", "criterion_id"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_table(
        "session_outline_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experience_id", sa.UUID(), nullable=False),
        sa.Column(
            "class_date",
            sa.Date(),
            nullable=False,
            comment="La fecha de clase. Debe caer dentro del rango de la experiencia (check_session_entry_date): una entrada fuera del rango es rechazada. La unicidad session_outline_entries_date_key es por fecha y no por franja horaria porque un bloque doble es una sola sesión (decisión 15 del flujo).",
        ),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            comment='Título de la sesión, ej. "Lanzamiento de la situación".',
        ),
        sa.Column(
            "topics",
            sa.Text(),
            nullable=True,
            comment="Línea de temas, texto libre. Null cuando aún no se ha redactado.",
        ),
        sa.Column(
            "planned_evidence_id",
            sa.UUID(),
            nullable=True,
            comment="La evidencia planificada que se recogerá en esta sesión, si ya se decidió. La FK es compuesta (experience_id, planned_evidence_id), así que no puede apuntar a una evidencia de otra experiencia.",
        ),
        sa.Column(
            "proposed_by",
            sa.Text(),
            server_default=sa.text("'teacher'::text"),
            nullable=False,
            comment="Quién propuso la entrada: 'mawta' (el asistente) o 'teacher' (el docente). El default es 'teacher'.",
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="session_outline_entries_proposed_by_check",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id", "planned_evidence_id"],
            ["planned_evidences.experience_id", "planned_evidences.id"],
            name="session_outline_entries_evidence_fk",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["learning_experiences.id"],
            name="session_outline_entries_experience_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="session_outline_entries_pkey"),
        sa.UniqueConstraint("experience_id", "id", name="session_outline_entries_experience_key"),
        comment="El esquema de sesiones de una experiencia: una entrada por fecha de clase, con un título y una línea de temas. Es deliberadamente ligero: no reemplaza a class_sessions (que son las sesiones reales con asistencia y audio) sino que planifica qué se hará en cada fecha. Las fechas sin entrada quedan permitidas: el esquema no tiene que cubrir todo.",
    )
    op.create_index(
        "session_outline_entries_date_key",
        "session_outline_entries",
        ["experience_id", "class_date"],
        unique=True,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "session_outline_entries_evidence_idx",
        "session_outline_entries",
        ["planned_evidence_id"],
        unique=False,
        postgresql_where=sa.text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "voice_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            comment='Duración en milisegundos. Se muestra como "0:04" junto al control de reproducción.',
        ),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=True,
            comment="Puntero heredado a disco, de antes de que el audio pasara a esta tabla. Se deja en su lugar para que las grabaciones previas a la migración en STORAGE_DIR sigan siendo reproducibles; las filas nuevas lo dejan null.",
        ),
        sa.Column(
            "audio",
            sa.LargeBinary(),
            nullable=True,
            comment="El audio grabado en sí. No es PII de un menor: es la voz del docente, grabada con su conocimiento mientras narra una observación — la parte sensible es el contenido hablado (ver la columna transcript), no la huella de voz. Sustituye a storage_key: se escribe aquí dentro de la misma transacción que la inserción de la fila, así que una nota y su audio nunca pueden desincronizarse como sí podría pasar entre una fila de BD y un archivo en disco.",
        ),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "transcription_status",
            sa.Text(),
            server_default=sa.text("'pending'::text"),
            nullable=False,
        ),
        sa.Column(
            "transcript",
            sa.Text(),
            nullable=True,
            comment="PII (menor): habla libre sobre un niño o niña. Nulable y purgable por separado del audio, para que un colegio pueda eliminar transcripciones y conservar las duraciones para analítica.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "transcript_redacted",
            sa.Text(),
            nullable=True,
            comment="PII (menor): la transcripción después del barrido de nombres: el estudiante asignado es [ESTUDIANTE], los compañeros de la sección [COMPAÑERO_n] y cualquier otra persona [PERSONA]. Es lo único que lee el agente de conclusiones. Sigue siendo habla libre sobre un menor.",
        ),
        sa.Column(
            "attribution_status",
            sa.Text(),
            server_default=sa.text("'pending'::text"),
            nullable=False,
            comment="Si la nota se puede usar como evidencia del estudiante asignado. pending: aún no se barre. ok: barrida y atribuida. discarded: el barrido indica que no es de este estudiante o no se entiende (ver discard_reason); queda fuera de las conclusiones sin preguntarle al docente. confirmed: el docente dijo que sí es de este estudiante. reassigned: el docente la movió a otro estudiante y se volvió a barrer.",
        ),
        sa.Column(
            "discard_reason",
            sa.Text(),
            nullable=True,
            comment="Por qué se descartó. mentions_other_student: nombra solo a compañeros de la sección y nunca al estudiante asignado. unreadable: la transcripción está vacía o no tiene sentido.",
        ),
        sa.Column(
            "attribution_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Cuándo se fijó attribution_status por última vez.",
        ),
        sa.CheckConstraint(
            "((attribution_status <> ALL (ARRAY['ok'::text, 'confirmed'::text, 'reassigned'::text])) OR (transcript_redacted IS NOT NULL))",
            name="voice_notes_redacted_consistent",
        ),
        sa.CheckConstraint(
            "((attribution_status = 'discarded'::text) = (discard_reason IS NOT NULL))",
            name="voice_notes_discard_consistent",
        ),
        sa.CheckConstraint(
            "((transcription_status = 'completed'::text) <= (transcript IS NOT NULL))",
            name="voice_notes_transcript_consistent",
        ),
        sa.CheckConstraint(
            "(attribution_status = ANY (ARRAY['pending'::text, 'ok'::text, 'discarded'::text, 'confirmed'::text, 'reassigned'::text]))",
            name="voice_notes_attribution_status_check",
        ),
        sa.CheckConstraint(
            "(discard_reason = ANY (ARRAY['mentions_other_student'::text, 'unreadable'::text]))",
            name="voice_notes_discard_reason_check",
        ),
        sa.CheckConstraint(
            "(transcription_status = ANY (ARRAY['pending'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text, 'skipped'::text]))",
            name="voice_notes_transcription_status_check",
        ),
        sa.CheckConstraint("(byte_size >= 0)", name="voice_notes_byte_size_check"),
        sa.CheckConstraint("(duration_ms >= 0)", name="voice_notes_duration_ms_check"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="voice_notes_class_fk"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="voice_notes_session_fk"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="voice_notes_student_fk"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name="voice_notes_teacher_fk"),
        sa.PrimaryKeyConstraint("id", name="voice_notes_pkey"),
        comment="DATOS PERSONALES DE MENORES (conductual, vía la transcripción). Una nota hablada del docente sobre un estudiante, grabada durante una sesión. El audio es la voz del docente; la transcripción es habla libre sobre un menor, la columna de mayor riesgo en el esquema después de los datos de identificación propios de los estudiantes.",
    )
    op.create_index(
        "voice_notes_attribution_idx",
        "voice_notes",
        ["student_id", "attribution_status"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "voice_notes_session_idx",
        "voice_notes",
        ["session_id"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "voice_notes_student_idx",
        "voice_notes",
        ["student_id", sa.literal_column("recorded_at DESC")],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "voice_notes_teacher_idx",
        "voice_notes",
        ["teacher_id", "recorded_at"],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "voice_notes_transcription_idx",
        "voice_notes",
        ["transcription_status"],
        unique=False,
        postgresql_where=sa.text(
            "((transcription_status = ANY (ARRAY['pending'::text, 'queued'::text, 'failed'::text])) AND (deleted_at IS NULL))"
        ),
    )
    op.create_table(
        "agent_generations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "agent",
            sa.Text(),
            nullable=False,
            comment="Qué agente atiende el pedido: planning, redaction (barrido de nombres de una nota de voz) o conclusions (propuesta de conclusión descriptiva).",
        ),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="Qué genera, según el agente. planning: experience, criteria, evidences o sessions. redaction: voice_note. conclusions: conclusion.",
        ),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column(
            "experience_id",
            sa.UUID(),
            nullable=True,
            comment="La experiencia sobre la que se genera. Null en kind = experience: la propuesta todavía no es una experiencia.",
        ),
        sa.Column(
            "requested_by",
            sa.UUID(),
            nullable=False,
            comment="El docente que pidió la generación. Solo para rastro: el acceso se decide por la clase, como en el resto de la planificación.",
        ),
        sa.Column(
            "target_key",
            sa.Text(),
            nullable=False,
            comment="Identifica el objetivo de la generación (ej. exp:<id>:criteria:<competencia>). Con agent_generations_target_key garantiza una sola generación en curso por objetivo.",
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'::text"), nullable=False),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Lo que pidió el docente. Solo ids y parámetros: nunca transcripciones ni nombres.",
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Lo que hizo una generación completada. planning: la propuesta o los ids insertados como pendientes. redaction: conteos y el estado de atribución resultante. conclusions: la propuesta (body, secciones con citas, avisos), que vive aquí hasta que el docente la guarda como conclusión.",
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
            comment="Mensaje para el docente, en español, cuando la generación falla. Se expone en la API.",
        ),
        sa.Column(
            "error_detail",
            sa.Text(),
            nullable=True,
            comment="Causa técnica del fallo, para soporte. Nunca se expone en la API.",
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "deadline_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() + '00:05:00'::interval)"),
            nullable=False,
            comment="Después de esta hora una generación sin terminar se da por fallida: el worker no la empieza y la API la muestra como failed. Cubre el caso de un worker que muere a mitad de camino.",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.UUID(),
            nullable=True,
            comment="El estudiante sobre el que trabaja una generación de redaction o conclusions. Null en planning.",
        ),
        sa.Column(
            "competency_id",
            sa.UUID(),
            nullable=True,
            comment="La competencia de una generación de conclusions.",
        ),
        sa.Column(
            "term_id",
            sa.UUID(),
            nullable=True,
            comment="El periodo de una generación de conclusions.",
        ),
        sa.Column(
            "voice_note_id",
            sa.UUID(),
            nullable=True,
            comment="La nota de voz que barre una generación de redaction.",
        ),
        sa.CheckConstraint(
            "((agent <> 'conclusions'::text) OR ((kind = 'conclusion'::text) AND (student_id IS NOT NULL) AND (competency_id IS NOT NULL) AND (term_id IS NOT NULL)))",
            name="agent_generations_conclusions_kind",
        ),
        sa.CheckConstraint(
            "((agent <> 'planning'::text) OR (kind = ANY (ARRAY['experience'::text, 'criteria'::text, 'evidences'::text, 'sessions'::text])))",
            name="agent_generations_planning_kind",
        ),
        sa.CheckConstraint(
            "((agent <> 'redaction'::text) OR ((kind = 'voice_note'::text) AND (voice_note_id IS NOT NULL) AND (student_id IS NOT NULL)))",
            name="agent_generations_redaction_kind",
        ),
        sa.CheckConstraint(
            "((status <> 'completed'::text) OR (result IS NOT NULL))",
            name="agent_generations_result_consistent",
        ),
        sa.CheckConstraint(
            "((status <> 'failed'::text) OR (error IS NOT NULL))",
            name="agent_generations_error_consistent",
        ),
        sa.CheckConstraint(
            "((status = ANY (ARRAY['completed'::text, 'failed'::text])) = (finished_at IS NOT NULL))",
            name="agent_generations_finished_consistent",
        ),
        sa.CheckConstraint(
            "(agent = ANY (ARRAY['planning'::text, 'redaction'::text, 'conclusions'::text]))",
            name="agent_generations_agent_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text]))",
            name="agent_generations_status_check",
        ),
        sa.CheckConstraint("(attempts >= 0)", name="agent_generations_attempts_check"),
        sa.CheckConstraint(
            "(cache_read_tokens >= 0)", name="agent_generations_cache_read_tokens_check"
        ),
        sa.CheckConstraint(
            "(cache_write_tokens >= 0)", name="agent_generations_cache_write_tokens_check"
        ),
        sa.CheckConstraint("(input_tokens >= 0)", name="agent_generations_input_tokens_check"),
        sa.CheckConstraint("(output_tokens >= 0)", name="agent_generations_output_tokens_check"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="agent_generations_class_fk"),
        sa.ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="agent_generations_competency_fk"
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="agent_generations_experience_fk"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["teachers.id"], name="agent_generations_requested_by_fk"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="agent_generations_student_fk"
        ),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], name="agent_generations_term_fk"),
        sa.ForeignKeyConstraint(
            ["voice_note_id"], ["voice_notes.id"], name="agent_generations_voice_note_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="agent_generations_pkey"),
        comment='DATOS PERSONALES DE MENORES (vía redaction y conclusions). Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen queda pendiente hasta que el docente lo acepta o lo edita. planning nunca recibe datos de estudiantes ni sugiere niveles de logro. redaction recibe la transcripción de una nota de voz con los nombres de la sección, porque reconocer un nombre mal transcrito o un apodo exige ese contexto; devuelve fragmentos, nunca texto reescrito. conclusions recibe evidencias, el nivel afirmado por el docente y transcripciones ya barridas, con el estudiante seudonimizado como [ESTUDIANTE]; nunca sugiere ni discute el nivel.',
    )
    op.create_index(
        "agent_generations_class_idx",
        "agent_generations",
        ["class_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "agent_generations_conclusion_scope_idx",
        "agent_generations",
        ["student_id", "competency_id", "term_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("(agent = 'conclusions'::text)"),
    )
    op.create_index(
        "agent_generations_target_key",
        "agent_generations",
        ["target_key"],
        unique=True,
        postgresql_where=sa.text("(status = ANY (ARRAY['pending'::text, 'running'::text]))"),
    )
    op.create_index(
        "agent_generations_voice_note_idx",
        "agent_generations",
        ["voice_note_id"],
        unique=False,
        postgresql_where=sa.text("(voice_note_id IS NOT NULL)"),
    )
    op.create_table(
        "assessment_criteria",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("criterion_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], name="assessment_criteria_assessment_fk"
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"], ["evaluation_criteria.id"], name="assessment_criteria_criterion_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="assessment_criteria_pkey"),
        sa.UniqueConstraint("assessment_id", "criterion_id", name="assessment_criteria_key"),
        comment='A qué criterios de evaluación habla una evidencia, ej. una "Tarea 1" etiquetada contra dos criterios de "Resuelve problemas de cantidad". Toda evidencia tiene al menos un criterio: es lo que la hace llegar a una competencia (el servidor lo exige al crearla).',
    )
    op.create_index(
        "assessment_criteria_criterion_idx", "assessment_criteria", ["criterion_id"], unique=False
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recipient_teacher_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Text(),
            nullable=False,
            comment="Subtipo legible por máquina dentro de kind. Sobre esto agrupa y filtra el cliente; title y body son para humanos.",
        ),
        sa.Column("severity", sa.Text(), server_default=sa.text("'info'::text"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("class_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("assessment_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("'system'::text"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = ANY (ARRAY['alert'::text, 'reminder'::text]))", name="notifications_kind_check"
        ),
        sa.CheckConstraint(
            "(severity = ANY (ARRAY['info'::text, 'low'::text, 'medium'::text, 'high'::text]))",
            name="notifications_severity_check",
        ),
        sa.CheckConstraint(
            "(source = ANY (ARRAY['system'::text, 'rule'::text, 'model'::text, 'teacher'::text]))",
            name="notifications_source_check",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], name="notifications_assessment_fk"
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="notifications_class_fk"),
        sa.ForeignKeyConstraint(
            ["recipient_teacher_id"], ["teachers.id"], name="notifications_recipient_fk"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="notifications_session_fk"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="notifications_student_fk"),
        sa.PrimaryKeyConstraint("id", name="notifications_pkey"),
        comment='DATOS PERSONALES DE MENORES (derivado). El feed de notificaciones. Los títulos y cuerpos de las alertas nombran estudiantes individuales y declaran inferencias sobre ellos, así que una fila de notification es dato de estudiante aunque esté dirigida a un docente. kind determina los filtros de Alertas/Recordatorios; read_at determina el punto de no leído y el estado atenuado "Leído". Cada fila lleva la entidad que la disparó, para que al tocarla se llegue al estudiante o la class en vez de a un callejón sin salida.',
    )
    op.create_index(
        "notifications_feed_idx",
        "notifications",
        ["recipient_teacher_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.create_index(
        "notifications_student_idx",
        "notifications",
        ["student_id"],
        unique=False,
        postgresql_where=sa.text("(student_id IS NOT NULL)"),
    )
    op.create_index(
        "notifications_unread_idx",
        "notifications",
        ["recipient_teacher_id", "kind"],
        unique=False,
        postgresql_where=sa.text(
            "((read_at IS NULL) AND (dismissed_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.create_table(
        "scores",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "class_id",
            sa.UUID(),
            nullable=False,
            comment="Desnormalizado desde la evidencia. Se mantiene por trigger; permite que los agregados por class se salten un join.",
        ),
        sa.Column(
            "term_id",
            sa.UUID(),
            nullable=True,
            comment="Desnormalizado desde la evidencia. Nulable: una score de recuperación o subsanación puede registrarse contra una evidencia sin term (ver assessments.term_id).",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'graded'::text"),
            nullable=False,
            comment="graded lleva un valor. not_submitted, absent y excused no llevan ninguno: son información para el docente sobre por qué falta la valoración.",
        ),
        sa.Column(
            "raw_value",
            sa.Numeric(precision=8, scale=4),
            nullable=True,
            comment="El número que escribió el docente, sobre max_value, ej. 14 sobre 18. Solo cuando la evidencia es numeric y status = graded.",
        ),
        sa.Column(
            "max_value",
            sa.Numeric(precision=8, scale=4),
            nullable=True,
            comment="Copiado de la evidencia al momento de escribir y congelado, así que cambiar después el máximo de una evidencia no puede reinterpretar notas ya ingresadas.",
        ),
        sa.Column(
            "scale_level_id",
            sa.UUID(),
            nullable=True,
            comment="El nivel AD/A/B/C que el docente dio a esta evidencia, como fila de grade_scale_levels. Solo cuando la evidencia es ordinal y status = graded. No es el nivel de logro de la competencia.",
        ),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'::text"), nullable=False),
        sa.Column("recorded_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "supersedes_id",
            sa.UUID(),
            nullable=True,
            comment="La fila que esta reemplaza tras una corrección. El enlace apunta solo hacia atrás: un superseded_by_id hacia adelante tendría que escribirse en el mismo momento que superseded_at.",
        ),
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Se establece cuando una fila más nueva reemplaza a esta. Una fila con superseded_at null y deleted_at null es el valor vigente. Se escribe antes de insertar el reemplazo — ver scores_live_key.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((status = 'graded'::text) = ((raw_value IS NOT NULL) OR (scale_level_id IS NOT NULL)))",
            name="scores_value_matches_status",
        ),
        sa.CheckConstraint(
            "(source = ANY (ARRAY['manual'::text, 'bulk'::text, 'import'::text, 'voice'::text, 'auto'::text]))",
            name="scores_source_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['graded'::text, 'excused'::text, 'absent'::text, 'not_submitted'::text]))",
            name="scores_status_check",
        ),
        sa.CheckConstraint(
            "((max_value IS NULL) OR (max_value > (0)::numeric))", name="scores_max_value_positive"
        ),
        sa.CheckConstraint(
            "((raw_value IS NULL) OR ((max_value IS NOT NULL) AND (raw_value >= (0)::numeric) AND (raw_value <= max_value)))",
            name="scores_value_in_range",
        ),
        sa.CheckConstraint(
            "((raw_value IS NULL) OR (scale_level_id IS NULL))", name="scores_single_value"
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], name="scores_assessment_fk"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="scores_class_fk"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["teachers.id"], name="scores_recorded_by_fk"),
        sa.ForeignKeyConstraint(
            ["scale_level_id"], ["grade_scale_levels.id"], name="scores_scale_level_fk"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="scores_student_fk"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["scores.id"], name="scores_supersedes_fk"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], name="scores_term_fk"),
        sa.PrimaryKeyConstraint("id", name="scores_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico). De solo inserción. La valoración de un estudiante en una evidencia: una nota cruda sobre el máximo (raw_value, max_value) o un nivel AD/A/B/C (scale_level_id), según value_scale de la evidencia, y nada derivado — sin porcentaje, sin peso. Corregir una score inserta una fila nueva que reemplaza a la anterior.",
    )
    op.create_index(
        "scores_assessment_idx",
        "scores",
        ["assessment_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "scores_class_term_idx",
        "scores",
        ["class_id", "term_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "scores_live_key",
        "scores",
        ["assessment_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "scores_student_term_idx",
        "scores",
        ["student_id", "term_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_index(
        "scores_supersedes_idx",
        "scores",
        ["supersedes_id"],
        unique=False,
        postgresql_where=sa.text("(supersedes_id IS NOT NULL)"),
    )
    op.create_table(
        "descriptive_conclusions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=False),
        sa.Column(
            "academic_year_id",
            sa.UUID(),
            nullable=False,
            comment="Copiado del academic_year_id de la class desde la que se escribió la conclusión. Existe por la misma razón que en competency_term_levels: dc_recuperacion_key acota la unicidad de las filas sin term (recuperación) a un año, y dc_year_fk/dc_term_fk componen sobre esta columna para que una fila del año 2026 no apunte a un term de otro año.",
        ),
        sa.Column(
            "term_id",
            sa.UUID(),
            nullable=True,
            comment="El periodo regular de esta conclusión. Nulable por la misma razón que competency_term_levels.term_id: una conclusión escrita a partir de recuperación pedagógica o evaluación de subsanación puede no tener un term regular detrás — el caso que hace obligatoria una conclusión de un estudiante que sigue en C tras la recuperación, o de inclusion_support en todo periodo, incluido uno de recuperación.",
        ),
        sa.Column("class_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "requirement",
            sa.Text(),
            server_default=sa.text("'optional'::text"),
            nullable=False,
            comment="Por qué existe esta conclusión, y su obligatoriedad varía por nivel educativo. 'level_c': la competencia está en C — obligatoria en Secundaria, Primaria e Inicial Ciclo II. 'level_b': obligatoria en Primaria e Inicial Ciclo II. 'level_a': obligatoria en Inicial Ciclo II. 'cycle_i_mandatory': toda competencia en Inicial Ciclo I lleva una, sin importar el nivel. 'consecutive_c': C en dos o más periodos consecutivos — obligatoria *y* el texto debe justificar por qué no hay progreso (5.1.1.3 p.3). 'inclusion_support': el estudiante enfrenta barreras educativas, así que es obligatoria en todo periodo y debe indicar los apoyos y ajustes razonables brindados (5.1.1.3 p.7). 'optional': el nivel supera el mínimo obligatorio para el nivel educativo del estudiante, escrita porque el docente lo consideró conveniente. La establece el servidor a partir del nivel vigente, el grado del estudiante, y el estudiante, nunca se confía en el cliente.",
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'::text"), nullable=False),
        sa.Column("authored_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "authored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "generation_id",
            sa.UUID(),
            nullable=True,
            comment="La generación de conclusions de la que el docente partió al escribir este body, si partió de una. El texto sigue siendo del docente (authored_by_id); esto deja trazable qué leyó el agente para proponerlo.",
        ),
        sa.Column(
            "generated_from_voice_notes",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Verdadero cuando la conclusión partió de una propuesta de Mawta (conclusions) que usó al menos una nota de voz. Lo fija el servidor al guardar, a partir de agent_generations.result.used_voice_note_ids; el cliente no lo envía. Es un registro interno, no se muestra al docente.",
        ),
        sa.CheckConstraint(
            "((deleted_at IS NOT NULL) OR (((char_length(body) >= 10) AND (char_length(body) <= 350)) AND (body !~ '[\\r\\n]'::text)))",
            name="dc_body_siagie",
        ),
        sa.CheckConstraint("(btrim(body) <> ''::text)", name="dc_body_not_blank"),
        sa.CheckConstraint(
            "(requirement = ANY (ARRAY['level_c'::text, 'level_b'::text, 'level_a'::text, 'cycle_i_mandatory'::text, 'consecutive_c'::text, 'inclusion_support'::text, 'optional'::text]))",
            name="descriptive_conclusions_requirement_check",
        ),
        sa.CheckConstraint(
            "(status = ANY (ARRAY['draft'::text, 'final'::text]))",
            name="descriptive_conclusions_status_check",
        ),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="dc_year_fk"),
        sa.ForeignKeyConstraint(["authored_by_id"], ["teachers.id"], name="dc_authored_by_fk"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name="dc_class_fk"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="dc_competency_fk"),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["agent_generations.id"], name="dc_generation_fk"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name="dc_student_fk"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["descriptive_conclusions.id"], name="dc_supersedes_fk"
        ),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], name="dc_term_fk"),
        sa.PrimaryKeyConstraint("id", name="descriptive_conclusions_pkey"),
        comment="DATOS PERSONALES DE MENORES (académico, oficial). La conclusión descriptiva de una competencia en un periodo: \"juicio docente basado en evidencias […] Señala avances, dificultades y recomendaciones\" (094-2020, glosario). Toda conclusión debe llevar recomendaciones personalizadas dentro del propio body (\"En todos los casos, las conclusiones descriptivas deben incluir recomendaciones personalizadas orientadas al desarrollo de cada competencia\", 5.1.1.3 p.7) — no hay una columna aparte que lo afirme, porque nada puede verificar que un texto libre realmente contenga una recomendación; es responsabilidad del docente al redactar body, igual que siempre. Va a SIAGIE junto al nivel. Solo una fila 'final' satisface un requisito obligatorio; un 'draft' no desbloquea el cierre del periodo.",
    )
    op.create_index(
        "dc_recuperacion_key",
        "descriptive_conclusions",
        ["student_id", "competency_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text(
            "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.create_index(
        "dc_regular_key",
        "descriptive_conclusions",
        ["student_id", "competency_id", "term_id"],
        unique=True,
        postgresql_where=sa.text(
            "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.create_index(
        "dc_term_idx",
        "descriptive_conclusions",
        ["term_id", "class_id"],
        unique=False,
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.create_table(
        "voice_note_redactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("voice_note_id", sa.UUID(), nullable=False),
        sa.Column(
            "generation_id",
            sa.UUID(),
            nullable=False,
            comment="La generación de redaction que produjo la fila; de ahí salen el modelo y la versión del prompt.",
        ),
        sa.Column(
            "student_id",
            sa.UUID(),
            nullable=False,
            comment="El estudiante al que estaba asignada la nota cuando se barrió. Si la nota se reasigna, se vuelve a barrer y estas filas quedan superseded.",
        ),
        sa.Column(
            "original_text",
            sa.Text(),
            nullable=False,
            comment="PII (menor): el fragmento tal como aparece en la transcripción, ej. un nombre mal escrito por la transcripción o un apodo.",
        ),
        sa.Column(
            "start_offset",
            sa.Integer(),
            nullable=False,
            comment="Posición del fragmento en voice_notes.transcript, en caracteres (runas), desde 0.",
        ),
        sa.Column("end_offset", sa.Integer(), nullable=False, comment="Posición final, exclusiva."),
        sa.Column(
            "replacement",
            sa.Text(),
            nullable=False,
            comment="La marca que quedó en transcript_redacted: [ESTUDIANTE], [COMPAÑERO_n] o [PERSONA].",
        ),
        sa.Column(
            "refers_to",
            sa.Text(),
            nullable=False,
            comment="A quién se refiere el fragmento según el barrido: el estudiante asignado, un compañero de la sección, u otra persona (apodo no reconocible, familiar, otro docente).",
        ),
        sa.Column(
            "matched_student_id",
            sa.UUID(),
            nullable=True,
            comment="El compañero de la sección al que el barrido asoció el fragmento. Obligatorio cuando refers_to = classmate.",
        ),
        sa.Column(
            "method",
            sa.Text(),
            server_default=sa.text("'model'::text"),
            nullable=False,
            comment="Cómo se detectó el fragmento. Por ahora solo model: el barrido lo hace un modelo con el contexto de la sección.",
        ),
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Se fija cuando la nota se vuelve a barrer (ej. tras reasignarla). Null significa vigente.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "((refers_to = 'classmate'::text) <= (matched_student_id IS NOT NULL))",
            name="voice_note_redactions_classmate_matched",
        ),
        sa.CheckConstraint("(method = 'model'::text)", name="voice_note_redactions_method_check"),
        sa.CheckConstraint(
            "(refers_to = ANY (ARRAY['assigned_student'::text, 'classmate'::text, 'other_person'::text]))",
            name="voice_note_redactions_refers_to_check",
        ),
        sa.CheckConstraint("(end_offset > start_offset)", name="voice_note_redactions_offsets"),
        sa.CheckConstraint("(start_offset >= 0)", name="voice_note_redactions_start_offset_check"),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["agent_generations.id"], name="voice_note_redactions_generation_fk"
        ),
        sa.ForeignKeyConstraint(
            ["matched_student_id"], ["students.id"], name="voice_note_redactions_matched_student_fk"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="voice_note_redactions_student_fk"
        ),
        sa.ForeignKeyConstraint(
            ["voice_note_id"], ["voice_notes.id"], name="voice_note_redactions_voice_note_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="voice_note_redactions_pkey"),
        comment="DATOS PERSONALES DE MENORES (nombres dentro de notas de voz). Una fila por cada reemplazo que hizo el barrido en una transcripción: qué texto original, en qué posición, por qué marca se cambió y a quién se asoció. Existe para que una persona pueda revisar, con una consulta, cada decisión del barrido comparando transcript con transcript_redacted. El modelo solo señala fragmentos; el servidor calcula las posiciones y hace el reemplazo.",
    )
    op.create_index(
        "voice_note_redactions_note_idx",
        "voice_note_redactions",
        ["voice_note_id"],
        unique=False,
        postgresql_where=sa.text("(superseded_at IS NULL)"),
    )
    # ### end Alembic commands ###
    # The planned_evidences <-> session_outline_entries cycle: this FK goes in once both exist.
    op.create_foreign_key(
        "planned_evidences_session_entry_fk",
        "planned_evidences",
        "session_outline_entries",
        ["experience_id", "session_entry_id"],
        ["experience_id", "id"],
    )
    op.create_entity(public_academic_years_set_updated_at)
    op.create_entity(public_agent_generations_set_updated_at)
    op.create_entity(public_assessment_criteria_set_updated_at)
    op.create_entity(public_assessments_set_updated_at)
    op.create_entity(public_attendance_records_set_updated_at)
    op.create_entity(public_attendance_records_sync_denormalised)
    op.create_entity(public_capabilities_set_updated_at)
    op.create_entity(public_class_schedules_set_updated_at)
    op.create_entity(public_class_sessions_set_updated_at)
    op.create_entity(public_class_teachers_set_updated_at)
    op.create_entity(public_classes_set_updated_at)
    op.create_entity(public_competencies_set_updated_at)
    op.create_entity(public_competency_exemptions_set_updated_at)
    op.create_entity(public_competency_term_levels_set_updated_at)
    op.create_entity(public_competency_year_snapshots_forbid_mutation)
    op.create_entity(public_competency_year_snapshots_set_updated_at)
    op.create_entity(public_courses_set_updated_at)
    op.create_entity(public_descriptive_conclusions_set_updated_at)
    op.create_entity(public_evaluation_criteria_check_criterion_experience)
    op.create_entity(public_evaluation_criteria_check_criterion_on_write)
    op.create_entity(public_evaluation_criteria_set_updated_at)
    op.create_entity(public_evaluation_criterion_capabilities_check_criterion_capabilities)
    op.create_entity(public_evaluation_criterion_capabilities_check_criterion_capability_competency)
    op.create_entity(public_evaluation_criterion_capabilities_set_updated_at)
    op.create_entity(public_events_forbid_mutation)
    op.create_entity(public_experience_competencies_check_competency_subject)
    op.create_entity(public_experience_competencies_set_updated_at)
    op.create_entity(public_grade_level_performances_set_updated_at)
    op.create_entity(public_grade_levels_set_updated_at)
    op.create_entity(public_grade_scale_levels_set_updated_at)
    op.create_entity(public_grade_scales_set_updated_at)
    op.create_entity(public_jobs_set_updated_at)
    op.create_entity(public_learning_experiences_check_inside_term)
    op.create_entity(public_learning_experiences_set_updated_at)
    op.create_entity(public_learning_standards_set_updated_at)
    op.create_entity(public_memberships_set_updated_at)
    op.create_entity(public_non_teaching_days_set_updated_at)
    op.create_entity(public_notifications_set_updated_at)
    op.create_entity(public_planned_evidence_criteria_check_evidence_criterion_experience)
    op.create_entity(public_planned_evidence_criteria_set_updated_at)
    op.create_entity(public_planned_evidences_set_updated_at)
    op.create_entity(public_school_set_updated_at)
    op.create_entity(public_school_validate_timezone)
    op.create_entity(public_scores_forbid_mutation)
    op.create_entity(public_scores_set_updated_at)
    op.create_entity(public_scores_sync_denormalised)
    op.create_entity(public_section_memberships_set_updated_at)
    op.create_entity(public_sections_set_updated_at)
    op.create_entity(public_session_outline_entries_check_session_entry_date)
    op.create_entity(public_session_outline_entries_set_updated_at)
    op.create_entity(public_standard_level_mappings_set_updated_at)
    op.create_entity(public_students_set_updated_at)
    op.create_entity(public_subjects_set_updated_at)
    op.create_entity(public_teachers_set_updated_at)
    op.create_entity(public_terms_set_updated_at)
    op.create_entity(chat_threads_set_updated_at)
    op.create_entity(public_users_set_updated_at)
    op.create_entity(public_voice_note_redactions_set_updated_at)
    op.create_entity(public_voice_notes_set_updated_at)
    op.create_entity(public_year_final_situations_forbid_mutation)
    op.create_entity(public_year_final_situations_set_updated_at)
    op.create_entity(chat_api_school)
    op.create_entity(chat_api_sections)
    op.create_entity(chat_api_terms)
    op.create_entity(chat_api_classes)
    op.create_entity(chat_api_students)
    op.create_entity(chat_api_competencies)
    op.create_entity(chat_api_levels)
    op.create_entity(privacy_pii_columns)
    op.create_entity(privacy_minor_data_tables)
    op.create_entity(privacy_undeclared_student_references)
    op.create_entity(chat_messages_owner_only)
    op.create_entity(chat_threads_owner_only)

    # Partitions, RLS switches, grants, view owners and comments.
    op.execute(
        """do $$
declare
  m date := date '2026-01-01';
begin
  while m < date '2028-01-01' loop
    execute format(
      'create table events_%s partition of events for values from (%L) to (%L)',
      to_char(m, 'YYYY_MM'), m, (m + interval '1 month')::date);
    m := (m + interval '1 month')::date;
  end loop;
end
$$"""
    )
    op.execute("create table events_default partition of events default")
    op.execute("alter table chat.threads enable row level security")
    op.execute("alter table chat.threads force row level security")
    op.execute("alter table chat.messages enable row level security")
    op.execute("alter table chat.messages force row level security")
    op.execute("grant select, insert, update, delete on all tables in schema chat to mawta_chat")
    op.execute(
        "grant select on school, academic_years, grade_levels, sections, terms, classes, courses, subjects, class_teachers, teachers, students, section_memberships, competencies, competency_term_levels, grade_scale_levels to mawta_chat_api"
    )
    op.execute(
        "comment on schema app is 'Funciones auxiliares de contexto de sesión y funciones de trigger compartidas. No contiene datos de negocio.'"
    )
    op.execute(
        "comment on schema chat is 'Datos propios del servicio del chat de dirección: hilos, mensajes, banco de preguntas y seudónimos. Solo mawta_chat los lee y escribe; mawta_app (Go) no tiene acceso.'"
    )
    op.execute(
        "comment on schema chat_api is 'Contrato de lectura del servicio del chat de dirección: vistas de solo lectura sobre las tablas de Mawta, propiedad de mawta_chat_api. mawta_chat solo puede leer estas vistas, nunca las tablas de public.'"
    )
    op.execute(
        "comment on schema privacy is 'Vistas y utilidades para descubrir y auditar columnas de datos personales (herramientas para la Ley 29733).'"
    )
    op.execute(
        "comment on type public.timerange is 'Intervalo de hora local dentro de un día de la semana. Usado por las restricciones de exclusión de class_schedules.'"
    )
    op.execute(
        "comment on function app.check_criterion_capability_competency() is 'La competency_id desnormalizada debe ser exactamente la del criterio. Sin esto, una fila podría pasar la FK compuesta hacia capabilities apuntando a una capacidad de la competencia correcta mientras el criterio habla de otra.'"
    )
    op.execute(
        "comment on function app.check_criterion_experience() is 'Un criterio anclado a una experiencia solo puede hablar de una competencia que esa experiencia trabaja. Ninguna FK compuesta puede expresar esto (la fila de experience_competencies no existe todavía cuando se crea el criterio), así que es un trigger BEFORE.'"
    )
    op.execute(
        "comment on function app.check_criterion_has_capability() is 'Un criterio no eliminado mira al menos una capacidad (decisión 2 del flujo), sea a través de evaluation_criterion_capabilities (camino nuevo, N:M) o de la columna vieja capability_id (camino legacy que esta migración no rompe). Diferido al COMMIT: crear un criterio y sus capacidades en una misma transacción es el caso normal, y sin la deferral ese insert sería imposible.'"
    )
    op.execute(
        "comment on function app.check_evidence_criterion_experience() is 'Una evidencia planificada observa criterios de su propia experiencia. Un criterio global (experience_id null) nunca es observable por una evidencia planificada: la evidencia observa criterios que el docente precisó para esta experiencia.'"
    )
    op.execute(
        "comment on function app.check_experience_competency_subject() is 'Cada competencia vinculada a una experiencia debe pertenecer al área de la course de la class. La pertenencia no es una columna de la fila (es un camino a través de classes → courses → subjects), así que no puede ser una FK compuesta ni un CHECK: es un trigger BEFORE que rechaza la fila.'"
    )
    op.execute(
        "comment on function app.check_experience_inside_term() is 'Un CHECK de fila no puede leer terms, así que el \"dentro del term\" es un trigger de restricción diferido: se dispara al COMMIT, lo que permite crear la experiencia y ajustar sus fechas en una misma transacción.'"
    )
    op.execute(
        "comment on function app.check_session_entry_date() is 'La fecha de una entrada del esquema debe caer dentro del rango de su experiencia. Ninguna FK compuesta puede expresar \"entre starts_on y ends_on\" (el rango son dos columnas de una sola fila), así que es un trigger BEFORE.'"
    )
    op.execute(
        "comment on function app.current_actor_id() is 'Usuario autenticado de la sesión actual, de SET LOCAL app.actor_id. Se usa como valor por defecto en columnas de actor en filas de auditoría y eventos.'"
    )
    op.execute(
        "comment on function app.ensure_events_partition(date) is 'Creación idempotente de particiones, llamada por un job programado con varios meses de anticipación.'"
    )
    op.execute(
        "comment on function app.log_event(text,text,uuid,jsonb,uuid,uuid,uuid) is 'Función de escritura de conveniencia que completa actor y request a partir de la sesión. Las lecturas de registros de estudiante se registran a través de esta desde la capa de acceso a datos — Postgres no puede disparar triggers sobre SELECT.'"
    )
    op.execute(
        "comment on index terms_one_active_key is 'A lo sumo un periodo activo por año y nivel (stage), la misma clave que terms_no_overlap. Es por nivel porque un colegio puede llevar calendarios distintos por nivel. No exige que haya uno: entre dos periodos puede no haber ninguno activo.'"
    )
    op.execute(
        "comment on table events_default is 'Partición comodín. Debe permanecer vacía: si caen filas aquí significa que el job de creación de particiones se ha atrasado.'"
    )
    op.execute(
        "comment on view chat_api.classes is 'Clases del colegio de la sesión: el área que se dicta en cada sección, su docente titular vigente hoy y el tutor de la sección.'"
    )
    op.execute(
        "comment on view chat_api.competencies is 'Competencias de área del colegio de la sesión. Las transversales (sin área) y las de tutoría quedan fuera: no cuentan para la promoción ni para los resúmenes por área.'"
    )
    op.execute(
        "comment on view chat_api.levels is 'DATOS PERSONALES DE MENORES (académico, oficial). Los niveles de logro vigentes (la afirmación del docente que no fue corregida) de cada alumno por competencia de área y periodo, con la sección de la clase donde se afirmó. Sin fila = sin nivel, nunca C. Las competencias transversales, las de tutoría y las corregidas no aparecen.'"
    )
    op.execute(
        "comment on view chat_api.school is 'El colegio de esta base de datos (school tiene una sola fila).'"
    )
    op.execute(
        "comment on view chat_api.sections is 'Secciones del colegio de la sesión, con su grado y año académico.'"
    )
    op.execute(
        "comment on view chat_api.students is 'DATOS PERSONALES DE MENORES (identificación). Una fila por matrícula de un alumno en una sección: nombre, sección, grado y fechas (left_on exclusiva, nula mientras sigue).'"
    )
    op.execute(
        "comment on view chat_api.terms is 'Periodos (bimestres, trimestres o semestres) del colegio de la sesión. is_current: contiene la fecha de hoy en la zona del colegio. has_levels: algún nivel de logro vigente se afirmó en el periodo; los niveles se afirman al cierre, así que el periodo en curso suele no tenerlos.'"
    )
    op.execute(
        "comment on view privacy.minor_data_tables is 'Tablas cuyo comentario declara que contienen datos sobre menores. La unidad sobre la que opera un procedimiento de retención o de borrado.'"
    )
    op.execute(
        "comment on view privacy.pii_columns is 'Cada columna documentada como portadora de datos personales, derivada del texto de COMMENT ON. Responde \"dónde guarda esta base de datos información sobre menores\" con un solo SELECT, y no puede desactualizarse respecto a los comentarios que lee.'"
    )
    op.execute(
        "comment on view privacy.undeclared_student_references is 'Debe devolver cero filas. Cualquier tabla que lleve un student_id sin declararse a sí misma en el registro es un hueco de documentación; se verifica que esto esté vacío en CI para que las tablas nuevas no puedan saltarse la declaración. Las particiones se omiten porque heredan la declaración de su tabla padre en vez de llevar su propio comentario, y events se omite por nombre: referencia a todo tipo de entidad y vive bajo sus propias reglas de retención.'"
    )
    op.execute(
        "comment on constraint assessment_criteria_key on assessment_criteria is 'A diferencia del resto de esta migración, esta es una unique constraint completa, no parcial por deleted_at is null: Postgres solo permite que una FK apunte a una unique/primary key completa, nunca a un índice parcial, y una FK compuesta hacia esta tabla la necesitaría completa. Sin consecuencia práctica hoy — nada en Go borra una fila de assessment_criteria (linkAssessmentCriteria solo inserta) — pero si algún día se agrega un \"destag\", debe reactivar la fila existente en vez de insertar una nueva para el mismo par.'"
    )
    op.execute(
        "comment on constraint class_schedules_no_overlap on class_schedules is 'Una class no puede ocupar dos franjas superpuestas el mismo día de la semana mientras ambas estén vigentes. No intenta detectar a un docente con doble reserva entre dos clases distintas — ver las notas sobre conflictos de horario entre clases.'"
    )
    op.execute(
        "comment on constraint class_sessions_started_consistent on class_sessions is 'Implicación booleana: in_progress o completed requiere actual_start_at. Una sesión no puede estar en curso sin haber iniciado.'"
    )
    op.execute(
        "comment on constraint class_teachers_one_titular on class_teachers is 'Dos titulares en la misma fecha harían que \"mis clases\" se contaran dos veces.'"
    )
    op.execute(
        "comment on constraint dc_body_siagie on descriptive_conclusions is 'SIAGIE acepta de 10 a 350 caracteres en una sola línea. Aplica a borradores y finales; las filas retiradas (deleted_at) quedan fuera.'"
    )
    op.execute(
        "comment on constraint grade_scale_levels_no_gap_overlap on grade_scale_levels is 'Dos bandas de una misma escala no pueden solaparse. No se impiden los huecos aquí — un hueco es detectable pero no siempre es un error durante la autoría, así que se verifica cuando la escala se usa por primera vez.'"
    )
    op.execute(
        "comment on constraint learning_experiences_no_overlap on learning_experiences is 'Dos experiencias no eliminadas de la misma class no pueden cubrir la misma fecha. El rango es inclusivo ''[]'': una experiencia que termina el lunes y otra que empieza ese mismo lunes se solapan — el docente no puede estar en dos experiencias a la vez.'"
    )
    op.execute(
        "comment on constraint section_memberships_one_at_a_time on section_memberships is 'Un estudiante no puede estar en dos sections en la misma fecha dentro de un año escolar. Este es el invariante que hace que \"el roster de la clase X en la fecha D\" sea siempre un conjunto único e inequívoco.'"
    )
    op.execute(
        "comment on constraint terms_no_overlap on terms is 'Dos terms del mismo año y stage no pueden cubrir la misma fecha, así que \"el term que contiene esta sesión de clase\" es siempre una sola fila. coalesce(stage, '''') en vez de comparar stage directamente: una restricción de exclusión (como un índice único) nunca trata dos NULL como iguales, así que sin esto dos terms sin stage del mismo año podrían solaparse silenciosamente.'"
    )
    op.execute(
        "comment on policy owner_only on chat.messages is 'Cada directivo ve, cambia y borra solo sus propias conversaciones (app.actor_id de la transacción).'"
    )
    op.execute(
        "comment on policy owner_only on chat.threads is 'Cada directivo ve, cambia y borra solo sus propias conversaciones (app.actor_id de la transacción).'"
    )
    op.execute("alter view chat_api.classes owner to mawta_chat_api")
    op.execute("grant select on chat_api.classes to mawta_chat")
    op.execute("alter view chat_api.competencies owner to mawta_chat_api")
    op.execute("grant select on chat_api.competencies to mawta_chat")
    op.execute("alter view chat_api.levels owner to mawta_chat_api")
    op.execute("grant select on chat_api.levels to mawta_chat")
    op.execute("alter view chat_api.school owner to mawta_chat_api")
    op.execute("grant select on chat_api.school to mawta_chat")
    op.execute("alter view chat_api.sections owner to mawta_chat_api")
    op.execute("grant select on chat_api.sections to mawta_chat")
    op.execute("alter view chat_api.students owner to mawta_chat_api")
    op.execute("grant select on chat_api.students to mawta_chat")
    op.execute("alter view chat_api.terms owner to mawta_chat_api")
    op.execute("grant select on chat_api.terms to mawta_chat")


def downgrade() -> None:
    op.drop_entity(chat_threads_owner_only)
    op.drop_entity(chat_messages_owner_only)
    op.drop_entity(privacy_undeclared_student_references)
    op.drop_entity(privacy_minor_data_tables)
    op.drop_entity(privacy_pii_columns)
    op.drop_entity(chat_api_levels)
    op.drop_entity(chat_api_competencies)
    op.drop_entity(chat_api_students)
    op.drop_entity(chat_api_classes)
    op.drop_entity(chat_api_terms)
    op.drop_entity(chat_api_sections)
    op.drop_entity(chat_api_school)
    op.drop_entity(public_year_final_situations_set_updated_at)
    op.drop_entity(public_year_final_situations_forbid_mutation)
    op.drop_entity(public_voice_notes_set_updated_at)
    op.drop_entity(public_voice_note_redactions_set_updated_at)
    op.drop_entity(public_users_set_updated_at)
    op.drop_entity(chat_threads_set_updated_at)
    op.drop_entity(public_terms_set_updated_at)
    op.drop_entity(public_teachers_set_updated_at)
    op.drop_entity(public_subjects_set_updated_at)
    op.drop_entity(public_students_set_updated_at)
    op.drop_entity(public_standard_level_mappings_set_updated_at)
    op.drop_entity(public_session_outline_entries_set_updated_at)
    op.drop_entity(public_session_outline_entries_check_session_entry_date)
    op.drop_entity(public_sections_set_updated_at)
    op.drop_entity(public_section_memberships_set_updated_at)
    op.drop_entity(public_scores_sync_denormalised)
    op.drop_entity(public_scores_set_updated_at)
    op.drop_entity(public_scores_forbid_mutation)
    op.drop_entity(public_school_validate_timezone)
    op.drop_entity(public_school_set_updated_at)
    op.drop_entity(public_planned_evidences_set_updated_at)
    op.drop_entity(public_planned_evidence_criteria_set_updated_at)
    op.drop_entity(public_planned_evidence_criteria_check_evidence_criterion_experience)
    op.drop_entity(public_notifications_set_updated_at)
    op.drop_entity(public_non_teaching_days_set_updated_at)
    op.drop_entity(public_memberships_set_updated_at)
    op.drop_entity(public_learning_standards_set_updated_at)
    op.drop_entity(public_learning_experiences_set_updated_at)
    op.drop_entity(public_learning_experiences_check_inside_term)
    op.drop_entity(public_jobs_set_updated_at)
    op.drop_entity(public_grade_scales_set_updated_at)
    op.drop_entity(public_grade_scale_levels_set_updated_at)
    op.drop_entity(public_grade_levels_set_updated_at)
    op.drop_entity(public_grade_level_performances_set_updated_at)
    op.drop_entity(public_experience_competencies_set_updated_at)
    op.drop_entity(public_experience_competencies_check_competency_subject)
    op.drop_entity(public_events_forbid_mutation)
    op.drop_entity(public_evaluation_criterion_capabilities_set_updated_at)
    op.drop_entity(public_evaluation_criterion_capabilities_check_criterion_capability_competency)
    op.drop_entity(public_evaluation_criterion_capabilities_check_criterion_capabilities)
    op.drop_entity(public_evaluation_criteria_set_updated_at)
    op.drop_entity(public_evaluation_criteria_check_criterion_on_write)
    op.drop_entity(public_evaluation_criteria_check_criterion_experience)
    op.drop_entity(public_descriptive_conclusions_set_updated_at)
    op.drop_entity(public_courses_set_updated_at)
    op.drop_entity(public_competency_year_snapshots_set_updated_at)
    op.drop_entity(public_competency_year_snapshots_forbid_mutation)
    op.drop_entity(public_competency_term_levels_set_updated_at)
    op.drop_entity(public_competency_exemptions_set_updated_at)
    op.drop_entity(public_competencies_set_updated_at)
    op.drop_entity(public_classes_set_updated_at)
    op.drop_entity(public_class_teachers_set_updated_at)
    op.drop_entity(public_class_sessions_set_updated_at)
    op.drop_entity(public_class_schedules_set_updated_at)
    op.drop_entity(public_capabilities_set_updated_at)
    op.drop_entity(public_attendance_records_sync_denormalised)
    op.drop_entity(public_attendance_records_set_updated_at)
    op.drop_entity(public_assessments_set_updated_at)
    op.drop_entity(public_assessment_criteria_set_updated_at)
    op.drop_entity(public_agent_generations_set_updated_at)
    op.drop_entity(public_academic_years_set_updated_at)
    op.execute("drop table if exists events_default")
    op.execute(
        """do $$
declare r record;
begin
  for r in select relname from pg_class where relname ~ '^events_\\d{4}_\\d{2}$' and relispartition loop
    execute format('drop table %I', r.relname);
  end loop;
end
$$"""
    )
    op.drop_constraint(
        "planned_evidences_session_entry_fk", "planned_evidences", type_="foreignkey"
    )
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "voice_note_redactions_note_idx",
        table_name="voice_note_redactions",
        postgresql_where=sa.text("(superseded_at IS NULL)"),
    )
    op.drop_table("voice_note_redactions")
    op.drop_index(
        "dc_term_idx",
        table_name="descriptive_conclusions",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "dc_regular_key",
        table_name="descriptive_conclusions",
        postgresql_where=sa.text(
            "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_index(
        "dc_recuperacion_key",
        table_name="descriptive_conclusions",
        postgresql_where=sa.text(
            "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_table("descriptive_conclusions")
    op.drop_index(
        "scores_supersedes_idx",
        table_name="scores",
        postgresql_where=sa.text("(supersedes_id IS NOT NULL)"),
    )
    op.drop_index(
        "scores_student_term_idx",
        table_name="scores",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "scores_live_key",
        table_name="scores",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "scores_class_term_idx",
        table_name="scores",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "scores_assessment_idx",
        table_name="scores",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("scores")
    op.drop_index(
        "notifications_unread_idx",
        table_name="notifications",
        postgresql_where=sa.text(
            "((read_at IS NULL) AND (dismissed_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_index(
        "notifications_student_idx",
        table_name="notifications",
        postgresql_where=sa.text("(student_id IS NOT NULL)"),
    )
    op.drop_index(
        "notifications_feed_idx",
        table_name="notifications",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("notifications")
    op.drop_index("assessment_criteria_criterion_idx", table_name="assessment_criteria")
    op.drop_table("assessment_criteria")
    op.drop_index(
        "agent_generations_voice_note_idx",
        table_name="agent_generations",
        postgresql_where=sa.text("(voice_note_id IS NOT NULL)"),
    )
    op.drop_index(
        "agent_generations_target_key",
        table_name="agent_generations",
        postgresql_where=sa.text("(status = ANY (ARRAY['pending'::text, 'running'::text]))"),
    )
    op.drop_index(
        "agent_generations_conclusion_scope_idx",
        table_name="agent_generations",
        postgresql_where=sa.text("(agent = 'conclusions'::text)"),
    )
    op.drop_index("agent_generations_class_idx", table_name="agent_generations")
    op.drop_table("agent_generations")
    op.drop_index(
        "voice_notes_transcription_idx",
        table_name="voice_notes",
        postgresql_where=sa.text(
            "((transcription_status = ANY (ARRAY['pending'::text, 'queued'::text, 'failed'::text])) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_index(
        "voice_notes_teacher_idx",
        table_name="voice_notes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "voice_notes_student_idx",
        table_name="voice_notes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "voice_notes_session_idx",
        table_name="voice_notes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "voice_notes_attribution_idx",
        table_name="voice_notes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("voice_notes")
    op.drop_index(
        "session_outline_entries_evidence_idx",
        table_name="session_outline_entries",
        postgresql_where=sa.text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "session_outline_entries_date_key",
        table_name="session_outline_entries",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("session_outline_entries")
    op.drop_index(
        "planned_evidence_criteria_pair_key",
        table_name="planned_evidence_criteria",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "planned_evidence_criteria_criterion_idx",
        table_name="planned_evidence_criteria",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("planned_evidence_criteria")
    op.drop_index(
        "evaluation_criterion_capabilities_pair_key",
        table_name="evaluation_criterion_capabilities",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "evaluation_criterion_capabilities_capability_idx",
        table_name="evaluation_criterion_capabilities",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("evaluation_criterion_capabilities")
    op.drop_index(
        "attendance_records_student_date_idx",
        table_name="attendance_records",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "attendance_records_session_student_key",
        table_name="attendance_records",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "attendance_records_session_idx",
        table_name="attendance_records",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "attendance_records_class_date_idx",
        table_name="attendance_records",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("attendance_records")
    op.drop_index(
        "assessments_student_idx",
        table_name="assessments",
        postgresql_where=sa.text("((student_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "assessments_session_idx",
        table_name="assessments",
        postgresql_where=sa.text("((session_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "assessments_planned_evidence_key",
        table_name="assessments",
        postgresql_where=sa.text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "assessments_due_idx",
        table_name="assessments",
        postgresql_where=sa.text("((status = 'published'::text) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "assessments_class_term_idx",
        table_name="assessments",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("assessments")
    op.drop_index(
        "planned_evidences_experience_idx",
        table_name="planned_evidences",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("planned_evidences")
    op.drop_index(
        "experience_competencies_pair_key",
        table_name="experience_competencies",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "experience_competencies_competency_idx",
        table_name="experience_competencies",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("experience_competencies")
    op.drop_index(
        "evaluation_criteria_performance_idx",
        table_name="evaluation_criteria",
        postgresql_where=sa.text("((performance_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "evaluation_criteria_experience_idx",
        table_name="evaluation_criteria",
        postgresql_where=sa.text("((experience_id IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "evaluation_criteria_competency_idx",
        table_name="evaluation_criteria",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "evaluation_criteria_capability_idx",
        table_name="evaluation_criteria",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("evaluation_criteria")
    op.drop_index(
        "cys_key",
        table_name="competency_year_snapshots",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("competency_year_snapshots")
    op.drop_index(
        "class_sessions_term_idx",
        table_name="class_sessions",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_sessions_date_idx",
        table_name="class_sessions",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_sessions_class_start_key",
        table_name="class_sessions",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_sessions_class_date_idx",
        table_name="class_sessions",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_sessions_attendance_pending_idx",
        table_name="class_sessions",
        postgresql_where=sa.text(
            "((attendance_taken_at IS NULL) AND (status = ANY (ARRAY['in_progress'::text, 'completed'::text])) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_table("class_sessions")
    op.drop_index(
        "learning_experiences_term_idx",
        table_name="learning_experiences",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "learning_experiences_class_range_idx",
        table_name="learning_experiences",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("learning_experiences")
    op.drop_index(
        "ctl_student_idx",
        table_name="competency_term_levels",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "ctl_regular_key",
        table_name="competency_term_levels",
        postgresql_where=sa.text(
            "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_index(
        "ctl_recuperacion_key",
        table_name="competency_term_levels",
        postgresql_where=sa.text(
            "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
        ),
    )
    op.drop_index(
        "ctl_class_term_idx",
        table_name="competency_term_levels",
        postgresql_where=sa.text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("competency_term_levels")
    op.drop_index(
        "class_teachers_teacher_idx",
        table_name="class_teachers",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_teachers_key",
        table_name="class_teachers",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("class_teachers")
    op.drop_index(
        "class_schedules_effective_idx",
        table_name="class_schedules",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "class_schedules_class_idx",
        table_name="class_schedules",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("class_schedules")
    op.drop_index(
        "section_memberships_student_idx",
        table_name="section_memberships",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "section_memberships_section_idx",
        table_name="section_memberships",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("section_memberships")
    op.drop_index(
        "classes_section_idx",
        table_name="classes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "classes_name_trgm_idx",
        table_name="classes",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "classes_course_section_key",
        table_name="classes",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("classes")
    op.drop_index(
        "yfs_key",
        table_name="year_final_situations",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("year_final_situations")
    op.drop_index(
        "terms_year_sequence_key",
        table_name="terms",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "terms_range_idx", table_name="terms", postgresql_where=sa.text("(deleted_at IS NULL)")
    )
    op.drop_index(
        "terms_one_active_key",
        table_name="terms",
        postgresql_where=sa.text("((status = 'active'::text) AND (deleted_at IS NULL))"),
    )
    op.drop_table("terms")
    op.drop_index(
        "sections_tutor_idx",
        table_name="sections",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "sections_natural_key",
        table_name="sections",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("sections")
    op.drop_index(
        "grade_level_performances_order_key",
        table_name="grade_level_performances",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "grade_level_performances_grade_idx",
        table_name="grade_level_performances",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("grade_level_performances")
    op.drop_index(
        "competency_exemptions_key",
        table_name="competency_exemptions",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("competency_exemptions")
    op.drop_index("question_bank_status_idx", table_name="question_bank", schema="chat")
    op.drop_table("question_bank", schema="chat")
    op.drop_index(
        "user_sessions_user_idx",
        table_name="user_sessions",
        postgresql_where=sa.text("(revoked_at IS NULL)"),
    )
    op.drop_index("user_sessions_token_hash_key", table_name="user_sessions")
    op.drop_index(
        "user_sessions_expiry_idx",
        table_name="user_sessions",
        postgresql_where=sa.text("(revoked_at IS NULL)"),
    )
    op.drop_table("user_sessions")
    op.drop_index(
        "teachers_membership_key",
        table_name="teachers",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "teachers_employee_code_key",
        table_name="teachers",
        postgresql_where=sa.text("((employee_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("teachers")
    op.drop_index(
        "learning_standards_competency_level_key",
        table_name="learning_standards",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("learning_standards")
    op.drop_index("messages_thread_idx", table_name="messages", schema="chat")
    op.drop_table("messages", schema="chat")
    op.drop_index(
        "capabilities_competency_code_key",
        table_name="capabilities",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("capabilities")
    op.drop_index(
        "non_teaching_days_year_idx",
        table_name="non_teaching_days",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "non_teaching_days_year_day_key",
        table_name="non_teaching_days",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("non_teaching_days")
    op.drop_index(
        "memberships_user_key",
        table_name="memberships",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "memberships_user_idx",
        table_name="memberships",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "memberships_one_school_per_user",
        table_name="memberships",
        postgresql_where=sa.text("((deleted_at IS NULL) AND (status <> 'revoked'::text))"),
    )
    op.drop_table("memberships")
    op.drop_index(
        "grade_scale_levels_scale_code_key",
        table_name="grade_scale_levels",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "grade_scale_levels_lookup_idx",
        table_name="grade_scale_levels",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("grade_scale_levels")
    op.drop_index(
        "courses_natural_key_no_code",
        table_name="courses",
        postgresql_where=sa.text("((code IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "courses_natural_key_coded",
        table_name="courses",
        postgresql_where=sa.text("((code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("courses")
    op.drop_index(
        "competencies_transversal_code_key",
        table_name="competencies",
        postgresql_where=sa.text("((subject_id IS NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "competencies_subject_code_key",
        table_name="competencies",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("competencies")
    op.drop_index(
        "threads_user_idx",
        table_name="threads",
        schema="chat",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("threads", schema="chat")
    op.drop_index(
        "users_username_key",
        table_name="users",
        postgresql_where=sa.text("((username IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "users_email_key", table_name="users", postgresql_where=sa.text("(deleted_at IS NULL)")
    )
    op.drop_table("users")
    op.drop_index(
        "subjects_code_key", table_name="subjects", postgresql_where=sa.text("(deleted_at IS NULL)")
    )
    op.drop_table("subjects")
    op.drop_index(
        "students_siagie_code_key",
        table_name="students",
        postgresql_where=sa.text("((siagie_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "students_name_trgm_idx",
        table_name="students",
        postgresql_using="gin",
        postgresql_ops={"full_name": "gin_trgm_ops"},
    )
    op.drop_index(
        "students_document_key",
        table_name="students",
        postgresql_where=sa.text("((document_number IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_index(
        "students_code_key",
        table_name="students",
        postgresql_where=sa.text("((student_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("students")
    op.drop_index(
        "standard_level_mappings_key",
        table_name="standard_level_mappings",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("standard_level_mappings")
    op.drop_index("school_singleton_key", table_name="school")
    op.drop_index(
        "school_modular_code_key",
        table_name="school",
        postgresql_where=sa.text("((modular_code IS NOT NULL) AND (deleted_at IS NULL))"),
    )
    op.drop_table("school")
    op.drop_index(
        "jobs_unique_key_idx",
        table_name="jobs",
        postgresql_where=sa.text(
            "((unique_key IS NOT NULL) AND (status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text, 'running'::text])))"
        ),
    )
    op.drop_index("jobs_kind_idx", table_name="jobs")
    op.drop_index(
        "jobs_finalized_idx",
        table_name="jobs",
        postgresql_where=sa.text("(finalized_at IS NOT NULL)"),
    )
    op.drop_index(
        "jobs_claim_idx",
        table_name="jobs",
        postgresql_where=sa.text(
            "(status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text]))"
        ),
    )
    op.drop_table("jobs")
    op.drop_index(
        "grade_scales_code_key",
        table_name="grade_scales",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("grade_scales")
    op.drop_index(
        "grade_levels_ordinal_key",
        table_name="grade_levels",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_index(
        "grade_levels_code_key",
        table_name="grade_levels",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("grade_levels")
    op.drop_index("events_time_idx", table_name="events")
    op.drop_index("events_student_time_idx", table_name="events")
    op.drop_index("events_entity_idx", table_name="events")
    op.drop_index("events_class_time_idx", table_name="events")
    op.drop_index("events_action_time_idx", table_name="events")
    op.drop_table("events")
    op.drop_table("pseudonyms", schema="chat")
    op.drop_index(
        "academic_years_year_key",
        table_name="academic_years",
        postgresql_where=sa.text("(deleted_at IS NULL)"),
    )
    op.drop_table("academic_years")
    # ### end Alembic commands ###
    op.drop_entity(app_validate_school_timezone)
    op.drop_entity(app_sync_score_denormalised)
    op.drop_entity(app_sync_attendance_denormalised)
    op.drop_entity(app_set_updated_at)
    op.drop_entity(app_log_event)
    op.drop_entity(app_forbid_year_close_mutation)
    op.drop_entity(app_forbid_score_mutation)
    op.drop_entity(app_forbid_event_mutation)
    op.drop_entity(app_ensure_events_partition)
    op.drop_entity(app_current_actor_id)
    op.drop_entity(app_check_session_entry_date)
    op.drop_entity(app_check_experience_inside_term)
    op.drop_entity(app_check_experience_competency_subject)
    op.drop_entity(app_check_evidence_criterion_experience)
    op.drop_entity(app_check_criterion_has_capability_on_write)
    op.drop_entity(app_check_criterion_has_capability)
    op.drop_entity(app_check_criterion_experience)
    op.drop_entity(app_check_criterion_capability_competency)
    op.execute("drop type public.timerange")
    op.execute("drop schema chat")
    op.execute("drop schema chat_api")
    op.execute("drop schema privacy")
    op.execute("drop schema app")
    # Roles, extensions and default privileges stay: roles are shared by every database in the
    # cluster, and dropping an extension could break another database's objects.
