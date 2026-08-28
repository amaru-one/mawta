# Recording real data

This is a runbook for hand-writing the SQL to onboard real data: a new
school, a section of students, teachers, classes, and a grading scheme.
`seed_demo_tenant.sql` in this directory is the worked example — every
pattern below is lifted directly from it, so when in doubt, search that file
for the table name and copy the shape of the insert.

Nothing here is a migration — see *Applying the seed* below for how to run
it, locally and on the server.

## Applying the seed

Apply in order: the goose migrations under `migrations/`, then
`seed_demo_tenant.sql`. It is not idempotent — its two `do $$ ... end $$;`
blocks each rely on a unique index to reject a second run — so re-applying
means resetting the database first, not running the file twice.

Each of the two blocks is already all-or-nothing; a clean run prints `DO`
twice.

### Local

`../docs/postgres-setup.md` covers standing the container up (`yanai-pg`,
host port 55432). It ships its own `psql` and nothing is bind-mounted, so
pipe the file in over stdin — no host client needed:

```sh
cd yanai-server
docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1 \
  < seed/seed_demo_tenant.sql
```

If you do have a host `psql` (`brew install libpq`), the `DATABASE_URL` form
works too:

```sh
psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
```

### On the server (`/srv/yanai`)

`deploy/docker-compose.prod.yml` bind-mounts this directory read-only at
`/seed` inside the postgres container, so the file is addressed by path
rather than piped.

**`git pull` first.** The deploy workflow rsyncs only the SPA and `deploy/`,
never the repo clone that mount points at — without a pull you apply a stale
file. This bit for real on 2026-08-24; `../../DEPLOY.md` has the full note,
including the matching `docker compose pull api` trap for migrations.

```sh
ssh deploy@<your-server>
cd /srv/yanai
git pull --ff-only

C="docker compose --env-file .env -f deploy/docker-compose.prod.yml"
$C exec -T postgres psql -U postgres -d yanai -v ON_ERROR_STOP=1 \
  -f /seed/seed_demo_tenant.sql
```

`DEPLOY.md`
§4 covers the first deploy (migrate, then seed) and the full drop-and-reseed.
Reseeding production is routine only while it holds nothing but the demo
tenant; once there is real student data it is a restore-from-backup job.

### Dry-running it first

Wrap it in a transaction you roll back. The `set constraints all immediate`
is not optional: `check_weights_sum` is `DEFERRABLE INITIALLY DEFERRED`, so a
plain rollback never fires it and a scheme whose weights don't sum to 1 would
sail through the rehearsal.

```sh
{ echo 'begin;'; cat seed/seed_demo_tenant.sql;
  echo 'set constraints all immediate;'; echo 'rollback;'; } \
  | docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1
```

### Undoing it

Hard deletes are permitted in development (`app.attach_soft_delete_guard` is
a no-op), but a *published* scheme version's weight rows stay guarded. Open
the escape hatch the schema provides for exactly this case, in the same
transaction as the deletes:

```sql
select set_config('app.tenant_id', '<tenant uuid>', true);
select set_config('app.allow_hard_delete', 'on', true);
```

Then delete children before parents: `evaluation_criterion_scores`,
`assessment_criteria`, `scores`, `class_sessions`, `class_schedules`,
`class_teachers`, `assessments`, `classes`, `section_memberships`,
`sections`, `courses`, `evaluation_criteria`, `performance_standards`,
`capabilities`, `competencies`, then the scheme's weights, version,
components and scheme, then `subjects`. Delete a version's weight rows and
the version in the same transaction — the deferred sum check skips a version
that no longer exists, and would otherwise fire on a sum of 0.

## The one thing that will bite you first

Every tenant-scoped table has `FORCE ROW LEVEL SECURITY`, and `FORCE` applies
even to the table owner — which includes whatever role runs your script.
Every write you make must be preceded, in the same session/transaction, by:

```sql
select set_config('app.tenant_id', '<the tenant's uuid>', true);
```

Skip this and your inserts don't error — they silently affect zero rows, or
get rejected by the `WITH CHECK` policy, which is worse to debug. Set it
once at the top of your script and keep the whole thing in one anonymous
PL/pgSQL block (`do ... end;`), as `seed_demo_tenant.sql` does, so there's no
chance of a second session losing the setting.

If the tenant doesn't exist yet, you obviously can't scope to its id before
creating it — create the `tenants` row first, `returning id`, then set
`app.tenant_id` from that before anything else.

## 1. Recording a new school (tenant)

```sql
insert into tenants (id, name, legal_name, kind, city, region, timezone, modular_code)
values (gen_random_uuid(), 'I.E. <name>', '<legal name>', 'parroquial' | 'publica' | 'privada' | ...,
        '<city>', '<region>', 'America/Lima', '<MINEDU modular code>')
returning id into v_tenant;

select set_config('app.tenant_id', v_tenant::text, true);
```

Then, still scoped to that tenant: an `academic_years` row (start/end dates,
`term_structure`), followed by `terms` (one row per bimestre/trimestre —
`sequence`, date range, `status`). See `seed_demo_tenant.sql`'s "Tenant,
calendar, grade levels" section for the full shape, including how a closed
term's `status` and `closed_at` must be set together (there's a check
constraint on that pairing).

Also record `grade_levels` (the grados the school offers) here — everything
downstream (`courses`, `sections`) hangs off a `grade_level_id`.

## 2. Recording a new section of students

A section is a roster, dated. There's no per-class enrollment — the roster
*is* the section (see `ANALYSIS.md` point 8 if you need a subject-elective
exception later; it's explicitly out of scope for now).

```sql
insert into sections (tenant_id, academic_year_id, grade_level_id, label, name, tutor_teacher_id, shift, capacity)
values (v_tenant, v_year, v_grade_level, 'B', '5to B', v_tutor_teacher, 'manana', 32)
returning id into v_section;

insert into students (tenant_id, student_code, given_name, paternal_surname, maternal_surname,
                      birthdate, sex, document_type, document_number, enrolled_on)
values (v_tenant, 'EST-2026-XXX', ..., date '2026-03-02');

insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on)
select v_tenant, s.id, v_section, v_year, date '2026-03-02'
  from students s where s.id = ...;
```

A student who transfers out mid-year is never deleted — set `left_on` (and
`status = 'transferred'`, `exit_reason`) on their `section_memberships` row.
Every prior attendance and score row stays attached to them. Attendance
denominators are evaluated **as of the session date**, not as of today — see
`seed_demo_tenant.sql`'s attendance join (`sm.joined_on <= sess.session_date
and (sm.left_on is null or sm.left_on > sess.session_date)`) for the pattern
to copy in your own queries.

## 3. Recording a new teacher

```sql
insert into users (email, given_name, family_name, display_name, status)
values ('<email>', '<given>', '<family>', '<display>', 'active')
returning id into v_user;

insert into memberships (tenant_id, user_id, role, status, joined_at)
values (v_tenant, v_user, 'teacher', 'active', now())
returning id into v_membership;

insert into teachers (tenant_id, membership_id, employee_code, display_name, title, hired_on, weekly_hours_contracted)
values (v_tenant, v_membership, '<employee code>', '<display>', '<title>', '<hired_on>', <hours>)
returning id into v_teacher;
```

A teacher only teaches a class from the point they're assigned to it —
that's `class_teachers`, dated the same way as `section_memberships` (see
§5).

## 4. Recording a new class

A class = a course (subject + grade level) taught to one section.

```sql
insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
values (...);

insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours)
values (v_tenant, v_year, v_subject, v_grade_level, '<name>', '<code>', <hours>)
returning id into v_course;

insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
values (v_tenant, v_year, v_course, v_section, '<name>', '<code>', '<room>')
returning id into v_class;

insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
values (v_tenant, v_class, v_teacher, 'titular', '<date>');

-- The recurring weekly pattern (screen 01's "ESTA SEMANA", screen 02's "4 sesiones/semana"):
insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
values (v_tenant, v_class, <1=Mon..7=Sun>, '<start time>', '<end time>', '<room>', '<date>');
```

`class_schedules` is the recurring pattern; `class_sessions` are the
concrete dated instances generated from it (or ad-hoc, with `schedule_id`
null). Don't hand-write `class_sessions` far in advance — generate them
close to when they'll actually happen, the way the seed script only creates
sessions for dates that already have real attendance/topic data.

A course can override the school's default grading scale — see
`seed_demo_tenant.sql`'s Matemática course (`courses.grading_scheme_id`) for
the pattern: most subjects inherit `tenants.default_grading_scheme_id`, one
subject sets its own.

## 5. Recording a grading scheme for a class

A scheme has scales, components, and versions — versions carry the actual
weights, and a new version is a new row, never an edit to a published one.

```sql
insert into grade_scales (tenant_id, code, name, kind, min_value, max_value, passing_value, decimals)
values (v_tenant, '<code>', '<name>', 'ordinal' | 'numeric', 0, 20, 11, 0)
returning id into v_scale;

insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal,
                                min_normalized, max_normalized, is_passing, color_key)
values (v_tenant, v_scale, ..., <band edges 0.0-1.0>, ...);

insert into grading_schemes (tenant_id, scale_id, code, name, description)
values (v_tenant, v_scale, '<code>', '<name>', '<description>')
returning id into v_scheme;

insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
values (v_tenant, v_scheme, '<code>', '<name>', <order>);

insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                     rounding_mode, absent_counts_as, retake_policy, ...)
values (v_tenant, v_scheme, 1, '<date>', 'half_up', 'zero', 'capped', ...)
returning id into v_version;

insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
values (v_tenant, v_version, v_component, <weight>, 'mean' | 'weighted_mean' | 'last', <n>);

update grading_scheme_versions set published_at = now(), published_by_id = v_teacher where id = v_version;
```

**Weights for one version's components must sum to exactly 1** — not
0.999999, not "close enough" (see `ANALYSIS.md` point 6 for why the schema
doesn't tolerate an epsilon). Three equal components are `0.333333 /
0.333333 / 0.333334`; do that rounding yourself before the insert, the
database will reject anything else.

To re-weight a scheme mid-year without disturbing grades already computed
under the old weights: insert a **new** `grading_scheme_versions` row with a
later `effective_from`, close the old version off
(`update ... set effective_to = <new version's effective_from>`), then
publish the new one. Never edit a published version's weights in place —
`app.forbid_published_weight_mutation` in `migrations/00001_initial_schema.sql`
enforces this once a version is published.

## 6. Recording criterios de evaluación and rubric scores

The CNEB layer below `competencies`: capacidades, desempeños, and the
teacher's own criterios de evaluación. `seed_demo_tenant.sql`'s Matemática
block is the worked example — search it for `capabilities` to see the
pattern in context.

```sql
insert into capabilities (tenant_id, competency_id, code, name, sort_order)
values (v_tenant, v_competency, '<code>', '<capacidad name>', <order>)
returning id into v_capability;

insert into performance_standards (tenant_id, capability_id, grade_level_id, code, description)
values (v_tenant, v_capability, v_grade_level, '<code>', '<desempeño text>')
returning id into v_performance_standard;

insert into evaluation_criteria (tenant_id, competency_id, performance_standard_id, code, description, sort_order)
values (v_tenant, v_competency, v_performance_standard, '<code>', '<criterio precisado>', <order>)
returning id into v_criterion;

-- Which assessment evidences this criterio (sibling of assessment_competencies,
-- at criterio granularity):
insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
values (v_tenant, v_assessment, v_criterion);
```

Both `performance_standard_id` on `evaluation_criteria` and `grade_level_id`
on `performance_standards` are nullable — a school loads its curriculum
incrementally, capacidad by capacidad and desempeño by desempeño, not all at
once. Not every capacidad needs a desempeño row yet, and a teacher can write
a criterio ad hoc before the national desempeño behind it is loaded.

Recording a per-student, per-criterio rubric result is append-only, exactly
like `scores`:

```sql
insert into evaluation_criterion_scores (tenant_id, assessment_id, criterion_id, student_id, scale_level_id, recorded_by_id)
values (v_tenant, v_assessment, v_criterion, v_student, v_scale_level, v_teacher);
```

`class_id` and `term_id` are denormalised from the assessment by a trigger —
never supply them. A student who submitted nothing gets no row at all,
rather than one at the lowest level: absence of evidence is not the same as
evidence of the lowest level, the same principle `competency_term_levels`
already follows. Correcting a result never updates the row in place — stamp
`superseded_at` on the old row, then insert the replacement with
`supersedes_id` set, same as correcting a `scores` row.
