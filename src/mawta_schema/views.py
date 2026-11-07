"""Views: chat_api (the read contract of the director chat) and privacy (catalog audits)."""

from alembic_utils.pg_view import PGView

VIEWS = [
    PGView(
        schema="chat_api",
        signature="school",
        definition=r"""SELECT id,
    name,
    city,
    region,
    timezone
   FROM school t
  WHERE deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="sections",
        definition=r"""SELECT s.id,
    ay.year AS academic_year,
    ay.status AS academic_year_status,
    g.label AS grade,
    g.long_label AS grade_long,
    g.stage,
    s.label AS section,
    s.name,
    s.shift,
    s.status
   FROM sections s
     JOIN grade_levels g ON g.id = s.grade_level_id
     JOIN academic_years ay ON ay.id = s.academic_year_id
  WHERE s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="terms",
        definition=r"""SELECT t.id,
    ay.year AS academic_year,
    ay.status AS academic_year_status,
    t.stage,
    t.sequence,
    t.name,
    t.short_name,
    t.starts_on,
    t.ends_on,
    t.status,
    (now() AT TIME ZONE tn.timezone)::date >= t.starts_on AND (now() AT TIME ZONE tn.timezone)::date <= t.ends_on AS is_current,
    (EXISTS ( SELECT 1
           FROM competency_term_levels l
          WHERE l.term_id = t.id AND l.superseded_at IS NULL AND l.deleted_at IS NULL)) AS has_levels
   FROM terms t
     JOIN academic_years ay ON ay.id = t.academic_year_id
     CROSS JOIN school tn
  WHERE t.deleted_at IS NULL AND ay.deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="classes",
        definition=r"""SELECT c.id,
    ay.year AS academic_year,
    ay.status AS academic_year_status,
    g.label AS grade,
    g.long_label AS grade_long,
    g.ordinal AS grade_ordinal,
    g.stage,
    s.id AS section_id,
    s.label AS section,
    s.name AS section_name,
    s.shift,
    su.code AS subject_code,
    su.name AS subject_name,
    su.is_tutoria,
    titular.display_name AS teacher,
    tutor.display_name AS tutor
   FROM classes c
     JOIN sections s ON s.id = c.section_id
     JOIN grade_levels g ON g.id = s.grade_level_id
     JOIN academic_years ay ON ay.id = s.academic_year_id
     JOIN courses co ON co.id = c.course_id
     JOIN subjects su ON su.id = co.subject_id
     CROSS JOIN school tn
     LEFT JOIN LATERAL ( SELECT te.display_name
           FROM class_teachers ct
             JOIN teachers te ON te.id = ct.teacher_id
          WHERE ct.class_id = c.id AND ct.role = 'titular'::text AND ct.deleted_at IS NULL AND te.deleted_at IS NULL AND ct.starts_on <= (now() AT TIME ZONE tn.timezone)::date AND (ct.ends_on IS NULL OR ct.ends_on >= (now() AT TIME ZONE tn.timezone)::date)
          ORDER BY ct.starts_on DESC
         LIMIT 1) titular ON true
     LEFT JOIN teachers tutor ON tutor.id = s.tutor_teacher_id AND tutor.deleted_at IS NULL
  WHERE c.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL AND co.deleted_at IS NULL AND su.deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="students",
        definition=r"""SELECT st.id AS student_id,
    st.given_name,
    st.preferred_name,
    st.paternal_surname,
    st.maternal_surname,
    concat_ws(' '::text, COALESCE(st.preferred_name, st.given_name), st.paternal_surname, st.maternal_surname) AS full_name,
    ay.year AS academic_year,
    ay.status AS academic_year_status,
    g.label AS grade,
    g.long_label AS grade_long,
    g.ordinal AS grade_ordinal,
    g.stage,
    s.id AS section_id,
    s.label AS section,
    s.name AS section_name,
    sm.joined_on,
    sm.left_on,
    sm.status AS membership_status
   FROM section_memberships sm
     JOIN students st ON st.id = sm.student_id
     JOIN sections s ON s.id = sm.section_id
     JOIN grade_levels g ON g.id = s.grade_level_id
     JOIN academic_years ay ON ay.id = sm.academic_year_id
  WHERE sm.deleted_at IS NULL AND st.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL AND ay.deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="competencies",
        definition=r"""SELECT c.id,
    su.code AS subject_code,
    su.name AS subject_name,
    su.sort_order AS subject_order,
    c.code,
    c.name,
    c.sort_order
   FROM competencies c
     JOIN subjects su ON su.id = c.subject_id
  WHERE (c.kind = ANY (ARRAY['area'::text, 'adicional_area'::text])) AND c.is_active AND NOT su.is_tutoria AND c.deleted_at IS NULL AND su.deleted_at IS NULL""",
    ),
    PGView(
        schema="chat_api",
        signature="levels",
        definition=r"""SELECT l.id,
    st.id AS student_id,
    concat_ws(' '::text, COALESCE(st.preferred_name, st.given_name), st.paternal_surname, st.maternal_surname) AS full_name,
    st.paternal_surname,
    st.maternal_surname,
    ay.year AS academic_year,
    ay.status AS academic_year_status,
    g.label AS grade,
    g.long_label AS grade_long,
    g.ordinal AS grade_ordinal,
    g.stage,
    s.id AS section_id,
    s.label AS section,
    s.name AS section_name,
    su.code AS subject_code,
    su.name AS subject_name,
    su.sort_order AS subject_order,
    c.code AS competency_code,
    c.name AS competency_name,
    c.sort_order AS competency_order,
    t.id AS term_id,
    t.sequence AS term_sequence,
    t.name AS term_name,
    t.short_name AS term_short_name,
    sl.code AS level,
    sl.ordinal AS level_ordinal
   FROM competency_term_levels l
     JOIN students st ON st.id = l.student_id
     JOIN competencies c ON c.id = l.competency_id
     JOIN subjects su ON su.id = c.subject_id
     JOIN terms t ON t.id = l.term_id
     JOIN academic_years ay ON ay.id = l.academic_year_id
     JOIN grade_scale_levels sl ON sl.id = l.scale_level_id
     JOIN classes cl ON cl.id = l.class_id
     JOIN sections s ON s.id = cl.section_id
     JOIN grade_levels g ON g.id = s.grade_level_id
  WHERE l.superseded_at IS NULL AND l.deleted_at IS NULL AND (c.kind = ANY (ARRAY['area'::text, 'adicional_area'::text])) AND NOT su.is_tutoria AND st.deleted_at IS NULL AND c.deleted_at IS NULL AND su.deleted_at IS NULL AND t.deleted_at IS NULL AND ay.deleted_at IS NULL AND cl.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL""",
    ),
    PGView(
        schema="privacy",
        signature="pii_columns",
        definition=r"""SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    a.attname AS column_name,
    format_type(a.atttypid, a.atttypmod) AS data_type,
        CASE
            WHEN d.description ~~ 'PII (menor y adulto)%'::text THEN 'minor_and_adult'::text
            WHEN d.description ~~ 'PII (menor)%'::text THEN 'minor'::text
            WHEN d.description ~~ 'PII (adulto)%'::text THEN 'adult'::text
            ELSE 'unclassified'::text
        END AS subject,
    NULLIF(TRIM(BOTH FROM "substring"(d.description, 'PII \([^)]*\):\s*([^.]*)'::text)), ''::text) AS category,
    d.description AS note
   FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace
     JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
     JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum
  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::"char", 'p'::"char"])) AND d.description ~~ 'PII %'::text""",
    ),
    PGView(
        schema="privacy",
        signature="minor_data_tables",
        definition=r"""SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    d.description AS note
   FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace
     JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::"char", 'p'::"char"])) AND d.description ~~ '%DATOS PERSONALES DE MENORES%'::text""",
    ),
    PGView(
        schema="privacy",
        signature="undeclared_student_references",
        definition=r"""SELECT c.relname AS table_name,
    a.attname AS column_name
   FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace
     JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
     LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
  WHERE n.nspname = 'public'::name AND (c.relkind = ANY (ARRAY['r'::"char", 'p'::"char"])) AND NOT c.relispartition AND a.attname = 'student_id'::name AND COALESCE(d.description, ''::text) !~~ '%DATOS PERSONALES DE MENORES%'::text AND c.relname <> 'events'::name""",
    ),
]
