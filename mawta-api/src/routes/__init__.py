"""The route table.

Deletes are POST `.../delete`, not HTTP DELETE, and there is no PATCH: the UI and the CORS
config depend on that. Path parameter names (classID, studentID…) matter because the request
log's body-capture allowlist is keyed by route pattern.
"""

from starlette.routing import Route

import web
from routes import auth as auth_routes
from routes import (
    curriculum,
    evidences,
    generations,
    notifications,
    planning,
    screens,
    sessions,
)
from web import Handler


def _teacher_routes() -> list[tuple[str, str, Handler]]:
    """(method, path under /api/v1, handler) for the teacher-only surface."""
    routes: list[tuple[str, str, Handler]] = [
        ("GET", "/home", screens.handle_home),
        ("GET", "/classes/{classID}/dashboard", screens.handle_class_dashboard),
        # The class list, and the evidence one student has in one competencia: the two reads
        # the evaluating screens are built on.
        ("GET", "/classes/{classID}/students", screens.handle_class_students),
        (
            "GET",
            "/classes/{classID}/students/{studentID}/evidence",
            screens.handle_student_evidence,
        ),
        ("POST", "/classes/{classID}/assessments", evidences.handle_create_assessment),
        ("POST", "/assessments/{assessmentID}/delete", evidences.handle_delete_assessment),
        ("POST", "/sessions/{sessionID}/start", sessions.handle_session_start),
        ("GET", "/sessions/{sessionID}", sessions.handle_session_roster),
        (
            "PUT",
            "/sessions/{sessionID}/attendance/{studentID}",
            sessions.handle_attendance_upsert,
        ),
        (
            "POST",
            "/sessions/{sessionID}/attendance/mark-all-present",
            sessions.handle_mark_all_present,
        ),
        (
            "POST",
            "/sessions/{sessionID}/students/{studentID}/voice-notes",
            sessions.handle_create_voice_note,
        ),
        ("GET", "/voice-notes/{voiceNoteID}/audio", sessions.handle_voice_note_audio),
        ("POST", "/voice-notes/{voiceNoteID}/save", sessions.handle_voice_note_save),
        ("POST", "/voice-notes/{voiceNoteID}/discard", sessions.handle_voice_note_discard),
        ("POST", "/assessments/{assessmentID}/scores", evidences.handle_create_score),
        ("POST", "/scores/{scoreID}/correct", evidences.handle_correct_score),
        # Niveles de logro: the official MINEDU record (RVM 094-2020 / 048-2024).
        (
            "GET",
            "/classes/{classID}/students/{studentID}/competencies",
            curriculum.handle_student_competencies,
        ),
        (
            "POST",
            "/classes/{classID}/students/{studentID}/competency-levels",
            curriculum.handle_assert_competency_level,
        ),
        (
            "POST",
            "/classes/{classID}/students/{studentID}/conclusions",
            curriculum.handle_upsert_conclusion,
        ),
        # Criterios de evaluación: what the teacher says to look at in a piece of work, each
        # anchored to a capacidad. Authoring only: no route here writes a nivel de logro for a
        # criterio, and none may be added.
        ("GET", "/classes/{classID}/criteria", curriculum.handle_class_criteria),
        ("GET", "/classes/{classID}/evidence-criteria", curriculum.handle_evidence_criteria),
        (
            "GET",
            "/competencies/{competencyID}/capabilities",
            curriculum.handle_competency_capabilities,
        ),
        (
            "POST",
            "/competencies/{competencyID}/capabilities",
            curriculum.handle_create_capability,
        ),
        ("POST", "/criteria/{criterionID}/delete", curriculum.handle_delete_criterion),
        # Term planning (docs/api-planificacion.md): learning experiences with their criteria,
        # planned evidences and session outline.
        ("GET", "/classes/{classID}/plan", planning.handle_class_plan),
        ("GET", "/classes/{classID}/curriculum", planning.handle_class_curriculum),
        ("GET", "/classes/{classID}/calendar", planning.handle_class_calendar),
        ("GET", "/experiences/{experienceID}", planning.handle_get_experience),
        ("POST", "/classes/{classID}/experiences", planning.handle_create_experience),
        ("PUT", "/experiences/{experienceID}", planning.handle_update_experience),
        ("POST", "/experiences/{experienceID}/confirm", planning.handle_confirm_experience),
        ("POST", "/experiences/{experienceID}/delete", planning.handle_delete_experience),
        (
            "POST",
            "/experiences/{experienceID}/criteria",
            planning.handle_create_planned_criterion,
        ),
        ("PUT", "/criteria/{criterionID}", planning.handle_update_planned_criterion),
        ("POST", "/criteria/{criterionID}/accept", planning.handle_accept_planned_criterion),
        (
            "POST",
            "/experiences/{experienceID}/evidences",
            planning.handle_create_planned_evidence,
        ),
        ("PUT", "/evidences/{evidenceID}", planning.handle_update_planned_evidence),
        ("POST", "/evidences/{evidenceID}/accept", planning.handle_accept_planned_evidence),
        ("POST", "/evidences/{evidenceID}/delete", planning.handle_delete_planned_evidence),
        ("PUT", "/experiences/{experienceID}/sessions/{date}", planning.handle_put_session_entry),
        (
            "POST",
            "/experiences/{experienceID}/sessions/{date}/accept",
            planning.handle_accept_session_entry,
        ),
        (
            "POST",
            "/experiences/{experienceID}/sessions/{date}/delete",
            planning.handle_delete_session_entry,
        ),
        # "✦ Generar con Mawta": the planning agent.
        (
            "POST",
            "/classes/{classID}/experience-proposals",
            generations.handle_create_experience_proposal,
        ),
        (
            "POST",
            "/experiences/{experienceID}/criteria/generate",
            generations.handle_generate_criteria,
        ),
        (
            "POST",
            "/experiences/{experienceID}/evidences/generate",
            generations.handle_generate_evidences,
        ),
        (
            "POST",
            "/experiences/{experienceID}/sessions/generate",
            generations.handle_generate_sessions,
        ),
        ("GET", "/generations/{generationID}", generations.handle_get_generation),
        # "✦ Generar con Mawta" for a conclusión descriptiva (docs/api-conclusiones.md).
        (
            "POST",
            "/classes/{classID}/students/{studentID}/conclusions/generate",
            generations.handle_generate_conclusion,
        ),
        (
            "GET",
            "/classes/{classID}/students/{studentID}/conclusions/generation",
            generations.handle_latest_conclusion_generation,
        ),
        ("GET", "/notifications", notifications.handle_list_notifications),
        (
            "POST",
            "/notifications/{notificationID}/read",
            notifications.handle_mark_notification_read,
        ),
        ("POST", "/notifications/read-all", notifications.handle_mark_all_notifications_read),
        ("GET", "/profile", notifications.handle_profile),
    ]
    return routes


def _route(method: str, path: str, handler: Handler) -> Route:
    return Route(path, web.handle(path, handler), methods=[method])


def build_routes() -> list[Route]:
    routes = [
        _route("GET", "/healthz", auth_routes.handle_healthz),
        # Outside any session guard by necessity: there is no session yet.
        _route("POST", "/api/v1/auth/login", auth_routes.handle_login),
        _route("POST", "/api/v1/auth/logout", auth_routes.handle_logout),
        # Open to every logged-in role; handle_me answers by role.
        _route("GET", "/api/v1/me", web.authenticate(auth_routes.handle_me)),
        # The director's token for the chat service.
        _route(
            "GET",
            "/api/v1/auth/chat-token",
            web.authenticate(web.require_director(auth_routes.handle_chat_token)),
        ),
    ]
    for method, path, handler in _teacher_routes():
        routes.append(_route(method, "/api/v1" + path, web.session_auth(handler)))
    return routes
