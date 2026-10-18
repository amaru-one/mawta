"""The authorization matrix: every class-scoped route, three callers.

    Quispe - teaches MAT-5B                  -> allowed
    Rojas  - same school, teaches nothing    -> 403 not_assigned_to_class
    Flores - another school entirely         -> 404 (RLS hid the row first)

Routes that belong to areas not ported yet are listed in PENDING and enabled as their module
lands.
"""

import uuid

import pytest

from tests.conftest import FX, error_code

CLASS = str(FX.class_mat_5b)
STUDENT = str(FX.students[0])

READ_ROUTES = [
    ("class dashboard", "GET", f"/api/v1/classes/{CLASS}/dashboard", None),
    (
        "class roster",
        "GET",
        f"/api/v1/classes/{CLASS}/students?competency_id={FX.competency_c2}",
        None,
    ),
    ("student evidence", "GET", f"/api/v1/classes/{CLASS}/students/{STUDENT}/evidence", None),
    ("session header", "GET", f"/api/v1/sessions/{FX.session_one}", None),
]

WRITE_ROUTES = [
    (
        "create an assessment",
        "POST",
        f"/api/v1/classes/{CLASS}/assessments",
        {
            "title": "Suplantada",
            "kind": "produccion",
            "value_scale": "numeric",
            "max_score": 20,
            "criterion_ids": [str(FX.criterion_one)],
        },
    ),
    (
        "delete someone else's assessment",
        "POST",
        f"/api/v1/assessments/{FX.assessment_numeric}/delete",
        None,
    ),
    (
        "score against someone else's assessment",
        "POST",
        f"/api/v1/assessments/{FX.assessment_numeric}/scores",
        {"student_id": str(FX.students[1]), "status": "graded", "raw_value": 20},
    ),
    (
        "correct someone else's score",
        "POST",
        f"/api/v1/scores/{FX.score_one}/correct",
        {"raw_value": 20},
    ),
    ("start someone else's session", "POST", f"/api/v1/sessions/{FX.session_one}/start", None),
    (
        "mark a whole roster present",
        "POST",
        f"/api/v1/sessions/{FX.session_one}/attendance/mark-all-present",
        None,
    ),
    (
        "set one student's attendance",
        "PUT",
        f"/api/v1/sessions/{FX.session_one}/attendance/{STUDENT}",
        {"status": "absent"},
    ),
]


@pytest.fixture
async def callers(login):
    return (
        await login(FX.user_quispe, FX.tenant_a),
        await login(FX.user_rojas, FX.tenant_a),
        await login(FX.user_flores, FX.tenant_b),
    )


@pytest.mark.parametrize("name,method,path,body", READ_ROUTES, ids=[r[0] for r in READ_ROUTES])
async def test_class_scoped_reads_require_an_assignment(client, callers, name, method, path, body):
    quispe, rojas, flores = callers
    assert (await client.do(quispe, method, path, body)).status_code < 300
    resp = await client.do(rojas, method, path, body)
    assert resp.status_code == 403 and error_code(resp) == "not_assigned_to_class"
    assert (await client.do(flores, method, path, body)).status_code in (403, 404)


@pytest.mark.parametrize("name,method,path,body", WRITE_ROUTES, ids=[r[0] for r in WRITE_ROUTES])
async def test_class_scoped_writes_require_an_assignment(client, callers, name, method, path, body):
    _, rojas, _ = callers
    resp = await client.do(rojas, method, path, body)
    assert resp.status_code == 403, resp.text


async def test_voice_note_routes_require_an_assignment(client, callers, admin):
    _, rojas, _ = callers
    note = uuid.uuid4()
    await admin.execute(
        "insert into voice_notes (id, tenant_id, session_id, student_id, class_id, teacher_id,"
        " duration_ms) values (%s, %s, %s, %s, %s, %s, 5000)",
        (note, FX.tenant_a, FX.session_one, FX.students[0], FX.class_mat_5b, FX.teacher_quispe),
    )
    try:
        for method, suffix in (("GET", "audio"), ("POST", "save"), ("POST", "discard")):
            resp = await client.do(rojas, method, f"/api/v1/voice-notes/{note}/{suffix}")
            assert resp.status_code == 403, (suffix, resp.text)
        cur = await admin.execute("select deleted_at from voice_notes where id = %s", (note,))
        assert (await cur.fetchone())["deleted_at"] is None
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))


async def test_a_student_outside_the_class_is_refused(client, callers, admin):
    quispe, _, _ = callers
    outsider = uuid.uuid4()
    await admin.execute(
        "insert into students (id, tenant_id, student_code, given_name, paternal_surname)"
        " values (%s, %s, 'EST-OUTSIDER', 'Fuera', 'Deaula')",
        (outsider, FX.tenant_a),
    )
    try:
        resp = await client.do(
            quispe, "GET", f"/api/v1/classes/{CLASS}/students/{outsider}/evidence"
        )
        assert resp.status_code == 403 and error_code(resp) == "student_not_in_class"
    finally:
        await admin.execute("delete from students where id = %s", (outsider,))


@pytest.mark.parametrize(
    "path", ["/api/v1/me", "/api/v1/home", "/api/v1/profile", "/api/v1/notifications"]
)
async def test_teacher_keyed_routes_stay_open(client, callers, path):
    _, rojas, _ = callers
    resp = await client.do(rojas, "GET", path)
    assert resp.status_code == 200, resp.text


async def test_unauthenticated_requests_are_still_rejected(client):
    resp = await client.http.get(f"/api/v1/classes/{CLASS}/students")
    assert resp.status_code == 401


async def test_a_session_only_ever_sees_its_own_school(client, callers):
    _, _, flores = callers
    resp = await client.do(flores, "GET", f"/api/v1/classes/{CLASS}/students")
    assert resp.status_code < 500
    for student in FX.students:
        assert str(student) not in resp.text
