-- Risk detection and notifications.
--
-- Screen 05 shows a teacher why a student was flagged, not just that they were.
-- That requirement is what makes risk_flag_evidence a table rather than a
-- sentence in a payload: the alert has to be traceable back to the sessions and
-- scores that produced it.

-- +goose Up

-- ---------------------------------------------------------------------------
-- risk_rules
-- ---------------------------------------------------------------------------
create table risk_rules (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  code         text not null,
  name         text not null,
  description  text,
  kind         text not null default 'rule' check (kind in ('rule', 'model')),
  version      text not null default '1',
  params       jsonb not null default '{}'::jsonb,
  severity     text not null default 'medium' check (severity in ('info', 'low', 'medium', 'high')),
  window_days  smallint check (window_days > 0),
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  constraint risk_rules_tenant_id_key unique (tenant_id, id)
);

comment on table risk_rules is 'The detectors behind screen 02''s "Alumnos en riesgo" and screen 05''s alerts. Deterministic rules ("3 ausencias seguidas") and model versions share one table so a flag always names what produced it, whichever it was.';
comment on column risk_rules.kind is 'rule = a threshold a human wrote and can explain. model = a learned scorer. The distinction matters when a teacher asks why, and when deciding whether a dismissal is a bug report or training data.';
comment on column risk_rules.version is 'Rule threshold revision or model version. Text, not integer, so a model version like "2026-03-risk-v2" can be recorded verbatim.';
comment on column risk_rules.params is 'Thresholds as data: {"consecutive_absences": 3} or {"level_drop_sessions": 3}. Tuning a rule is an UPDATE here plus a new version, not a deploy.';

create unique index risk_rules_tenant_code_version_key
  on risk_rules (tenant_id, code, version) where deleted_at is null;

select app.enable_tenant_rls('risk_rules');
select app.attach_updated_at('risk_rules');
select app.attach_soft_delete_guard('risk_rules');

-- ---------------------------------------------------------------------------
-- risk_flags
-- ---------------------------------------------------------------------------
create table risk_flags (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  class_id          uuid,
  rule_id           uuid not null,
  rule_version      text not null,
  severity          text not null default 'medium' check (severity in ('info', 'low', 'medium', 'high')),
  reason_code       text not null,
  reason_text       text not null,
  model_score       numeric(6, 5) check (model_score between 0 and 1),
  opened_at         timestamptz not null default now(),
  last_evaluated_at timestamptz not null default now(),
  status            text not null default 'active'
                      check (status in ('active', 'resolved', 'dismissed', 'expired')),
  resolved_at       timestamptz,
  dismissed_at      timestamptz,
  dismissed_by_id   uuid,
  dismissal_reason  text check (dismissal_reason in ('not_a_concern', 'already_handled', 'incorrect_data', 'wrong_call', 'other')),
  dismissal_note    text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint risk_flags_tenant_id_key unique (tenant_id, id),
  constraint risk_flags_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint risk_flags_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint risk_flags_rule_fk foreign key (tenant_id, rule_id)
    references risk_rules (tenant_id, id),
  constraint risk_flags_dismissed_by_fk foreign key (tenant_id, dismissed_by_id)
    references teachers (tenant_id, id),
  constraint risk_flags_dismissed_consistent
    check ((status = 'dismissed') = (dismissed_at is not null)),
  constraint risk_flags_dismissed_has_actor
    check (dismissed_at is null or dismissed_by_id is not null),
  constraint risk_flags_resolved_consistent
    check ((status = 'resolved') = (resolved_at is not null))
);

comment on table risk_flags is
  'MINORS'' PERSONAL DATA (inferred, sensitive). Which students are under tracking, since when, why, and by which rule or model version. Screen 06''s "Alumnos en seguimiento 23" counts distinct students with an active flag across a teacher''s classes; screen 02''s "En riesgo 2" is the same count for one class. Inferred data about a child carries the same protection as data the school was given.';

comment on column risk_flags.class_id is 'The class the flag arose in. Null for a flag that spans a student''s whole schedule, e.g. absence across every subject.';
comment on column risk_flags.rule_version is 'Copied from the rule at flag time. The rule row may be re-tuned later; the flag must keep saying which thresholds it actually fired on.';
comment on column risk_flags.reason_text is 'The sentence a teacher reads: "3 ausencias seguidas", "Bajó de A a B en 3 clases". Generated when the flag opens, stored so the alert on screen 05 still reads correctly after the underlying window has moved on.';
comment on column risk_flags.opened_at is 'When tracking began. This is the "since when" of the tracking requirement, and stays fixed while the flag remains open.';
comment on column risk_flags.dismissed_at is 'A teacher judged the flag wrong or already handled. Dismissals are never deleted: a dismissal is the only negative label this product generates, and it is the most valuable training signal in the schema.';
comment on column risk_flags.dismissal_reason is 'Why it was dismissed. incorrect_data and wrong_call are different labels for a model — one means the inputs were bad, the other means the inference was.';

-- One open flag per student, class and rule; re-firing updates rather than duplicates.
create unique index risk_flags_open_key
  on risk_flags (student_id, coalesce(class_id, '00000000-0000-0000-0000-000000000000'::uuid), rule_id)
  where status = 'active' and deleted_at is null;
-- Screen 02 "En riesgo 2" and the risk list for one class.
create index risk_flags_class_active_idx
  on risk_flags (class_id, severity) where status = 'active' and deleted_at is null;
-- Screen 06 "Alumnos en seguimiento 23": distinct tracked students in a tenant.
create index risk_flags_tenant_active_idx
  on risk_flags (tenant_id, student_id) where status = 'active' and deleted_at is null;
-- Training: dismissed flags with their reasons, over time.
create index risk_flags_dismissed_idx
  on risk_flags (rule_id, dismissed_at) where dismissed_at is not null;

select app.enable_tenant_rls('risk_flags');
select app.attach_updated_at('risk_flags');
select app.attach_soft_delete_guard('risk_flags');

-- ---------------------------------------------------------------------------
-- risk_flag_evidence
-- ---------------------------------------------------------------------------
create table risk_flag_evidence (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  risk_flag_id  uuid not null,
  entity_type   text not null
                  check (entity_type in ('attendance_record', 'score', 'computed_grade',
                                         'session_observation', 'voice_note', 'class_session')),
  entity_id     uuid not null,
  occurred_at   timestamptz not null,
  detail        jsonb not null default '{}'::jsonb,
  weight        numeric(6, 5) check (weight between 0 and 1),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint rfe_flag_fk foreign key (tenant_id, risk_flag_id)
    references risk_flags (tenant_id, id) on delete cascade
);

comment on table risk_flag_evidence is 'The specific rows that caused a flag: the three absences, the three sessions where the level fell. Deliberately a polymorphic reference rather than six nullable foreign keys, because evidence types will grow and the set is append-only and read as a unit.';
comment on column risk_flag_evidence.entity_type is 'Which table entity_id points into. Not enforceable as a foreign key; the constraint list is the guard, and evidence rows are written only by the detection job.';
comment on column risk_flag_evidence.weight is 'For model-generated flags, this evidence item''s contribution to the score. Null for deterministic rules, where every item is simply part of the trigger.';

create index rfe_flag_idx on risk_flag_evidence (risk_flag_id, occurred_at desc);
create index rfe_entity_idx on risk_flag_evidence (entity_type, entity_id);

select app.enable_tenant_rls('risk_flag_evidence');
select app.attach_updated_at('risk_flag_evidence');

-- ---------------------------------------------------------------------------
-- notifications
-- ---------------------------------------------------------------------------
create table notifications (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants (id),
  recipient_teacher_id uuid not null,
  kind                 text not null check (kind in ('alert', 'reminder')),
  category             text not null,
  severity             text not null default 'info' check (severity in ('info', 'low', 'medium', 'high')),
  title                text not null,
  body                 text,
  payload              jsonb not null default '{}'::jsonb,
  student_id           uuid,
  class_id             uuid,
  session_id           uuid,
  assessment_id        uuid,
  risk_flag_id         uuid,
  source               text not null default 'system'
                         check (source in ('system', 'rule', 'model', 'teacher')),
  dedupe_key           text,
  created_at           timestamptz not null default now(),
  read_at              timestamptz,
  dismissed_at         timestamptz,
  expires_at           timestamptz,
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz,
  constraint notifications_recipient_fk foreign key (tenant_id, recipient_teacher_id)
    references teachers (tenant_id, id),
  constraint notifications_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint notifications_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint notifications_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint notifications_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint notifications_risk_flag_fk foreign key (tenant_id, risk_flag_id)
    references risk_flags (tenant_id, id),
  constraint notifications_alert_has_evidence
    check (kind <> 'alert' or source = 'teacher' or risk_flag_id is not null)
);

comment on table notifications is 'MINORS'' PERSONAL DATA (derived). The feed on screen 05. Alert titles and bodies name individual students and state inferences about them, so a notification row is student data even though it is addressed to a teacher. kind drives the Alertas/Recordatorios filter pills; read_at drives the unread dot and the dimmed "Leído" state. Every row carries the entity that triggered it, so tapping through lands on the student or class rather than on a dead end.';

comment on column notifications.category is 'Machine-readable subtype within the kind: level_drop, consecutive_absences, attendance_unmarked, grades_pending, no_voice_notes. What the client groups and filters on; title and body are for humans.';
comment on column notifications.risk_flag_id is 'The flag that produced this alert, and through it the evidence. Screen 05 states a claim about a child ("bajó de A a B en las últimas 3 clases"); the teacher must be able to reach what supports it.';
comment on column notifications.dedupe_key is 'Stable key identifying the underlying condition, e.g. "attendance_unmarked:<session_id>". Prevents the reminder job re-notifying every run for a condition the teacher has already seen. Screen 05''s "Sin notas de voz — Tutoría 8B" is generated from the absence of rows, which without this would fire daily forever.';
comment on column notifications.expires_at is 'When the reminder stops being worth showing. A "mark yesterday''s attendance" nudge is noise a week later.';
comment on constraint notifications_alert_has_evidence on notifications is 'An alert generated by a rule or model must point at the flag that justifies it. Reminders need no evidence, and a teacher-authored alert is its own justification.';

create unique index notifications_dedupe_key
  on notifications (recipient_teacher_id, dedupe_key)
  where dedupe_key is not null and deleted_at is null;
-- Screen 05: the feed, newest first, optionally filtered by kind.
create index notifications_feed_idx
  on notifications (recipient_teacher_id, created_at desc) where deleted_at is null;
-- The bell badge: does this teacher have anything unread?
create index notifications_unread_idx
  on notifications (recipient_teacher_id, kind)
  where read_at is null and dismissed_at is null and deleted_at is null;
create index notifications_student_idx on notifications (student_id) where student_id is not null;

select app.enable_tenant_rls('notifications');
select app.attach_updated_at('notifications');
select app.attach_soft_delete_guard('notifications');

-- +goose Down

drop table if exists notifications;
drop table if exists risk_flag_evidence;
drop table if exists risk_flags;
drop table if exists risk_rules;
