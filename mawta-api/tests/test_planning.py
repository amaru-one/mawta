"""The term-planning API."""

import uuid
from datetime import date, timedelta

import pytest

from tests.conftest import FX, error_code
from tests.planning_helpers import (
    PLAN_CAP_C1A,
    PLAN_CAP_C1B,
    PLAN_COMPET_COM,
    PLAN_HOLIDAY,
    PLAN_PERF_C1_OF_4S,
    PLAN_PERF_C1A,
    PLAN_PERF_C1B,
    PLAN_PERF_C2,
    PLAN_VACATION_IN,
    PLAN_VACATION_OUT,
    admin_script,
    create_plan_class,
    criterion_body,
    drop_plan_class,
    expected_class_dates,
    experience_body,
)


@pytest.fixture
async def class_id(admin):
    cid, section = await create_plan_class(admin)
    yield cid
    await drop_plan_class(admin, cid, section)


@pytest.fixture
async def teacher(login):
    return await login(FX.user_quispe, FX.tenant_a)


class Planner:
    """The helpers around one class, so a test reads as the flow it checks."""

    def __init__(self, client, token, class_id):
        self.client, self.token, self.class_id = client, token, class_id

    async def call(self, method, path, body=None, want=None):
        resp = await self.client.do(self.token, method, path, body)
        if want is not None:
            assert resp.status_code == want, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp

    async def create_experience(self, starts_on, ends_on, *competencies):
        resp = await self.call(
            "POST",
            f"/api/v1/classes/{self.class_id}/experiences",
            experience_body(starts_on, ends_on, *competencies),
            201,
        )
        return resp.json()

    async def create_criterion(self, experience_id, competency_id, performance_id, *capabilities):
        resp = await self.call(
            "POST",
            f"/api/v1/experiences/{experience_id}/criteria",
            criterion_body(competency_id, performance_id, *capabilities),
            201,
        )
        return resp.json()

    async def experience(self, experience_id):
        return (await self.call("GET", f"/api/v1/experiences/{experience_id}", want=200)).json()

    async def plan(self, term_id):
        path = f"/api/v1/classes/{self.class_id}/plan?term_id={term_id}"
        return (await self.call("GET", path, want=200)).json()


@pytest.fixture
async def planner(client, teacher, class_id):
    return Planner(client, teacher, class_id)


def competency_status(plan, competency_id):
    return next((c for c in plan["competencies"] if c["id"] == str(competency_id)), None)


def want_error(resp, status, code):
    assert resp.status_code == status and error_code(resp) == code, (
        f"got {resp.status_code} {error_code(resp)!r} ({resp.text}), want {status} {code!r}"
    )


# ----------------------------------------------------------------- reads --


async def test_plan_reads_an_empty_term(planner):
    p = await planner.plan(FX.term_ii)
    term = p["term"]
    assert term["id"] == str(FX.term_ii)
    assert (term["starts_on"], term["ends_on"]) == ("2026-05-16", "2026-07-31")
    # Mondays and Wednesdays, the double block counted once, the cancelled Friday and the
    # non-teaching days left out.
    assert p["class_dates_total"] == len(expected_class_dates("2026-05-16", "2026-07-31"))
    # The weekly schedule meets Mondays and Wednesdays across the whole term, holidays and
    # vacations included: the timeline marks them as class slots.
    day, last, want = date(2026, 5, 16), date(2026, 7, 31), []
    while day <= last:
        if day.isoweekday() in (1, 3):
            want.append(day.isoformat())
        day += timedelta(days=1)
    assert p["scheduled_class_days"] == want

    ranges = p["non_teaching_days"]
    assert [(r["from"], r["to"], r["kind"]) for r in ranges] == [
        (PLAN_HOLIDAY, PLAN_HOLIDAY, "feriado"),
        (PLAN_VACATION_IN, PLAN_VACATION_OUT, "vacaciones"),
    ]
    assert all(r["label"] for r in ranges)
    assert p["experiences"] == []

    # Bimestre II is the last term of the fixture's year: with nothing worked, both
    # competencies need two terms and have one left.
    assert len(p["competencies"]) == 2
    for c in p["competencies"]:
        assert c["status"] == "toca" and c["terms_worked"] == []
        assert c["capabilities_covered_this_term"] == 0
    assert competency_status(p, FX.competency_c1)["capabilities_total"] == 2

    # Without term_id the plan still resolves a term of the class's year.
    default = await planner.call("GET", f"/api/v1/classes/{planner.class_id}/plan", want=200)
    assert default.json()["term"]["id"] in (str(FX.term_i), str(FX.term_ii))
    # A term of another school is not found.
    other = await planner.call(
        "GET", f"/api/v1/classes/{planner.class_id}/plan?term_id={FX.term_b}"
    )
    want_error(other, 404, "not_found")


async def test_plan_tracks_competencies_across_terms(planner):
    exp = await planner.create_experience("2026-06-01", "2026-06-30", FX.competency_c1)
    await planner.create_criterion(exp["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)

    # A borrador is still being built: it does not count as work done.
    c1 = competency_status(await planner.plan(FX.term_ii), FX.competency_c1)
    assert c1["status"] == "toca" and c1["terms_worked"] == []
    assert c1["capabilities_covered_this_term"] == 0

    # Confirming the experience makes it count.
    await planner.call("POST", f"/api/v1/experiences/{exp['id']}/confirm", want=200)
    p = await planner.plan(FX.term_ii)
    c1 = competency_status(p, FX.competency_c1)
    assert c1["status"] == "planificada" and c1["terms_worked"] == [2]
    assert c1["capabilities_covered_this_term"] == 1
    assert competency_status(p, FX.competency_c2)["status"] == "toca"
    assert len(p["experiences"]) == 1
    e = p["experiences"][0]
    assert e["id"] == exp["id"] and e["status"] == "planificada"
    assert e["class_dates"] == len(expected_class_dates("2026-06-01", "2026-06-30"))
    assert e["pending_proposals"] == 0
    assert len(e["competencies"]) == 1
    assert e["competencies"][0]["capabilities_total"] == 2
    assert e["competencies"][0]["capabilities_with_criteria"] == 1

    # Seen from Bimestre I, MAT-C1 is worked once (in II) and two terms remain: it can wait.
    # MAT-C2 still needs both remaining terms: it is due.
    p = await planner.plan(FX.term_i)
    assert competency_status(p, FX.competency_c1)["status"] == "puede_esperar"
    assert competency_status(p, FX.competency_c2)["status"] == "toca"


async def test_curriculum_of_the_class_grade(planner):
    resp = await planner.call("GET", f"/api/v1/classes/{planner.class_id}/curriculum", want=200)
    c = resp.json()
    assert c["grade"] == {"code": "5S", "cycle": "ciclo_vii", "expected_level": 7}
    assert len(c["competencies"]) == 2
    for comp in c["competencies"]:
        if comp["id"] == str(FX.competency_c1):
            # 2 capabilities and the 2 performances of 5S (not 4S's)
            assert len(comp["capabilities"]) == 2 and len(comp["performances"]) == 2
            first = comp["performances"][0]
            assert first["id"] == str(PLAN_PERF_C1A) and first["order"] == 1
            assert first["suggested_capability_id"] == str(PLAN_CAP_C1A) and first["text"]
            assert comp["standard"]["level"] == 7
        else:
            assert comp["id"] == str(FX.competency_c2)
            assert len(comp["capabilities"]) == 1 and len(comp["performances"]) == 1


async def test_calendar_of_a_class(planner):
    base = f"/api/v1/classes/{planner.class_id}/calendar"
    resp = await planner.call("GET", f"{base}?from=2026-05-18&to=2026-07-31", want=200)
    cal = resp.json()
    assert cal["class_dates"] == expected_class_dates("2026-05-18", "2026-07-31")
    days = cal["non_teaching_days"]
    assert len(days) == 6 and days[0]["date"] == PLAN_HOLIDAY and days[0]["kind"] == "feriado"

    for query in (
        "?from=2026-03-01&to=2026-12-01",  # longer than any term
        "?from=2026-06-10&to=2026-06-01",  # backwards
        "?from=junio&to=2026-06-30",  # not a date
        "",  # missing
    ):
        want_error(await planner.call("GET", base + query), 400, "bad_request")


# ---------------------------------------------------------------- writes --


async def assert_placement(admin, evidence_id, on):
    """Both sides of an evidence's placement agree; on == '' means unplaced."""
    cur = await admin.execute(
        """
        select (select to_char(se.class_date, 'YYYY-MM-DD')
                  from planned_evidences pe
                  join session_outline_entries se
                    on se.id = pe.session_entry_id and se.deleted_at is null
                 where pe.id = %(e)s) as from_evidence,
               (select string_agg(to_char(class_date, 'YYYY-MM-DD'), ',')
                  from session_outline_entries
                 where planned_evidence_id = %(e)s and deleted_at is null) as from_entries,
               (select count(*) from session_outline_entries
                 where planned_evidence_id = %(e)s and deleted_at is null) as entries
        """,
        {"e": evidence_id},
    )
    row = await cur.fetchone()
    assert (row["from_evidence"] or "") == on, row
    assert (row["from_entries"] or "") == on, row
    assert on == "" or row["entries"] == 1


def codes(warnings, code):
    return [w for w in warnings if w["code"] == code]


async def test_planning_an_experience(planner, admin):
    """The whole flow: draft, criteria, evidences, sessions, proposals, confirm, then taking
    it apart again."""
    exp = await planner.create_experience(
        "2026-06-01", "2026-06-30", FX.competency_c1, FX.competency_c2
    )
    assert exp["status"] == "borrador" and exp["class_id"] == str(planner.class_id)
    assert exp["term_id"] == str(FX.term_ii) and len(exp["competencies"]) == 2
    assert exp["situation_text"] and exp["idea_text"]
    assert exp["class_dates"] == expected_class_dates("2026-06-01", "2026-06-30")
    # Three capabilities, no criteria: one warning each.
    assert len(codes(exp["warnings"], "capability_without_criterion")) == 3
    exp_path = f"/api/v1/experiences/{exp['id']}"

    # A criterion looking at both capabilities of MAT-C1.
    crit = await planner.create_criterion(
        exp["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A, PLAN_CAP_C1B
    )
    assert crit["proposed_by"] == "teacher" and crit["accepted_at"]
    assert len(crit["capability_ids"]) == 2 and crit["performance_id"] == str(PLAN_PERF_C1A)
    assert crit["experience_id"] == exp["id"]

    # Edit it down to one capability and another performance.
    resp = await planner.call(
        "PUT",
        f"/api/v1/criteria/{crit['id']}",
        {
            "description": "Calcula el vuelto exacto",
            "capability_ids": [str(PLAN_CAP_C1B)],
            "performance_id": str(PLAN_PERF_C1B),
        },
        200,
    )
    crit = resp.json()
    assert crit["description"] == "Calcula el vuelto exacto"
    assert crit["capability_ids"] == [str(PLAN_CAP_C1B)]
    assert crit["performance_id"] == str(PLAN_PERF_C1B)

    # A planned evidence over it, not placed yet.
    resp = await planner.call(
        "POST",
        f"{exp_path}/evidences",
        {"name": "Lista de precios", "kind": "produccion", "criterion_ids": [crit["id"]]},
        201,
    )
    ev = resp.json()
    assert ev["session_date"] is None and len(ev["criterion_ids"]) == 1
    assert ev["proposed_by"] == "teacher" and ev["accepted_at"]

    # A session on 2026-06-03 that collects it: both sides of the placement move.
    resp = await planner.call(
        "PUT",
        f"{exp_path}/sessions/2026-06-03",
        {"title": "¿Qué vendemos?", "topics": "Precios y vueltos", "planned_evidence_id": ev["id"]},
        200,
    )
    ses = resp.json()
    assert ses["date"] == "2026-06-03" and ses["planned_evidence_id"] == ev["id"]
    assert ses["accepted_at"]
    await assert_placement(admin, ev["id"], "2026-06-03")

    # Unplace it from the evidence side, then place it again.
    resp = await planner.call("PUT", f"/api/v1/evidences/{ev['id']}", {"session_date": None}, 200)
    assert resp.json()["session_date"] is None
    await assert_placement(admin, ev["id"], "")
    await planner.call(
        "PUT",
        f"/api/v1/evidences/{ev['id']}",
        {"session_date": "2026-06-03", "name": "Lista de precios final"},
        200,
    )
    await assert_placement(admin, ev["id"], "2026-06-03")

    # Leaving session_date out keeps the placement.
    await planner.call("PUT", f"/api/v1/evidences/{ev['id']}", {"kind": "actuacion"}, 200)
    await assert_placement(admin, ev["id"], "2026-06-03")

    # A second session; replacing the first without an evidence empties it.
    await planner.call(
        "PUT", f"{exp_path}/sessions/2026-06-08", {"title": "Armamos la tiendita"}, 200
    )
    await planner.call(
        "PUT", f"{exp_path}/sessions/2026-06-03", {"title": "¿Qué vendemos? (v2)"}, 200
    )
    await assert_placement(admin, ev["id"], "")
    await planner.call(
        "PUT",
        f"{exp_path}/sessions/2026-06-03",
        {"title": "¿Qué vendemos?", "planned_evidence_id": ev["id"]},
        200,
    )
    # Moving the evidence to another session empties the first one.
    await planner.call(
        "PUT",
        f"{exp_path}/sessions/2026-06-08",
        {"title": "Armamos la tiendita", "planned_evidence_id": ev["id"]},
        200,
    )
    await assert_placement(admin, ev["id"], "2026-06-08")

    # Mawta's proposals, as the planning agent writes them: pending until the teacher accepts
    # or edits them. The criterion and its capability go in one transaction, as the deferred
    # check_criterion_on_write requires.
    prop_crit, prop_ev = uuid.uuid4(), uuid.uuid4()
    await admin_script(
        admin,
        """
        begin;
        insert into evaluation_criteria (id, tenant_id, competency_id, description,
                                         experience_id, performance_id, proposed_by)
        values ({{id}}, {{tenant}}, {{c2}}, 'Propuesta de Mawta', {{exp}}, {{perf}}, 'mawta');
        insert into evaluation_criterion_capabilities (tenant_id, criterion_id, competency_id,
                                                       capability_id)
        values ({{tenant}}, {{id}}, {{c2}}, {{cap}});
        commit;
        """,
        id=prop_crit,
        tenant=FX.tenant_a,
        c2=FX.competency_c2,
        exp=exp["id"],
        perf=PLAN_PERF_C2,
        cap=FX.capability_c2,
    )
    await admin.execute(
        "insert into planned_evidences (id, tenant_id, experience_id, name, kind, proposed_by)"
        " values (%s, %s, %s, 'Exposición propuesta', 'actuacion', 'mawta')",
        (prop_ev, FX.tenant_a, exp["id"]),
    )
    await admin.execute(
        "insert into session_outline_entries (tenant_id, experience_id, class_date, title,"
        " proposed_by) values (%s, %s, '2026-06-10', 'Sesión propuesta', 'mawta')",
        (FX.tenant_a, exp["id"]),
    )

    got = await planner.experience(exp["id"])
    pending = codes(got["warnings"], "pending_proposals")
    assert pending and pending[0]["count"] == 3, got["warnings"]
    # A pending proposal does not cover its capability.
    assert codes(got["warnings"], "capability_without_criterion")
    p = await planner.plan(FX.term_ii)
    assert len(p["experiences"]) == 1 and p["experiences"][0]["pending_proposals"] == 3

    # Editing a proposal accepts it; accept takes one as it is.
    resp = await planner.call(
        "PUT", f"/api/v1/criteria/{prop_crit}", {"description": "Propuesta editada"}, 200
    )
    pc = resp.json()
    assert pc["proposed_by"] == "mawta" and pc["accepted_at"]
    assert pc["description"] == "Propuesta editada"
    resp = await planner.call("POST", f"/api/v1/evidences/{prop_ev}/accept", want=200)
    assert resp.json()["accepted_at"] and resp.json()["name"] == "Exposición propuesta"
    resp = await planner.call("POST", f"{exp_path}/sessions/2026-06-10/accept", want=200)
    assert resp.json()["accepted_at"] and resp.json()["proposed_by"] == "mawta"
    await planner.call("POST", f"/api/v1/criteria/{prop_crit}/accept", want=200)  # no-op

    # Every capability now has an accepted criterion except MAT-C1-CAP1 (the first criterion
    # was edited down to CAP2).
    got = await planner.experience(exp["id"])
    uncovered = codes(got["warnings"], "capability_without_criterion")
    assert [w["capability_id"] for w in uncovered] == [str(PLAN_CAP_C1A)]
    # The one accepted evidence planned over MAT-C1 is the only one in the term so far.
    few = codes(got["warnings"], "competency_few_evidences")
    assert few and few[0]["count"] == 1

    # The experience is still a borrador: the term plan does not count its evidence.
    for c in (await planner.plan(FX.term_ii))["competencies"]:
        if c["id"] == str(FX.competency_c1):
            assert c["evidences_this_term"] == 0 and not c["in_term"] and c["evidence_kinds"] == []

    # Edit the experience itself.
    resp = await planner.call(
        "PUT",
        exp_path,
        {"title": "La tiendita", "situation_text": "", "ends_on": "2026-06-24"},
        200,
    )
    got = resp.json()
    assert got["title"] == "La tiendita" and got["situation_text"] is None
    assert got["ends_on"] == "2026-06-24"

    # Confirm.
    got = (await planner.call("POST", f"{exp_path}/confirm", want=200)).json()
    assert got["status"] == "planificada"
    assert len(codes(got["warnings"], "capability_without_criterion")) == 1

    # Once confirmed, the term plan counts the evidence and marks MAT-C1.
    for c in (await planner.plan(FX.term_ii))["competencies"]:
        if c["id"] == str(FX.competency_c1):
            assert c["evidences_this_term"] == 1 and c["in_term"]
            assert len(c["evidence_kinds"]) == 1

    # Deleting a criterion takes it out of the evidences that observe it.
    await planner.call("POST", f"/api/v1/criteria/{crit['id']}/delete", want=204)
    got = await planner.experience(exp["id"])
    assert all(crit["id"] not in e["criterion_ids"] for e in got["evidences"])

    # Deleting a session leaves its evidence unplaced; deleting an evidence empties its session.
    await planner.call("POST", f"{exp_path}/sessions/2026-06-08/delete", want=204)
    await assert_placement(admin, ev["id"], "")
    await planner.call(
        "PUT",
        f"{exp_path}/sessions/2026-06-03",
        {"title": "¿Qué vendemos?", "planned_evidence_id": ev["id"]},
        200,
    )
    await planner.call("POST", f"/api/v1/evidences/{ev['id']}/delete", want=204)
    got = await planner.experience(exp["id"])
    assert all(s["planned_evidence_id"] != ev["id"] for s in got["sessions"])
    want_error(
        await planner.call("POST", f"{exp_path}/sessions/2026-06-08/delete"), 404, "not_found"
    )
    want_error(await planner.call("POST", f"/api/v1/evidences/{ev['id']}/accept"), 404, "not_found")

    # Deleting the experience takes everything with it and frees its dates.
    await planner.call("POST", f"{exp_path}/delete", want=204)
    want_error(await planner.call("GET", exp_path), 404, "not_found")
    cur = await admin.execute(
        """
        select (select count(*) from evaluation_criteria
                 where experience_id = %(e)s and deleted_at is null)
             + (select count(*) from planned_evidences
                 where experience_id = %(e)s and deleted_at is null)
             + (select count(*) from session_outline_entries
                 where experience_id = %(e)s and deleted_at is null)
             + (select count(*) from experience_competencies
                 where experience_id = %(e)s and deleted_at is null) as live
        """,
        {"e": exp["id"]},
    )
    assert (await cur.fetchone())["live"] == 0
    assert (await planner.plan(FX.term_ii))["experiences"] == []
    await planner.create_experience("2026-06-01", "2026-06-30", FX.competency_c1)


async def test_planning_domain_errors(planner):
    """Each stable code of the contract's "Domain errors" table."""
    class_path = f"/api/v1/classes/{planner.class_id}/experiences"
    a = await planner.create_experience("2026-06-01", "2026-06-12", FX.competency_c1)
    b = await planner.create_experience(
        "2026-06-15", "2026-06-30", FX.competency_c1, FX.competency_c2
    )
    a_path, b_path = f"/api/v1/experiences/{a['id']}", f"/api/v1/experiences/{b['id']}"
    crit_a = await planner.create_criterion(a["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)
    await planner.call("PUT", f"{a_path}/sessions/2026-06-03", {"title": "Inicio"}, 200)
    crit_b = await planner.create_criterion(
        b["id"], FX.competency_c2, PLAN_PERF_C2, FX.capability_c2
    )
    ev_b = (
        await planner.call(
            "POST",
            f"{b_path}/evidences",
            {"name": "Otra", "kind": "actuacion", "criterion_ids": [crit_b["id"]]},
            201,
        )
    ).json()

    def body(starts, ends, *competencies):
        return experience_body(starts, ends, *competencies)

    cases = [
        ("overlapping dates", "POST", class_path, body("2026-06-10", "2026-06-20", FX.competency_c1), 409, "experience_overlap"),
        ("moving into another experience", "PUT", a_path, {"ends_on": "2026-06-16"}, 409, "experience_overlap"),
        ("ending after the term", "POST", class_path, body("2026-07-27", "2026-08-07", FX.competency_c1), 422, "outside_term"),
        ("starting before the term", "PUT", a_path, {"starts_on": "2026-05-10"}, 422, "outside_term"),
        ("another área's competency", "POST", class_path, body("2026-07-01", "2026-07-10", PLAN_COMPET_COM), 422, "competency_not_in_subject"),
        ("adding another área's competency", "PUT", a_path, {"competency_ids": [str(FX.competency_c1), str(PLAN_COMPET_COM)]}, 422, "competency_not_in_subject"),
        ("removing a competency with criteria", "PUT", a_path, {"competency_ids": [str(FX.competency_c2)]}, 409, "competency_has_criteria"),
        ("a capability of another competency", "POST", f"{a_path}/criteria", criterion_body(FX.competency_c1, PLAN_PERF_C1A, FX.capability_c2), 422, "capability_not_in_competency"),
        ("editing to a capability of another competency", "PUT", f"/api/v1/criteria/{crit_a['id']}", {"capability_ids": [str(FX.capability_c2)]}, 422, "capability_not_in_competency"),
        ("a criterion without capabilities", "POST", f"{a_path}/criteria", criterion_body(FX.competency_c1, PLAN_PERF_C1A), 422, "criterion_needs_capability"),
        ("editing away every capability", "PUT", f"/api/v1/criteria/{crit_a['id']}", {"capability_ids": []}, 422, "criterion_needs_capability"),
        ("a performance of another grade", "POST", f"{a_path}/criteria", criterion_body(FX.competency_c1, PLAN_PERF_C1_OF_4S, PLAN_CAP_C1A), 422, "performance_not_in_grade"),
        ("a performance of another competency", "PUT", f"/api/v1/criteria/{crit_a['id']}", {"performance_id": str(PLAN_PERF_C2)}, 422, "performance_not_in_grade"),
        ("a competency the experience does not work", "POST", f"{a_path}/criteria", criterion_body(FX.competency_c2, PLAN_PERF_C2, FX.capability_c2), 422, "competency_not_in_experience"),
        ("a criterion of another área's competency", "POST", f"{a_path}/criteria", criterion_body(PLAN_COMPET_COM, PLAN_PERF_C2, FX.capability_c2), 422, "competency_not_in_subject"),
        ("an evidence over another experience's criterion", "POST", f"{b_path}/evidences", {"name": "Cruzada", "kind": "produccion", "criterion_ids": [crit_a["id"]]}, 422, "criterion_other_experience"),
        ("re-pointing an evidence at another experience's criterion", "PUT", f"/api/v1/evidences/{ev_b['id']}", {"criterion_ids": [crit_a["id"]]}, 422, "criterion_other_experience"),
        ("an evidence in a date without a session", "POST", f"{a_path}/evidences", {"name": "Sin sesión", "kind": "produccion", "criterion_ids": [crit_a["id"]], "session_date": "2026-06-08"}, 422, "date_not_in_experience"),
        ("moving an evidence to a date without a session", "PUT", f"/api/v1/evidences/{ev_b['id']}", {"session_date": "2026-06-17"}, 422, "date_not_in_experience"),
        ("a session on a holiday", "PUT", f"{b_path}/sessions/{PLAN_HOLIDAY}", {"title": "Feriado"}, 422, "date_not_in_experience"),
        ("a session on a day without class", "PUT", f"{a_path}/sessions/2026-06-02", {"title": "Martes"}, 422, "date_not_in_experience"),
        ("a session outside the experience", "PUT", f"{a_path}/sessions/2026-06-15", {"title": "De la otra"}, 422, "date_not_in_experience"),
        ("shrinking the dates past a session", "PUT", a_path, {"starts_on": "2026-06-08"}, 422, "date_not_in_experience"),
        ("a session holding another experience's evidence", "PUT", f"{a_path}/sessions/2026-06-03", {"title": "Inicio", "planned_evidence_id": ev_b["id"]}, 422, "evidence_not_in_experience"),
        ("a criterion without a description", "POST", f"{a_path}/criteria", {"competency_id": str(FX.competency_c1), "description": "  ", "capability_ids": [str(PLAN_CAP_C1A)], "performance_id": str(PLAN_PERF_C1A)}, 400, "missing_description"),
        ("an experience without competencies", "POST", class_path, body("2026-07-01", "2026-07-10"), 400, "missing_competencies"),
        ("an evidence of an unknown kind", "POST", f"{a_path}/evidences", {"name": "Rara", "kind": "prueba_escrita", "criterion_ids": [crit_a["id"]]}, 400, "bad_request"),
        ("an evidence without criteria", "POST", f"{a_path}/evidences", {"name": "Sola", "kind": "produccion", "criterion_ids": []}, 400, "missing_criteria"),
        ("a term of another year", "POST", class_path, {**body("2026-07-01", "2026-07-10", FX.competency_c1), "term_id": str(FX.term_b)}, 404, "not_found"),
        ("a global criterion through the planning routes", "PUT", f"/api/v1/criteria/{FX.criterion_one}", {"description": "x"}, 404, "not_found"),
        ("accepting a session that does not exist", "POST", f"{a_path}/sessions/2026-06-10/accept", None, 404, "not_found"),
    ]  # fmt: skip
    for name, method, path, payload, status, code in cases:
        resp = await planner.call(method, path, payload)
        assert resp.status_code == status and error_code(resp) == code, (
            f"{name}: got {resp.status_code} {error_code(resp)!r} ({resp.text}), "
            f"want {status} {code!r}"
        )

    # Confirming twice.
    await planner.call("POST", f"{a_path}/confirm", want=200)
    want_error(await planner.call("POST", f"{a_path}/confirm"), 409, "experience_not_draft")

    # Nothing above changed experience A behind the rejections.
    got = await planner.experience(a["id"])
    assert (got["starts_on"], got["ends_on"]) == ("2026-06-01", "2026-06-12")
    assert len(got["competencies"]) == 1 and len(got["criteria"]) == 1
    assert len(got["criteria"][0]["capability_ids"]) == 1 and len(got["sessions"]) == 1


async def enrol_student(admin, class_id) -> uuid.UUID:
    student = uuid.uuid4()
    await admin_script(
        admin,
        """
        insert into students (id, tenant_id, student_code, given_name, paternal_surname, status)
        values ({{student}}, {{tenant}}, 'EST-' || left({{student}}::text, 8), 'Lola', 'Lopez',
                'active');
        insert into section_memberships (tenant_id, academic_year_id, section_id, student_id,
                                         joined_on)
        select {{tenant}}, academic_year_id, section_id, {{student}}, '2026-03-01'
          from classes where id = {{class}};
        """,
        tenant=FX.tenant_a,
        student=student,
        **{"class": class_id},
    )
    return student


@pytest.fixture
async def student(admin, class_id):
    sid = await enrol_student(admin, class_id)
    yield sid
    await admin.execute("delete from section_memberships where student_id = %s", (sid,))
    await admin.execute("delete from students where id = %s", (sid,))


async def test_confirmed_experience_reaches_calendar_and_students(planner, admin, student):
    """The bridge between the plan and the classroom: what the teacher planned names the class
    sessions of the calendar, and each planned evidence is an assessment the roster can be
    evaluated on."""
    fx = FX
    exp = await planner.create_experience("2026-06-01", "2026-06-30", fx.competency_c1)
    exp_path = f"/api/v1/experiences/{exp['id']}"
    crit = await planner.create_criterion(exp["id"], fx.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)
    ev = (
        await planner.call(
            "POST",
            f"{exp_path}/evidences",
            {"name": "Lista de precios", "kind": "produccion", "criterion_ids": [crit["id"]]},
            201,
        )
    ).json()
    await planner.call(
        "PUT",
        f"{exp_path}/sessions/2026-06-03",
        {"title": "¿Qué vendemos?", "planned_evidence_id": ev["id"]},
        200,
    )

    async def topic(on):
        cur = await admin.execute(
            "select topic from class_sessions where class_id = %s and session_date = %s"
            " and status <> 'cancelled'",
            (planner.class_id, on),
        )
        return (await cur.fetchone())["topic"]

    async def assessments():
        cur = await admin.execute(
            "select count(*) as n from assessments a join planned_evidences pe"
            " on pe.id = a.planned_evidence_id where pe.experience_id = %s"
            " and a.deleted_at is null",
            (exp["id"],),
        )
        return (await cur.fetchone())["n"]

    # A draft promises, it does not reach the classroom yet.
    assert await topic("2026-06-03") is None and await assessments() == 0

    await planner.call("POST", f"{exp_path}/confirm", want=200)
    assert await topic("2026-06-03") == "¿Qué vendemos?"
    assert await assessments() == 1
    cur = await admin.execute(
        "select a.title, a.kind, a.value_scale, a.session_id,"
        " (select count(*) from assessment_criteria ac where ac.assessment_id = a.id"
        "   and ac.criterion_id = %s and ac.deleted_at is null) as criteria"
        " from assessments a where a.planned_evidence_id = %s and a.deleted_at is null",
        (crit["id"], ev["id"]),
    )
    row = await cur.fetchone()
    assert (row["title"], row["kind"], row["value_scale"]) == (
        "Lista de precios",
        "produccion",
        "numeric",
    )
    assert row["session_id"] is not None and row["criteria"] == 1

    # The student sees it, tagged with the criterion, ready to be evaluated.
    path = f"/api/v1/classes/{planner.class_id}/students/{student}/evidence?term_id={fx.term_ii}"
    got = (await planner.call("GET", path, want=200)).json()["evidence"]
    assert len(got) == 1 and got[0]["title"] == "Lista de precios" and len(got[0]["criteria"]) == 1

    # The screens do not send term_id: they read the class's current term, and the planned
    # evidence must be in it.
    for tail in ("students", f"students/{student}/evidence"):
        resp = await planner.call("GET", f"/api/v1/classes/{planner.class_id}/{tail}", want=200)
        assert "Lista de precios" in resp.text or '"evidence_count":1' in resp.text

    # Edits after confirming flow through, and syncing again changes nothing.
    await planner.call(
        "PUT",
        f"/api/v1/evidences/{ev['id']}",
        {"name": "Lista de precios final", "kind": "actuacion"},
        200,
    )
    await planner.call(
        "PUT", f"{exp_path}/sessions/2026-06-03", {"title": "Precios y vueltos"}, 200
    )
    await planner.plan(fx.term_ii)
    assert await assessments() == 1
    assert await topic("2026-06-03") == "Precios y vueltos"
    cur = await admin.execute(
        "select title, kind, session_id from assessments"
        " where planned_evidence_id = %s and deleted_at is null",
        (ev["id"],),
    )
    row = await cur.fetchone()
    # renamed, actuacion, unplaced (the session entry no longer holds the evidence)
    assert (row["title"], row["kind"], row["session_id"]) == (
        "Lista de precios final",
        "actuacion",
        None,
    )

    # Deleting the evidence takes the assessment off the students' screens.
    await planner.call("POST", f"/api/v1/evidences/{ev['id']}/delete", want=204)
    assert await assessments() == 0
    await planner.call("POST", f"{exp_path}/sessions/2026-06-03/delete", want=204)
    assert await topic("2026-06-03") is None


async def test_level_screen_carries_the_expected_standard_of_the_cycle(planner, student):
    """The nivel de logro is judged against the standard of the cycle's expected level (CNEB),
    so the registration screen returns it with every competency."""
    path = f"/api/v1/classes/{planner.class_id}/students/{student}/competencies"
    comps = {
        c["competency_id"]: c
        for c in (await planner.call("GET", path, want=200)).json()["competencies"]
    }
    std = comps[str(FX.competency_c1)]["standard"]
    assert std == {
        "level": 7,
        "cycle": "ciclo_vii",
        "text": "Resuelve problemas referidos a las relaciones entre cantidades.",
    }
    assert comps[str(FX.competency_c2)]["standard"]["level"] == 7


async def test_students_without_an_active_term_read_the_latest_closed_one(planner, admin, student):
    """With no active term (between two terms) the screens still show the class's evidence:
    they fall back to the latest closed term, read-only."""
    await admin_script(
        admin,
        """
        insert into assessments (tenant_id, class_id, term_id, title, kind, value_scale,
                                 max_score, status, published_at)
        values ({{tenant}}, {{class}}, {{term}}, 'Evidencia del bimestre', 'produccion',
                'numeric', 20, 'published', now());
        """,
        tenant=FX.tenant_a,
        term=FX.term_ii,
        **{"class": planner.class_id},
    )

    async def count():
        resp = await planner.call("GET", f"/api/v1/classes/{planner.class_id}/students", want=200)
        mine = [s for s in resp.json()["students"] if s["student_id"] == str(student)]
        assert mine, resp.text
        return mine[0]["evidence_count"]

    try:
        assert await count() == 1
        # Close the term and leave nobody active; restore it afterwards.
        await admin.execute(
            "update terms set status = 'closed', closed_at = now() where id = %s", (FX.term_ii,)
        )
        assert await count() == 1  # the latest closed term
    finally:
        await admin.execute(
            "update terms set status = 'active', closed_at = null where id = %s", (FX.term_ii,)
        )
        await admin.execute(
            "delete from assessments where class_id = %s and title = 'Evidencia del bimestre'",
            (planner.class_id,),
        )


async def test_explicit_term_of_another_year_is_not_found(planner, admin):
    """An explicit term_id must be a term of the class: a period of another year is a 404 on
    reads and on creating an assessment, never an empty screen."""
    year, term = uuid.uuid4(), uuid.uuid4()
    await admin_script(
        admin,
        """
        insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure,
                                    status)
        values ({{year}}, {{tenant}}, 2031, '2031', '2031-03-01', '2031-12-18', 'bimestre',
                'planned');
        insert into terms (id, tenant_id, academic_year_id, sequence, name, starts_on, ends_on,
                           status)
        values ({{term}}, {{tenant}}, {{year}}, 1, 'Bimestre 2031', '2031-03-01', '2031-05-15',
                'planned');
        """,
        year=year,
        term=term,
        tenant=FX.tenant_a,
    )
    try:
        base = f"/api/v1/classes/{planner.class_id}"
        want_error(await planner.call("GET", f"{base}/students?term_id={term}"), 404, "not_found")
        want_error(await planner.call("GET", f"{base}/dashboard?term_id={term}"), 404, "not_found")
        resp = await planner.call(
            "POST",
            f"{base}/assessments",
            {
                "title": "x",
                "kind": "produccion",
                "value_scale": "ordinal",
                "criterion_ids": [str(FX.criterion_one)],
                "term_id": str(term),
            },
        )
        want_error(resp, 404, "not_found")
        # A term of the class's own year still works.
        await planner.call("GET", f"{base}/students?term_id={FX.term_ii}", want=200)
    finally:
        await admin.execute("delete from terms where id = %s", (term,))
        await admin.execute("delete from academic_years where id = %s", (year,))


async def test_planned_evidence_scale(planner):
    """A planned evidence says how it will be valued: a mark out of a maximum the teacher chooses
    (20 when none is named), or an AD/A/B/C level. The two never mix."""
    exp = await planner.create_experience("2026-06-01", "2026-06-30", FX.competency_c1)
    exp_path = f"/api/v1/experiences/{exp['id']}"
    crit = await planner.create_criterion(exp["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)

    async def create(**extra):
        body = {"name": "Evidencia", "kind": "produccion", "criterion_ids": [crit["id"]], **extra}
        return (await planner.call("POST", f"{exp_path}/evidences", body, 201)).json()

    ev = await create()
    assert (ev["value_scale"], ev["max_score"]) == ("numeric", 20)
    ev = await create(max_score=18)
    assert (ev["value_scale"], ev["max_score"]) == ("numeric", 18)
    ev = await create(value_scale="ordinal")
    assert (ev["value_scale"], ev["max_score"]) == ("ordinal", None)

    for extra in (
        {"value_scale": "ordinal", "max_score": 10},  # a level with a maximum
        {"max_score": 0},  # a zero maximum
        {"value_scale": "porcentaje"},  # an unknown scale
    ):
        body = {"name": "X", "kind": "produccion", "criterion_ids": [crit["id"]], **extra}
        want_error(await planner.call("POST", f"{exp_path}/evidences", body), 400, "bad_request")

    # Switching an evidence to a level drops the maximum that belonged to the old scale; a lone
    # maximum on a level is refused.
    ev_path = f"/api/v1/evidences/{ev['id']}"
    ev = (
        await planner.call("PUT", ev_path, {"value_scale": "numeric", "max_score": 12}, 200)
    ).json()
    assert (ev["value_scale"], ev["max_score"]) == ("numeric", 12)
    ev = (await planner.call("PUT", ev_path, {"value_scale": "ordinal"}, 200)).json()
    assert (ev["value_scale"], ev["max_score"]) == ("ordinal", None)
    want_error(await planner.call("PUT", ev_path, {"max_score": 9}), 400, "bad_request")


async def test_evidence_criteria_come_from_planned_experiences(planner, admin):
    """ "Añadir evidencia" offers the criterios of the class's planned experiencias in the term,
    and only those (RVM 094-2020, 5.1.1.1: a criterio is written for a situation)."""
    fx = FX
    try:
        draft = await planner.create_experience("2026-06-01", "2026-06-12", fx.competency_c1)
        crit_draft = await planner.create_criterion(
            draft["id"], fx.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A
        )
        planned = await planner.create_experience("2026-06-15", "2026-06-30", fx.competency_c1)
        planned_path = f"/api/v1/experiences/{planned['id']}"
        crit_planned = await planner.create_criterion(
            planned["id"], fx.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A
        )
        ev = (
            await planner.call(
                "POST",
                f"{planned_path}/evidences",
                {
                    "name": "Lista de precios",
                    "kind": "produccion",
                    "criterion_ids": [crit_planned["id"]],
                },
                201,
            )
        ).json()
        await planner.call(
            "PUT",
            f"{planned_path}/sessions/2026-06-17",
            {"title": "¿Qué vendemos?", "planned_evidence_id": ev["id"]},
            200,
        )
        await planner.call("POST", f"{planned_path}/confirm", want=200)

        async def read(path):
            resp = await planner.call("GET", path, want=200)
            return {
                cr["criterion_id"]: cr
                for comp in resp.json()["competencies"]
                for cr in comp["criteria"]
            }

        offered = await read(
            f"/api/v1/classes/{planner.class_id}/evidence-criteria?term_id={fx.term_ii}"
        )
        cr = offered.get(crit_planned["id"])
        assert cr and cr["experience_id"] == planned["id"]
        assert cr["experience_title"] == planned["title"]
        assert crit_draft["id"] not in offered  # a draft's criterio
        assert str(fx.criterion_one) not in offered  # a general criterio
        assert len(offered) == 1

        # The área's list keeps the general criterios and nothing of an experiencia.
        general = await read(f"/api/v1/classes/{fx.class_mat_5b}/criteria")
        assert crit_planned["id"] not in general
        assert str(fx.criterion_one) in general

        async def file(class_id, criterion_id):
            return await planner.call(
                "POST",
                f"/api/v1/classes/{class_id}/assessments",
                {
                    "title": "T-crit-x",
                    "kind": "actuacion",
                    "term_id": str(fx.term_ii),
                    "value_scale": "ordinal",
                    "criterion_ids": [criterion_id],
                },
            )

        assert (await file(planner.class_id, crit_planned["id"])).status_code == 201
        want_error(await file(planner.class_id, crit_draft["id"]), 400, "criterion_not_in_class")
        want_error(await file(fx.class_mat_5b, crit_planned["id"]), 400, "criterion_not_in_class")
    finally:
        await admin.execute(
            "delete from assessment_criteria where assessment_id in"
            " (select id from assessments where title like 'T-crit-%')"
        )
        await admin.execute("delete from assessments where title like 'T-crit-%'")
