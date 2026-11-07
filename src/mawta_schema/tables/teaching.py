"""Courses, classes, their teachers and timetable, sessions and attendance."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="courses_pkey"),
        UniqueConstraint("academic_year_id", "grade_level_id", "id", name="courses_year_grade_key"),
        UniqueConstraint("academic_year_id", "id", name="courses_year_key"),
        ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="courses_grade_level_fk"
        ),
        ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="courses_subject_fk"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="courses_year_fk"),
        CheckConstraint("(weekly_hours >= (0)::numeric)", name="courses_weekly_hours_check"),
        Index(
            "courses_natural_key_coded",
            "academic_year_id",
            "subject_id",
            "grade_level_id",
            "code",
            unique=True,
            postgresql_where=text("((code IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "courses_natural_key_no_code",
            "academic_year_id",
            "subject_id",
            "grade_level_id",
            unique=True,
            postgresql_where=text("((code IS NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "Una asignatura dictada en un grado en un año determinado. Se ubica entre subjects y classes para que el currículo y la política de calificación se definan una vez por grado, no una vez por section."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    grade_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    weekly_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        comment="Horas semanales nominales según el plan de estudios. La cifra real viene de class_schedules; este es el plan contra el cual comparar.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Class(Base):
    __tablename__ = "classes"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="classes_pkey"),
        UniqueConstraint("academic_year_id", "id", name="classes_year_key"),
        ForeignKeyConstraint(
            ["academic_year_id", "grade_level_id", "course_id"],
            ["courses.academic_year_id", "courses.grade_level_id", "courses.id"],
            name="classes_course_fk",
        ),
        ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="classes_grade_level_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id", "grade_level_id", "section_id"],
            ["sections.academic_year_id", "sections.grade_level_id", "sections.id"],
            name="classes_section_fk",
        ),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="classes_year_fk"),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'archived'::text, 'cancelled'::text]))",
            name="classes_status_check",
        ),
        Index(
            "classes_course_section_key",
            "course_id",
            "section_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "classes_name_trgm_idx",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("classes_section_idx", "section_id", postgresql_where=text("(deleted_at IS NULL)")),
        {
            "comment": 'Una course dictada a una section: "Inglés 5to B". La unidad en la que realmente trabaja el docente — casi toda la aplicación se enfoca en una sola class. classes_course_fk/classes_section_fk son compuestas sobre academic_year_id y grade_level_id, así que una class no puede apuntar a una course o section de un año distinto al suyo, ni combinar una course y una section de grados distintos entre sí.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    grade_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Copiado del grado de la course/section que dicta. No es una fuente independiente de verdad: existe para que classes_course_fk/classes_section_fk puedan ser compuestas sobre él y así impedir una class que mezcle una course de un grado con una section de otro.",
    )
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(
        Text,
        comment='Nombre para mostrar. Se almacena porque es la cadena sobre la que buscan los docentes, y porque "Historia 5to C" y "Math 8B" no siguen una única regla de derivación.',
    )
    code: Mapped[str | None] = mapped_column(Text)
    default_room: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassTeacher(Base):
    __tablename__ = "class_teachers"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="class_teachers_pkey"),
        ExcludeConstraint(
            ("class_id", "="),
            (text("daterange(starts_on, ends_on, '[)'::text)"), "&&"),
            name="class_teachers_one_titular",
            using="gist",
            where=text("((role = 'titular'::text) AND (deleted_at IS NULL))"),
        ),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="class_teachers_class_fk"),
        ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name="class_teachers_teacher_fk"),
        CheckConstraint(
            "((ends_on IS NULL) OR (ends_on >= starts_on))", name="class_teachers_range_valid"
        ),
        CheckConstraint(
            "(role = ANY (ARRAY['titular'::text, 'auxiliar'::text, 'practicante'::text, 'reemplazo'::text]))",
            name="class_teachers_role_check",
        ),
        Index(
            "class_teachers_key",
            "class_id",
            "teacher_id",
            "starts_on",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "class_teachers_teacher_idx",
            "teacher_id",
            "starts_on",
            "ends_on",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Quién dicta una class, en qué calidad, durante qué fechas. Una class tiene exactamente un titular a la vez y cualquier número de auxiliares."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text, server_default=text("'titular'::text"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassSchedule(Base):
    __tablename__ = "class_schedules"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="class_schedules_pkey"),
        ExcludeConstraint(
            ("class_id", "="),
            ("weekday", "="),
            (text("timerange(starts_at, ends_at, '[)'::text)"), "&&"),
            (text("daterange(effective_from, effective_to, '[)'::text)"), "&&"),
            name="class_schedules_no_overlap",
            using="gist",
            where=text("(deleted_at IS NULL)"),
        ),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="class_schedules_class_fk"),
        CheckConstraint(
            "((effective_to IS NULL) OR (effective_to > effective_from))",
            name="class_schedules_range_valid",
        ),
        CheckConstraint("(ends_at > starts_at)", name="class_schedules_time_valid"),
        CheckConstraint(
            "((weekday >= 1) AND (weekday <= 7))", name="class_schedules_weekday_check"
        ),
        Index(
            "class_schedules_class_idx",
            "class_id",
            "weekday",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "class_schedules_effective_idx",
            "effective_from",
            "effective_to",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "El patrón semanal recurrente de una class: una fila por franja semanal. Distinto de class_sessions, que son las instancias concretas con fecha. Un cambio de horario cierra la fila antigua con effective_to y abre una nueva, así que las sesiones pasadas se siguen explicando por sí mismas."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    weekday: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Día de la semana ISO-8601, 1 = lunes .. 7 = domingo. Coincide con extract(isodow), para que el generador pueda hacer join sin aritmética.",
    )
    starts_at: Mapped[time] = mapped_column(
        Time,
        comment='Hora local de reloj en la zona horaria del colegio. Deliberadamente no es timestamptz: "10:00 los lunes" debe sobrevivir a un cambio de horario tipo DST, y el instante UTC concreto se materializa en class_sessions.',
    )
    ends_at: Mapped[time] = mapped_column(Time)
    room: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassSession(Base):
    __tablename__ = "class_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="class_sessions_pkey"),
        ForeignKeyConstraint(
            ["attendance_taken_by_id"], ["teachers.id"], name="class_sessions_attendance_by_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id", "class_id"],
            ["classes.academic_year_id", "classes.id"],
            name="class_sessions_class_fk",
        ),
        ForeignKeyConstraint(
            ["schedule_id"], ["class_schedules.id"], name="class_sessions_schedule_fk"
        ),
        ForeignKeyConstraint(
            ["started_by_id"], ["teachers.id"], name="class_sessions_started_by_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="class_sessions_term_fk",
        ),
        ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="class_sessions_year_fk"
        ),
        CheckConstraint(
            "((actual_end_at IS NULL) OR (actual_start_at IS NULL) OR (actual_end_at >= actual_start_at))",
            name="class_sessions_actual_valid",
        ),
        CheckConstraint(
            "((attendance_taken_at IS NULL) = (attendance_taken_by_id IS NULL))",
            name="class_sessions_attendance_consistent",
        ),
        CheckConstraint(
            "((status = ANY (ARRAY['in_progress'::text, 'completed'::text])) <= (actual_start_at IS NOT NULL))",
            name="class_sessions_started_consistent",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['scheduled'::text, 'in_progress'::text, 'completed'::text, 'cancelled'::text, 'rescheduled'::text]))",
            name="class_sessions_status_check",
        ),
        CheckConstraint(
            "(scheduled_end_at > scheduled_start_at)", name="class_sessions_window_valid"
        ),
        Index(
            "class_sessions_attendance_pending_idx",
            "session_date",
            postgresql_where=text(
                "((attendance_taken_at IS NULL) AND (status = ANY (ARRAY['in_progress'::text, 'completed'::text])) AND (deleted_at IS NULL))"
            ),
        ),
        Index(
            "class_sessions_class_date_idx",
            "class_id",
            text("session_date DESC"),
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "class_sessions_class_start_key",
            "class_id",
            "scheduled_start_at",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "class_sessions_date_idx",
            "session_date",
            "status",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "class_sessions_term_idx",
            "term_id",
            "status",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'Una instancia con fecha concreta de una class. Ciclo de vida scheduled -> in_progress -> completed, con cancelled y rescheduled como alternativas terminales. La tarjeta "HOY · SIN INICIAR" es una fila scheduled para hoy; el botón "Iniciar clase" la mueve a in_progress y registra actual_start_at.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Copiado del academic_year_id de la class al crear la sesión. class_sessions_class_fk/class_sessions_term_fk son compuestas sobre esta columna, así que una sesión no puede apuntar a un term de un año distinto al de su class.",
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La franja recurrente de la que proviene esta instancia. Null para una sesión puntual agregada a mano, para que una clase de reposición ad hoc sea representable sin inventar una regla semanal.",
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    session_date: Mapped[date] = mapped_column(Date)
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'scheduled'::text"))
    topic: Mapped[str | None] = mapped_column(
        Text,
        comment='Qué cubre la sesión, ej. "Present perfect tense". Se muestra tanto para la próxima sesión como para las pasadas.',
    )
    room: Mapped[str | None] = mapped_column(Text)
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attendance_taken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment='Null significa que la asistencia nunca se marcó, que es exactamente lo que activa el recordatorio de "Asistencia sin marcar". Distinto de una sesión donde todos estuvieron ausentes.',
    )
    attendance_taken_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="attendance_records_pkey"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="attendance_records_class_fk"),
        ForeignKeyConstraint(
            ["recorded_by_id"], ["teachers.id"], name="attendance_records_recorded_by_fk"
        ),
        ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="attendance_records_session_fk"
        ),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="attendance_records_student_fk"),
        CheckConstraint(
            "((minutes_late IS NULL) OR (status = 'late'::text))",
            name="attendance_records_late_consistent",
        ),
        CheckConstraint("(minutes_late >= 0)", name="attendance_records_minutes_late_check"),
        CheckConstraint(
            "(source = ANY (ARRAY['manual'::text, 'bulk'::text, 'import'::text, 'auto'::text]))",
            name="attendance_records_source_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['present'::text, 'late'::text, 'absent'::text, 'excused'::text, 'justified'::text]))",
            name="attendance_records_status_check",
        ),
        Index(
            "attendance_records_class_date_idx",
            "class_id",
            "session_date",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "attendance_records_session_idx",
            "session_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "attendance_records_session_student_key",
            "session_id",
            "student_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "attendance_records_student_date_idx",
            "student_id",
            text("session_date DESC"),
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'DATOS PERSONALES DE MENORES (conductuales). Una fila por estudiante por sesión. Se registran con un toque a la vez o en bloque vía "Todos presentes"; de aquí se lee la "Asistencia 94%".'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Desnormalizado desde la sesión. Presente para que las tasas de asistencia por class no necesiten un join, y se mantiene por trigger en vez de por la aplicación.",
    )
    session_date: Mapped[date] = mapped_column(
        Date,
        comment="Desnormalizado desde la sesión. La regla de ausencias consecutivas recorre los registros de un estudiante en orden de fecha; sin esto el recorrido necesitaría un join y un ordenamiento en cada evaluación.",
    )
    status: Mapped[str] = mapped_column(
        Text,
        comment="excused y justified son distintos: excused significa que el colegio autorizó la ausencia por adelantado, justified significa que se aceptó un motivo válido después. Ambas son ausencias para la familia, ninguna cuenta en contra del estudiante.",
    )
    minutes_late: Mapped[int | None] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Text,
        server_default=text("'manual'::text"),
        comment='Cómo se creó la fila. bulk marca un toque de "Todos presentes", lo cual vale la pena distinguir de los toques individuales al juzgar qué tan confiable es el dato.',
    )
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
