"""The whole path of valuing one piece of evidence."""

import math

import pytest

from tests.conftest import FX, error_code

CLASS = str(FX.class_mat_5b)
STUDENT = str(FX.students[2])


@pytest.fixture
async def teacher(login):
    return await login(FX.user_quispe, FX.tenant_a)


@pytest.fixture(autouse=True)
async def clean(admin):
    yield
    for sql in (
        "delete from scores where assessment_id in"
        " (select id from assessments where title like 'T-eval-%')",
        "delete from assessment_criteria where assessment_id in"
        " (select id from assessments where title like 'T-eval-%')",
        "delete from assessments where title like 'T-eval-%'",
    ):
        await admin.execute(sql)


async def file_evidence(client, token, **fields):
    body = {
        "kind": "produccion",
        "term_id": str(FX.term_ii),
        "criterion_ids": [str(FX.criterion_one)],
    }
    body.update(fields)
    resp = await client.do(token, "POST", f"/api/v1/classes/{CLASS}/assessments", body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def read_entry(client, token, assessment_id):
    resp = await client.do(
        token,
        "GET",
        f"/api/v1/classes/{CLASS}/students/{STUDENT}/evidence?term_id={FX.term_ii}",
    )
    assert resp.status_code == 200, resp.text
    for entry in resp.json()["evidence"]:
        if entry["assessment_id"] == assessment_id:
            return entry
    raise AssertionError(f"evidence {assessment_id} is not in the student's list")


async def test_numeric_evidence_shows_a_percentage(client, teacher):
    eid = await file_evidence(
        client, teacher, title="T-eval-num", value_scale="numeric", max_score=18
    )
    entry = await read_entry(client, teacher, eid)
    assert entry["score"] is None and entry["max_score"] == 18
    resp = await client.do(
        teacher,
        "POST",
        f"/api/v1/assessments/{eid}/scores",
        {"student_id": STUDENT, "raw_value": 14},
    )
    assert resp.status_code == 201, resp.text
    entry = await read_entry(client, teacher, eid)
    assert entry["score"]["raw_value"] == 14
    assert math.isclose(entry["score"]["percentage"], 77.7778, abs_tol=0.01)
    assert entry["score"]["level"] is None
    assert entry["criteria"][0]["criterion_id"] == str(FX.criterion_one)


async def test_ordinal_evidence_takes_a_level_and_a_correction_replaces_it(client, teacher):
    eid = await file_evidence(client, teacher, title="T-eval-ord", value_scale="ordinal")
    resp = await client.do(
        teacher, "POST", f"/api/v1/assessments/{eid}/scores", {"student_id": STUDENT, "level": "B"}
    )
    assert resp.status_code == 201, resp.text
    score_id = resp.json()["id"]
    entry = await read_entry(client, teacher, eid)
    assert entry["score"]["level"] == "B" and entry["score"]["raw_value"] is None
    fixed = await client.do(teacher, "POST", f"/api/v1/scores/{score_id}/correct", {"level": "AD"})
    assert fixed.status_code == 201, fixed.text
    assert (await read_entry(client, teacher, eid))["score"]["level"] == "AD"
    again = await client.do(teacher, "POST", f"/api/v1/scores/{score_id}/correct", {"level": "A"})
    assert again.status_code == 409 and error_code(again) == "already_superseded"


async def test_a_value_of_the_wrong_kind_is_refused(client, teacher):
    num = await file_evidence(
        client, teacher, title="T-eval-num2", value_scale="numeric", max_score=10
    )
    ord_ = await file_evidence(client, teacher, title="T-eval-ord2", value_scale="ordinal")
    for aid, body, code in (
        (num, {"level": "A"}, "level_on_numeric"),
        (ord_, {"raw_value": 3}, "mark_on_ordinal"),
        (num, {"raw_value": 11}, "mark_out_of_range"),
    ):
        resp = await client.do(
            teacher, "POST", f"/api/v1/assessments/{aid}/scores", {"student_id": STUDENT, **body}
        )
        assert resp.status_code == 400 and error_code(resp) == code, resp.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": ""},
        {"kind": "examen"},
        {"kind": "prueba_escrita"},
        {"criterion_ids": []},
        {"value_scale": "ordinal", "max_score": 20},
        {"value_scale": "numeric", "max_score": None},
    ],
)
async def test_an_evidence_needs_a_kind_a_criterio_and_a_coherent_scale(client, teacher, overrides):
    body = {
        "title": "T-eval-x",
        "kind": "produccion",
        "term_id": str(FX.term_ii),
        "value_scale": "numeric",
        "max_score": 20,
        "criterion_ids": [str(FX.criterion_one)],
        **overrides,
    }
    resp = await client.do(teacher, "POST", f"/api/v1/classes/{CLASS}/assessments", body)
    assert resp.status_code == 400 and error_code(resp) == "bad_request", resp.text


async def test_wrong_json_type_is_a_bad_request(client, teacher):
    resp = await client.do(
        teacher, "POST", f"/api/v1/classes/{CLASS}/assessments", {"title": 5, "kind": "produccion"}
    )
    assert resp.status_code == 400 and error_code(resp) == "bad_request"
