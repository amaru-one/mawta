"""Per-resource authorization on top of the per-tenant isolation RLS gives us.

`session_auth` establishes a live session and an active teacher membership; RLS scopes
queries to the school. Neither says which *classes* the teacher teaches, so every
handler touching a class-scoped resource calls one of these guards, inside the
request's tenant transaction, before doing anything else. Cheap (one indexed exists);
favour calling them even where it looks redundant.
"""

from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.db import TenantCtx
from mawta_api.errors import AppError, NotFound
from mawta_api.repo import authz as repo
from mawta_api.repo.home import tenant_today


def forbidden(code: str, message: str) -> AppError:
    return AppError(403, code, message)


async def require_class_access(conn: AsyncConnection, tc: TenantCtx, class_id: UUID) -> None:
    """Fail unless the acting teacher is assigned to the class today."""
    today = await tenant_today(conn, tc.tenant_id)
    assert tc.teacher_id is not None
    if not await repo.teacher_teaches_class(conn, class_id, tc.teacher_id, today):
        raise forbidden("not_assigned_to_class", "you are not assigned to this class")


async def require_subject_access(
    conn: AsyncConnection, tc: TenantCtx, subject_id: UUID | None
) -> None:
    """The curriculum-authoring equivalent. A transversal competencia has no área (None)
    and belongs to the whole school, so it is allowed through."""
    if subject_id is None:
        return
    today = await tenant_today(conn, tc.tenant_id)
    assert tc.teacher_id is not None
    if not await repo.teacher_teaches_subject(conn, subject_id, tc.teacher_id, today):
        raise forbidden("not_assigned_to_subject", "you do not teach this área")


async def require_student_on_roster(
    conn: AsyncConnection, tc: TenantCtx, class_id: UUID, student_id: UUID
) -> None:
    """Being assigned to a class is not authorization to read any student id in the URL."""
    today = await tenant_today(conn, tc.tenant_id)
    if not await repo.student_on_class_roster(conn, class_id, student_id, today):
        raise forbidden("student_not_in_class", "that student is not on this class's roster")


# The id-only routes name a score, an assessment, a voice note, never the class. Each
# resolver finds the class, then the guard runs. NotFound becomes a 404 on purpose.


async def require_session_access(conn: AsyncConnection, tc: TenantCtx, session_id: UUID) -> UUID:
    class_id = await repo.class_id_for_session(conn, session_id)
    await require_class_access(conn, tc, class_id)
    return class_id


async def require_voice_note_access(conn: AsyncConnection, tc: TenantCtx, vn_id: UUID) -> None:
    await require_class_access(conn, tc, await repo.class_id_for_voice_note(conn, vn_id))


async def require_assessment_access(conn: AsyncConnection, tc: TenantCtx, a_id: UUID) -> None:
    await require_class_access(conn, tc, await repo.class_id_for_assessment(conn, a_id))


async def require_score_access(conn: AsyncConnection, tc: TenantCtx, score_id: UUID) -> None:
    await require_class_access(conn, tc, await repo.class_id_for_score(conn, score_id))


async def require_competency_access(conn: AsyncConnection, tc: TenantCtx, comp_id: UUID) -> None:
    await require_subject_access(conn, tc, await repo.subject_id_for_competency(conn, comp_id))


async def require_criterion_access(conn: AsyncConnection, tc: TenantCtx, crit_id: UUID) -> None:
    """A criterio anchored to an experience belongs to that experience's class; a global
    one belongs to its área."""
    class_id = await repo.class_id_for_criterion(conn, crit_id)
    if class_id is not None:
        await require_class_access(conn, tc, class_id)
        return
    await require_subject_access(conn, tc, await repo.subject_id_for_criterion(conn, crit_id))


async def require_experience_access(conn: AsyncConnection, tc: TenantCtx, exp_id: UUID) -> UUID:
    class_id = await repo.class_id_for_experience(conn, exp_id)
    await require_class_access(conn, tc, class_id)
    return class_id


async def require_evidence_access(conn: AsyncConnection, tc: TenantCtx, evidence_id: UUID) -> UUID:
    class_id = await repo.class_id_for_evidence(conn, evidence_id)
    await require_class_access(conn, tc, class_id)
    return class_id


async def require_planned_criterion_access(
    conn: AsyncConnection, tc: TenantCtx, crit_id: UUID
) -> UUID:
    """A global criterio is not part of any plan, so the planning routes answer 404."""
    class_id = await repo.class_id_for_criterion(conn, crit_id)
    if class_id is None:
        raise NotFound
    await require_class_access(conn, tc, class_id)
    return class_id
