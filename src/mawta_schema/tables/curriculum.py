"""The curriculum (CNEB): subjects, competencies, capabilities, performances and standards."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="subjects_pkey"),
        Index(
            "subjects_code_key", "code", unique=True, postgresql_where=text("(deleted_at IS NULL)")
        ),
        {
            "comment": "Un curso o asignatura del colegio: Matemática, Comunicación, Inglés, Historia, Geografía, Tutoría."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    area_curricular: Mapped[str | None] = mapped_column(
        Text,
        comment='Área curricular MINEDU a la que pertenece la asignatura, ej. "Ciencias Sociales" para Historia y Geografía. Se mantiene en español: es un término propio del currículo nacional, no una categoría genérica.',
    )
    icon_key: Mapped[str | None] = mapped_column(
        Text,
        comment="Clave estable para el ícono de las tarjetas de clase (calculadora, libro, banco, mundo). Se almacena en vez de derivarse del nombre, para que renombrar una asignatura no cambie su ícono.",
    )
    is_tutoria: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        comment='Tutoría se programa como una asignatura pero no se califica en la escala de logro. "Tutoría 5to A" aparece entre las clases; debe excluirse de los agregados de distribución de logro.',
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Competency(Base):
    __tablename__ = "competencies"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="competencies_pkey"),
        ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="competencies_subject_fk"),
        CheckConstraint(
            "(kind = ANY (ARRAY['area'::text, 'transversal'::text, 'adicional_area'::text, 'adicional_libre'::text]))",
            name="competencies_kind_check",
        ),
        CheckConstraint(
            "((kind = 'transversal'::text) = (subject_id IS NULL))",
            name="competencies_transversal_has_no_subject",
        ),
        Index(
            "competencies_subject_code_key",
            "subject_id",
            "code",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "competencies_transversal_code_key",
            "code",
            unique=True,
            postgresql_where=text("((subject_id IS NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": 'Una competencia MINEDU dentro de una asignatura, ej. "Se comunica oralmente en inglés como lengua extranjera". Las evidencias (assessments) llegan aquí a través de sus criterios de evaluación.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El área curricular o taller al que pertenece esta competencia. Null solo para kind = 'transversal': las dos competencias transversales CNEB no están adscritas a un área ni a un solo docente (5.1.1.3 p.8), y cada IE decide cómo se asigna su nivel.",
    )
    code: Mapped[str] = mapped_column(
        Text,
        comment="Código del currículo nacional cuando existe, o un código propio del colegio si no.",
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        Text,
        server_default=text("'area'::text"),
        comment="Qué cuenta esta competencia para la promoción (RVM 094-2020 num. 5.1.3 p.9-11). 'area': una competencia CNEB de un área curricular o taller — cuenta. 'adicional_area': una competencia agregada por el colegio y organizada en un área curricular — cuenta (5.1.3 p.11). 'adicional_libre': una competencia agregada por el colegio no organizada en un área — no cuenta (p.10). 'transversal': una de las dos competencias transversales CNEB — nunca cuenta (p.9), y no lleva subject_id.",
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="capabilities_pkey"),
        UniqueConstraint("competency_id", "id", name="capabilities_competency_key"),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="capabilities_competency_fk"
        ),
        Index(
            "capabilities_competency_code_key",
            "competency_id",
            "code",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'Una capacidad MINEDU, ej. "Utiliza estrategias y conocimientos matemáticos" bajo la competencia "Resuelve problemas de cantidad".'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(
        Text,
        comment="Código del currículo nacional cuando existe, o un código propio del colegio si no.",
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradeLevelPerformance(Base):
    __tablename__ = "grade_level_performances"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="grade_level_performances_pkey"),
        UniqueConstraint("competency_id", "id", name="grade_level_performances_competency_key"),
        UniqueConstraint("grade_level_id", "id", name="grade_level_performances_grade_key"),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="grade_level_performances_competency_fk"
        ),
        ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="grade_level_performances_grade_fk"
        ),
        ForeignKeyConstraint(
            ["competency_id", "suggested_capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="grade_level_performances_suggested_capability_fk",
        ),
        CheckConstraint(
            "((expected_standard_level >= 1) AND (expected_standard_level <= 8))",
            name="grade_level_performances_expected_standard_level_check",
        ),
        Index(
            "grade_level_performances_grade_idx",
            "grade_level_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "grade_level_performances_order_key",
            "competency_id",
            "grade_level_id",
            "sort_order",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Los desempeños de grado del programa oficial: por competencia y por grado, con su texto oficial y su postura frente al estándar del ciclo. Es la única fuente de la que un criterio puede derivar (decisión 2 del flujo): un criterio es el precisado del docente de uno de estos textos en la situación de la experiencia."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    grade_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sort_order: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Posición del desempeño dentro de su competencia y grado. Los programas listan los desempeños en un orden pedagógico; ese orden se conserva para mostrarlos tal como aparecen en el documento oficial.",
    )
    official_text: Mapped[str] = mapped_column(
        Text,
        comment="El texto literal del programa (RM 649-2016). Nunca se redacta ni se parafrasea en la app: el currículo no se inventa.",
    )
    en_proceso: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        comment='La postura del desempeño frente al estándar del ciclo: true = "en proceso hacia" el nivel esperado, false = "logra" el nivel esperado. Los programas de un grado intermedio describen avances hacia el estándar del fin de ciclo; los del grado final del ciclo describen el logro.',
    )
    expected_standard_level: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Nivel (1-8) del estándar de aprendizaje al que este desempeño apunta. Los programas lo declaran por grado; se guarda por fila para que el desempeño se lea junto al estándar correcto sin re-derivarlo del ciclo.",
    )
    suggested_capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="INFERIDO, NO OFICIAL. Los programas no etiquetan desempeños por capacidad: este vínculo es una pista que se calcula al cargar el currículo y que el docente puede ignorar. Nunca reemplaza el juicio del docente sobre qué capacidades mira un criterio. La FK compuesta (competency_id, suggested_capability_id) garantiza que la pista apunte a una capacidad de la misma competencia.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningStandard(Base):
    __tablename__ = "learning_standards"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="learning_standards_pkey"),
        UniqueConstraint("competency_id", "id", name="learning_standards_competency_key"),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="learning_standards_competency_fk"
        ),
        CheckConstraint("((level >= 1) AND (level <= 8))", name="learning_standards_level_check"),
        Index(
            "learning_standards_competency_level_key",
            "competency_id",
            "level",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Los estándares de aprendizaje del CNEB: por competencia y nivel (1-8), con su texto oficial. Son la referencia con la que se redacta la conclusión descriptiva de fin de ciclo, nunca una fuente de criterios: el criterio proviene del desempeño de grado, el estándar describe el punto de llegada del ciclo."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    level: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Nivel del estándar, 1-8: un nivel por fin de ciclo de la EBR. El mapeo (modalidad, ciclo) → nivel vive en standard_level_mappings.",
    )
    official_text: Mapped[str] = mapped_column(
        Text, comment="El texto literal del CNEB. Nunca se redacta ni se parafrasea en la app."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandardLevelMapping(Base):
    __tablename__ = "standard_level_mappings"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="standard_level_mappings_pkey"),
        CheckConstraint(
            "(cycle = ANY (ARRAY['ciclo_i'::text, 'ciclo_ii'::text, 'ciclo_iii'::text, 'ciclo_iv'::text, 'ciclo_v'::text, 'ciclo_vi'::text, 'ciclo_vii'::text]))",
            name="standard_level_mappings_cycle_check",
        ),
        CheckConstraint(
            "((expected_level >= 1) AND (expected_level <= 8))",
            name="standard_level_mappings_expected_level_check",
        ),
        CheckConstraint(
            "(modality = ANY (ARRAY['ebr'::text, 'ebe'::text, 'eja'::text]))",
            name="standard_level_mappings_modality_check",
        ),
        Index(
            "standard_level_mappings_key",
            "modality",
            "cycle",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'Qué nivel de estándar (1-8) corresponde a cada combinación de modalidad y ciclo, ej. (ebr, ciclo_vii) → 7. Permite resolver "el estándar de fin de ciclo de esta class" a partir del grado, sin codificarlo en Go ni asumir que todos los colegios siguen la EBR regular.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    modality: Mapped[str] = mapped_column(
        Text,
        comment="Modalidad del servicio educativo: ebr (Educación Básica Regular), ebe (Educación Básica Especial), eja (Educación Básica Alternativa).",
    )
    cycle: Mapped[str] = mapped_column(
        Text,
        comment="Ciclo de la modalidad. En EBR: ciclo_i (0-2 años), ciclo_ii (3-5), ciclo_iii (1ro-2do primaria), ciclo_iv (3ro-4to), ciclo_v (5to-6to), ciclo_vi (1ro-2do secundaria), ciclo_vii (3ro-5to).",
    )
    expected_level: Mapped[int] = mapped_column(
        SmallInteger,
        comment="El nivel (1-8) del estándar de aprendizaje que cierra ese ciclo. Un ciclo termina en un nivel: este mapeo es la única fuente de esa correspondencia.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
