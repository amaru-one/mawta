# Recording real data

This is a runbook for hand-writing the SQL to onboard real data: a new
school, a section of students, teachers, classes, and a grading scheme.
`seed_demo_tenant.sql` in this directory is the worked example — every
pattern below is lifted directly from it, so when in doubt, search that file
for the table name and copy the shape of the insert.

Nothing here is a migration. Apply the schema migrations first
(`migrations/00001`–`00014`), then run whatever script you write the same
way you'd run `seed_demo_tenant.sql`:

```sh
psql "$DATABASE_URL" -f your_script.sql
```

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
`seed_demo_tenant.sql`'s scheme-version-2 block is the worked example.
