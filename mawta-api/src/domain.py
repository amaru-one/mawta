"""The schema's text+CHECK "enums" as constants (port of internal/domain)."""

import unicodedata

# class_sessions.status
SESSION_SCHEDULED = "scheduled"
SESSION_IN_PROGRESS = "in_progress"
SESSION_COMPLETED = "completed"
SESSION_CANCELLED = "cancelled"
SESSION_RESCHEDULED = "rescheduled"

# scores.status
SCORE_GRADED = "graded"
SCORE_EXCUSED = "excused"
SCORE_ABSENT = "absent"
SCORE_NOT_SUBMITTED = "not_submitted"

# assessments.value_scale
VALUE_SCALE_NUMERIC = "numeric"
VALUE_SCALE_ORDINAL = "ordinal"

# assessments.kind and planned_evidences.kind
EVIDENCE_PRODUCCION = "produccion"
EVIDENCE_ACTUACION = "actuacion"


def is_evidence_kind(kind: str) -> bool:
    return kind in (EVIDENCE_PRODUCCION, EVIDENCE_ACTUACION)


# grade_scale_levels.code (MINEDU ordinal scale, C < B < A < AD). Spellings only.
LEVEL_C = "C"
LEVEL_B = "B"
LEVEL_A = "A"
LEVEL_AD = "AD"

# grade_levels.stage
STAGE_INICIAL = "inicial"
STAGE_PRIMARIA = "primaria"
STAGE_SECUNDARIA = "secundaria"
STAGE_OTRO = "otro"

# grade_levels.cycle (only when stage = inicial)
CYCLE_I = "ciclo_i"
CYCLE_II = "ciclo_ii"

# descriptive_conclusions.requirement
CONCLUSION_LEVEL_C = "level_c"
CONCLUSION_LEVEL_B = "level_b"
CONCLUSION_LEVEL_A = "level_a"
CONCLUSION_CYCLE_I_MANDATORY = "cycle_i_mandatory"
CONCLUSION_CONSECUTIVE_C = "consecutive_c"
CONCLUSION_INCLUSION_SUPPORT = "inclusion_support"
CONCLUSION_OPTIONAL = "optional"

# descriptive_conclusions.status
CONCLUSION_DRAFT = "draft"
CONCLUSION_FINAL = "final"

# jobs.kind
JOB_KIND_VOICE_NOTE_TRANSCRIBE = "voice_note.transcribe"
JOB_KIND_AGENT_GENERATE = "agent.generate"

# memberships.role and user_sessions.role
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_SUPERVISOR = "supervisor"
ROLE_ADMIN = "admin"
ROLE_DIRECTOR = "director"

# The whole of the role gate on login.
LOGIN_ENABLED_ROLES = {ROLE_TEACHER, ROLE_DIRECTOR}

# user_sessions.revoked_reason
SESSION_REVOKE_LOGOUT = "logout"
SESSION_REVOKE_EXPIRED = "expired"
SESSION_REVOKE_IDLE = "idle"
SESSION_REVOKE_PASSWORD_CHANGE = "password_change"
SESSION_REVOKE_ADMIN = "admin"


# A conclusión descriptiva is registered in SIAGIE, which accepts 10 to 350 characters. Every
# conclusion respects it, draft or final: the teacher never holds a text that could not be exported.
CONCLUSION_MIN_CHARS = 10
CONCLUSION_MAX_CHARS = 350


def normalize_conclusion(text: str) -> str:
    """One paragraph in NFC, with line breaks and runs of whitespace collapsed to a single
    space. NFC matters for the count: a decomposed "á" is two code points."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def conclusion_length(text: str) -> int:
    """Characters, not bytes: "ñ" is one character but two bytes in UTF-8."""
    return len(text)
