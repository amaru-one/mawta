"""The school itself and the people who sign in: users, memberships, sessions, teachers."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class School(Base):
    __tablename__ = "school"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="school_pkey"),
        CheckConstraint(
            "(kind = ANY (ARRAY['publica'::text, 'privada'::text, 'parroquial'::text, 'internacional'::text]))",
            name="school_kind_check",
        ),
        CheckConstraint("singleton", name="school_singleton_check"),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'suspended'::text, 'closed'::text]))",
            name="school_status_check",
        ),
        Index(
            "school_modular_code_key",
            "modular_code",
            unique=True,
            postgresql_where=text("((modular_code IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index("school_singleton_key", "singleton", unique=True),
        {
            "comment": "El colegio (institución educativa) de esta base de datos. Hay una sola fila: cada colegio tiene su propia base."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    legal_name: Mapped[str | None] = mapped_column(Text)
    modular_code: Mapped[str | None] = mapped_column(
        Text,
        comment="Código modular MINEDU de la institución educativa, cuando tiene uno. Null para colegios privados fuera del registro.",
    )
    kind: Mapped[str] = mapped_column(Text, server_default=text("'publica'::text"))
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        Text,
        server_default=text("'America/Lima'::text"),
        comment='Zona horaria IANA del colegio. Todos los timestamps se almacenan en UTC; este es el único lugar donde se define un día calendario local, y es contra el que se calcula "HOY".',
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    singleton: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("true"),
        comment="Siempre true: el índice único school_singleton_key garantiza que la base tenga un solo colegio.",
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="users_pkey"),
        CheckConstraint(
            "((username IS NULL) = (password_hash IS NULL))", name="users_credential_complete"
        ),
        CheckConstraint("(failed_login_count >= 0)", name="users_failed_login_count_check"),
        CheckConstraint(
            "(status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'deactivated'::text]))",
            name="users_status_check",
        ),
        CheckConstraint(
            "((username IS NULL) OR (username ~ '^[a-z0-9._-]{3,64}$'::text))",
            name="users_username_shape",
        ),
        Index(
            "users_email_key",
            text("(lower(email))"),
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "users_username_key",
            text("(lower(username))"),
            unique=True,
            postgresql_where=text("((username IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "PII (adulto). Principales de autenticación: los cuatro roles de membership (teacher, student, supervisor, admin). Contiene la credencial (username + password_hash). No contiene datos de menores — los estudiantes no son usuarios y no tienen inicio de sesión: memberships.role puede decir 'student', pero ninguna fila de students se vincula jamás a una fila de users."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(
        Text,
        comment="PII (adulto): contacto. Se pasa a minúsculas al escribir; la unicidad se aplica sobre lower(email).",
    )
    given_name: Mapped[str] = mapped_column(Text)
    family_name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text, comment="PII (adulto): contacto.")
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    username: Mapped[str | None] = mapped_column(
        Text,
        comment="PII (adulto): el identificador de inicio de sesión. Único globalmente sobre lower(username), igual que email y por la misma razón — una persona, una credencial, un colegio (ver memberships_one_school_per_user). Se pasa a minúsculas al escribir; users_username_shape lo restringe a [a-z0-9._-]{3,64} para que lower() sea una identidad verdadera. Email sigue siendo un dato de contacto y nunca es un inicio de sesión.",
    )
    password_hash: Mapped[str | None] = mapped_column(
        Text,
        comment="Hash bcrypt (costo desde BCRYPT_COST, por defecto 12) de la contraseña de la cuenta. Nunca se registra en logs, nunca se devuelve en ningún endpoint, solo lo lee internal/repo/auth.go. Null significa que la cuenta no tiene contraseña y no puede iniciar sesión; users_credential_complete mantiene eso emparejado con un username null.",
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Cuándo se estableció la contraseña por última vez. Cada fila de user_sessions del usuario se revoca (reason = 'password_change') cuando cambia.",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Último inicio de sesión exitoso, escrito por repo.RecordLoginSuccess.",
    )
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger,
        server_default=text("0"),
        comment="Inicios de sesión fallidos consecutivos desde el último éxito. Se reinicia a 0 en un éxito. Al llegar a LOGIN_MAX_FAILURES la cuenta se bloquea mediante locked_until, sin importar la contraseña en el siguiente intento.",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Expiración del bloqueo. Mientras esté en el futuro, todo intento de inicio de sesión para esta cuenta se rechaza con account_locked sin importar la contraseña.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="memberships_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="memberships_user_id_fkey"),
        CheckConstraint(
            "(role = ANY (ARRAY['teacher'::text, 'student'::text, 'supervisor'::text, 'admin'::text, 'director'::text]))",
            name="memberships_role_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'revoked'::text]))",
            name="memberships_status_check",
        ),
        Index(
            "memberships_one_school_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("((deleted_at IS NULL) AND (status <> 'revoked'::text))"),
        ),
        Index("memberships_user_idx", "user_id", postgresql_where=text("(deleted_at IS NULL)")),
        Index(
            "memberships_user_key",
            "user_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Qué usuario actúa en qué colegio, y con qué rol. El join que hace visible una fila de users bajo RLS, y la fila a la que resuelve un inicio de sesión. Cuatro roles: 'teacher' (el único que hoy puede completar un inicio de sesión), 'student', 'supervisor', 'admin'. Los otros tres están modelados — las verificaciones de permisos se escriben de forma genérica contra role — para poder habilitarlos más adelante solo ampliando domain.LoginEnabledRoles; un intento de inicio de sesión de uno de ellos hoy se rechaza con role_not_enabled. memberships_one_school_per_user limita a un usuario a exactamente un membership activo, así que el flujo de inicio de sesión nunca tiene que elegir entre varios."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="user_sessions_pkey"),
        ForeignKeyConstraint(
            ["membership_id"], ["memberships.id"], name="user_sessions_membership_fk"
        ),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="user_sessions_user_id_fkey"),
        CheckConstraint("(expires_at > created_at)", name="user_sessions_expires_after_created"),
        CheckConstraint(
            "((revoked_at IS NULL) = (revoked_reason IS NULL))",
            name="user_sessions_revocation_consistent",
        ),
        CheckConstraint(
            "(revoked_reason = ANY (ARRAY['logout'::text, 'expired'::text, 'idle'::text, 'password_change'::text, 'admin'::text]))",
            name="user_sessions_revoked_reason_check",
        ),
        CheckConstraint(
            "(role = ANY (ARRAY['teacher'::text, 'student'::text, 'supervisor'::text, 'admin'::text, 'director'::text]))",
            name="user_sessions_role_check",
        ),
        Index(
            "user_sessions_expiry_idx", "expires_at", postgresql_where=text("(revoked_at IS NULL)")
        ),
        Index("user_sessions_token_hash_key", "token_hash", unique=True),
        Index("user_sessions_user_idx", "user_id", postgresql_where=text("(revoked_at IS NULL)")),
        {
            "comment": "Sesiones del lado del servidor. El navegador guarda un token opaco de 256 bits en una cookie HttpOnly; aquí solo se almacena su sha256, así que leer esta tabla no permite suplantar a nadie. El único lector es el repositorio de autenticación de la API, siempre por token_hash exacto."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    token_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        comment="sha256 del token en crudo. El token en crudo solo existe en el header Set-Cookie y en el almacén de cookies del navegador — nunca se guarda, se registra en logs ni se devuelve de nuevo. sha256 en vez de bcrypt a propósito: la entrada son 256 bits de crypto/rand, ya inadivinables, así que no necesita factor de trabajo, y esto se lee en cada solicitud.",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(
        Text,
        comment="Copiado del membership al iniciar sesión y verificado de nuevo contra el membership vigente en cada solicitud (internal/httpapi.sessionAuth), de modo que un rol revocado o degradado después del inicio de sesión surte efecto de inmediato en lugar de esperar a que expire la sesión.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        comment="Se actualiza como máximo una vez por hora por sesión (repo.TouchSession), no en cada solicitud — escribir en cada solicitud convertiría cada GET en una transacción de lectura-escritura.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="Expiración absoluta, establecida al iniciar sesión a partir de SESSION_TTL. Nunca se extiende. La expiración por inactividad es una verificación aparte, calculada en Go a partir de last_seen_at contra SESSION_IDLE_TIMEOUT.",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(
        Text,
        comment="logout (iniciado por el usuario), expired/idle (revocado de forma perezosa al momento de la validación — no hay un scheduler en este código, ver internal/worker/SPEC.md, así que nada las depura de forma proactiva), password_change (cada sesión del usuario, al cambiar la contraseña), admin (reservado para una futura revocación iniciada por un administrador).",
    )
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="teachers_pkey"),
        ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="teachers_membership_fk"),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'on_leave'::text, 'inactive'::text]))",
            name="teachers_status_check",
        ),
        CheckConstraint(
            "(weekly_hours_contracted >= (0)::numeric)",
            name="teachers_weekly_hours_contracted_check",
        ),
        Index(
            "teachers_employee_code_key",
            "employee_code",
            unique=True,
            postgresql_where=text("((employee_code IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "teachers_membership_key",
            "membership_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "PII (adulto). Perfil docente por colegio. display_name, title y hired_on se muestran directamente; el correo y el inicio de sesión viven en la fila de users vinculada."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    employee_code: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(
        Text,
        comment='Etiqueta de rol, ej. "Docente de Secundaria". Texto libre: los colegios lo redactan de forma inconsistente y es solo para mostrar.',
    )
    hired_on: Mapped[date | None] = mapped_column(
        Date,
        comment='Fecha de inicio en este colegio. A partir de este valor se muestra "Desde marzo 2021 · 5 años".',
    )
    weekly_hours_contracted: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        comment='Horas semanales contratadas. El valor mostrado como "30h Semanales" se calcula en cambio a partir de class_schedules; esta es la cifra del contrato contra la cual conciliar.',
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
