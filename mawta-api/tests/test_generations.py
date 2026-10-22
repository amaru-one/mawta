# ruff: noqa: F811
"""✦ Generar con Mawta.

A route records a generation and queues its job; the test then runs the job's work the way the
worker does (Runner.run) over a scripted model, and reads the outcome back through the API.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from agent import MAX_ATTEMPTS
from agent.llm import LLMError, Model, Prices, Request, Response, Usage
from agent.llm.fake import Fake, FakeReply
from agent.planning import PlanningAgent
from agent.runner import MSG_INVALID_ANSWER, MSG_RETRY_LATER, Outcome, Runner
from db import returned
from repo import agent_generations as gens
from tests.conftest import FX, Admin, Client, MakeClient, error_code
from tests.planning_helpers import PLAN_CAP_C1A, PLAN_CAP_C1B, PLAN_PERF_C1A, PLAN_PERF_C1B

# Fixtures shared with other test modules, re-exported so pytest finds them here.
from tests.test_authz import callers as callers  # noqa: F401
from tests.test_planning import Planner, want_error
from tests.test_planning import class_id as class_id  # noqa: F401
from tests.test_planning import planner as planner  # noqa: F401
from tests.test_planning import teacher as teacher  # noqa: F401


@pytest.fixture
async def agent_client(make_client: MakeClient):
    return await make_client(anthropic_api_key="test-key")


@pytest.fixture
async def gplanner(agent_client: Client, teacher: str, class_id: uuid.UUID):
    return Planner(agent_client, teacher, class_id)


def new_runner(client: Client, model: Model) -> Runner:
    api = client.app.state.api
    prices = Prices(input_per_mtok=3, output_per_mtok=15)
    return Runner(api.db, model, prices, api.logger, PlanningAgent())


async def run_job(
    runner: Runner, generation_id: Any, attempt: int = 1, max_attempts: int = 3
) -> tuple[Outcome, Exception | None]:
    return await runner.run(
        FX.tenant_a, {"generation_id": str(generation_id)}, attempt, max_attempts
    )


async def must_run(runner: Runner, generation_id: Any) -> None:
    outcome, err = await run_job(runner, generation_id, 1, MAX_ATTEMPTS)
    assert err is None and outcome == Outcome.COMPLETED, (outcome, err)


def reply(value: Any) -> FakeReply:
    return FakeReply(input=json.dumps(value), usage=Usage(input_tokens=1200, output_tokens=300))


async def request_generation(planner: Planner, path: str, body: Any = None) -> dict[str, Any]:
    resp = await planner.call("POST", path, body, 202)
    gen = resp.json()
    assert gen["status"] == "pending", gen
    return gen


async def get_generation(planner: Planner, generation_id: Any) -> dict[str, Any]:
    return (await planner.call("GET", f"/api/v1/generations/{generation_id}", want=200)).json()


async def test_generation_routes_need_the_agent(planner: Planner):
    exp = await planner.create_experience("2026-05-18", "2026-05-29", FX.competency_c1)
    body = {
        "term_id": str(FX.term_ii),
        "idea_text": "una feria",
        "competency_id": str(FX.competency_c1),
    }
    for path in (
        f"/api/v1/classes/{planner.class_id}/experience-proposals",
        f"/api/v1/experiences/{exp['id']}/criteria/generate",
        f"/api/v1/experiences/{exp['id']}/evidences/generate",
        f"/api/v1/experiences/{exp['id']}/sessions/generate",
    ):
        want_error(await planner.call("POST", path, body), 503, "agent_unavailable")


async def test_experience_proposal_from_an_idea(
    gplanner: Planner, agent_client: Client, admin: Admin
):
    p = gplanner
    await p.create_experience("2026-06-01", "2026-06-12", FX.competency_c1)

    path = f"/api/v1/classes/{p.class_id}/experience-proposals"
    body = {
        "term_id": str(FX.term_ii),
        "idea_text": "Una feria de emprendimiento donde calculen precios y ganancias",
        "competency_ids": [str(FX.competency_c1)],
    }
    gen = await request_generation(p, path, body)
    again = await request_generation(p, path, body)
    assert again["id"] == gen["id"], "a second request while one is pending returns it"

    # The model picks another competency (the teacher's choice wins) and dates that cross the
    # existing experience (the server moves them).
    model = Fake(
        replies=[
            reply(
                {
                    "title": "Feria de emprendimiento",
                    "situation_text": "La I.E. organiza una feria. ¿Cómo fijamos precios justos "
                    "y calculamos ganancias?",
                    "competency_ids": [str(FX.competency_c2)],
                    "starts_on": "2026-06-08",
                    "ends_on": "2026-06-19",
                }
            )
        ]
    )
    await must_run(new_runner(agent_client, model), gen["id"])

    sent = model.calls[0]
    assert "feria de emprendimiento" in sent.prompt and str(FX.competency_c1) in sent.prompt
    assert sent.tool.name == "proponer_experiencia"

    got = await get_generation(p, gen["id"])
    assert got["status"] == "completed", got
    proposal = got["result"]["proposal"]
    assert proposal["title"] == "Feria de emprendimiento"
    assert proposal["competency_ids"] == [str(FX.competency_c1)]
    # moved past the existing experience
    assert (proposal["starts_on"], proposal["ends_on"]) == ("2026-06-13", "2026-06-24")

    # The proposal is not an experience until the teacher saves it, and it can be saved as is.
    assert len((await p.plan(FX.term_ii))["experiences"]) == 1
    saved = {
        "term_id": str(FX.term_ii),
        "title": proposal["title"],
        "idea_text": "una feria",
        "situation_text": proposal["situation_text"],
        "starts_on": proposal["starts_on"],
        "ends_on": proposal["ends_on"],
        "competency_ids": [proposal["competency_ids"][0]],
    }
    await p.call("POST", f"/api/v1/classes/{p.class_id}/experiences", saved, 201)

    cur = await admin.execute(
        "select input_tokens + output_tokens as tokens, cost_usd from agent_generations"
        " where id = %s",
        (gen["id"],),
    )
    row = returned(await cur.fetchone())
    assert row["tokens"] == 1500 and row["cost_usd"] > 0


async def test_generate_criteria_fills_only_gaps(gplanner: Planner, agent_client: Client):
    p = gplanner
    exp = await p.create_experience("2026-05-18", "2026-05-29", FX.competency_c1)
    await p.create_criterion(exp["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)

    path = f"/api/v1/experiences/{exp['id']}/criteria/generate"
    body = {"competency_id": str(FX.competency_c1)}
    gen = await request_generation(p, path, body)

    model = Fake(
        replies=[
            reply(
                {
                    "criteria": [
                        {
                            "description": "Expresa con números enteros las ganancias y pérdidas "
                            "de la feria.",
                            "capability_ids": [str(PLAN_CAP_C1B)],
                        },
                        {
                            "description": "Traduce las ventas a expresiones numéricas.",
                            "capability_ids": [str(PLAN_CAP_C1A)],
                        },
                        {
                            "description": "Explica con sus palabras qué significa cada número "
                            "de la feria.",
                            "capability_ids": [str(PLAN_CAP_C1B)],
                        },
                    ]
                }
            )
        ]
    )
    runner = new_runner(agent_client, model)
    await must_run(runner, gen["id"])

    assert "SIN CRITERIO" in model.calls[0].prompt
    got = await get_generation(p, gen["id"])
    assert len(got["result"]["criteria_ids"]) == 1, "only the criterion filling the gap"
    e = await p.experience(exp["id"])
    proposed = next(c for c in e["criteria"] if c["id"] == got["result"]["criteria_ids"][0])
    assert proposed["proposed_by"] == "mawta" and proposed["accepted_at"] is None
    assert proposed["capability_ids"] == [str(PLAN_CAP_C1B)]

    # Every capability has a criterion now: nothing to generate, no call.
    gen2 = await request_generation(p, path, body)
    await must_run(runner, gen2["id"])
    assert model.call_count() == 1
    got2 = await get_generation(p, gen2["id"])
    assert got2["status"] == "completed" and got2["result"] == {"criteria_ids": []}

    resp = await p.call("POST", path, {"competency_id": str(FX.competency_c2)})
    want_error(resp, 422, "competency_not_in_experience")


async def test_generate_evidences_and_sessions(
    gplanner: Planner, agent_client: Client, admin: Admin
):
    from tests.test_planning import assert_placement

    p = gplanner
    exp = await p.create_experience("2026-05-18", "2026-05-29", FX.competency_c1)
    c1 = await p.create_criterion(exp["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)
    c2 = await p.create_criterion(exp["id"], FX.competency_c1, PLAN_PERF_C1B, PLAN_CAP_C1B)

    gen = await request_generation(p, f"/api/v1/experiences/{exp['id']}/evidences/generate")
    model = Fake(
        replies=[
            reply(
                {
                    "evidences": [
                        {
                            "name": "Lista de precios de la feria",
                            "kind": "produccion",
                            "criterion_ids": [c1["id"], c2["id"]],
                        },
                        {
                            "name": "Examen sorpresa",
                            "kind": "prueba_escrita",
                            "criterion_ids": [c1["id"]],
                        },
                    ]
                }
            )
        ]
    )
    runner = new_runner(agent_client, model)
    await must_run(runner, gen["id"])
    e = await p.experience(exp["id"])
    # one pending evidence over both criteria (the invalid kind is dropped)
    assert len(e["evidences"]) == 1
    assert e["evidences"][0]["proposed_by"] == "mawta" and e["evidences"][0]["accepted_at"] is None
    assert len(e["evidences"][0]["criterion_ids"]) == 2
    evidence_id = e["evidences"][0]["id"]

    # The teacher already planned 2026-05-18: the agent must not touch it.
    await p.call(
        "PUT",
        f"/api/v1/experiences/{exp['id']}/sessions/2026-05-18",
        {"title": "Presentamos la feria"},
        200,
    )

    gen = await request_generation(p, f"/api/v1/experiences/{exp['id']}/sessions/generate")
    model.replies = [
        reply(
            {
                "sessions": [
                    {"date": "2026-05-18", "title": "Otra cosa", "topics": "nada"},
                    {
                        "date": "2026-05-20",
                        "title": "¿Cuánto cuesta?",
                        "topics": "Precios y números enteros",
                    },
                    {"date": "2026-05-22", "title": "Día cancelado", "topics": "no hay clase"},
                    {
                        "date": "2026-05-25",
                        "title": "Armamos la lista de precios",
                        "topics": "Representaciones numéricas",
                        "planned_evidence_id": evidence_id,
                    },
                    {
                        "date": "2026-05-27",
                        "title": "Feria y reflexión",
                        "topics": "Ganancias y pérdidas",
                    },
                ]
            }
        )
    ]
    await must_run(runner, gen["id"])

    prompt = model.calls[1].prompt
    assert "2026-05-20 (miércoles)" in prompt and "2026-05-22" not in prompt
    got = await get_generation(p, gen["id"])
    assert got["result"] == {"session_dates": ["2026-05-20", "2026-05-25", "2026-05-27"]}
    e = await p.experience(exp["id"])
    for s in e["sessions"]:
        if s["date"] == "2026-05-18":
            assert s["title"] == "Presentamos la feria" and s["proposed_by"] == "teacher"
        else:
            assert s["proposed_by"] == "mawta" and s["accepted_at"] is None
    await assert_placement(admin, evidence_id, "2026-05-25")


class FailingModel:
    """A scripted function, for failures a Fake cannot express (like something changing while
    the model thinks)."""

    name: str = "test-model"
    fn: Callable[[Request], Awaitable[Response]]

    def __init__(self, fn: Callable[[Request], Awaitable[Response]]) -> None:
        self.fn = fn

    async def generate(self, req: Request) -> Response:
        return await self.fn(req)


async def test_generation_failures(gplanner: Planner, agent_client: Client, admin: Admin):
    p = gplanner
    exp = await p.create_experience("2026-05-18", "2026-05-29", FX.competency_c1)
    criteria_path = f"/api/v1/experiences/{exp['id']}/criteria/generate"
    criteria_body = {"competency_id": str(FX.competency_c1)}
    bad = reply({"criteria": [{"description": "Inventado", "capability_ids": [str(uuid.uuid4())]}]})

    # an invalid answer gets one repair, then fails
    gen = await request_generation(p, criteria_path, criteria_body)
    model = Fake(replies=[bad, bad])
    outcome, err = await run_job(new_runner(agent_client, model), gen["id"], 1, 3)
    assert err is None and outcome == Outcome.FAILED
    assert model.call_count() == 2 and "no se pudo usar" in model.calls[1].prompt
    got = await get_generation(p, gen["id"])
    assert got["status"] == "failed" and got["error"] == MSG_INVALID_ANSWER
    assert (await p.experience(exp["id"]))["criteria"] == []

    # a transient failure is retried, and fails on the last attempt
    gen = await request_generation(p, criteria_path, criteria_body)
    overloaded = LLMError("overloaded", permanent=False)
    model = Fake(
        replies=[FakeReply(error=overloaded), FakeReply(error=LLMError("o", permanent=False))]
    )
    runner = new_runner(agent_client, model)
    _, err = await run_job(runner, gen["id"], 1, 3)
    assert err is not None, "returned so the queue retries"
    assert (await get_generation(p, gen["id"]))["status"] == "running"
    outcome, err = await run_job(runner, gen["id"], 3, 3)
    assert err is None and outcome == Outcome.FAILED
    assert (await get_generation(p, gen["id"]))["error"] == MSG_RETRY_LATER

    # a permanent failure is not retried
    gen = await request_generation(p, criteria_path, criteria_body)
    model = Fake(replies=[FakeReply(error=LLMError("provider status 400", permanent=True))])
    outcome, err = await run_job(new_runner(agent_client, model), gen["id"], 1, 3)
    assert err is None and outcome == Outcome.FAILED

    # a generation past its deadline reads as failed and never runs
    gen = await request_generation(p, criteria_path, criteria_body)
    await admin.execute(
        "update agent_generations set deadline_at = now() - interval '1 minute' where id = %s",
        (gen["id"],),
    )
    got = await get_generation(p, gen["id"])
    assert got["status"] == "failed" and got["error"] == gens.EXPIRED_GENERATION_MESSAGE
    model = Fake()
    outcome, err = await run_job(new_runner(agent_client, model), gen["id"], 1, 3)
    assert err is None and outcome == Outcome.SKIPPED and model.call_count() == 0

    # the experience is deleted while the model thinks
    other = await p.create_experience("2026-06-01", "2026-06-12", FX.competency_c1)
    gen = await request_generation(p, f"/api/v1/experiences/{other['id']}/evidences/generate")
    await p.create_criterion(other["id"], FX.competency_c1, PLAN_PERF_C1A, PLAN_CAP_C1A)

    async def delete_then_answer(_req: Request) -> Response:
        await p.call("POST", f"/api/v1/experiences/{other['id']}/delete", want=204)
        return Response(input={"evidences": []})

    outcome, err = await run_job(
        new_runner(agent_client, FailingModel(delete_then_answer)), gen["id"], 1, 3
    )
    assert err is None and outcome == Outcome.FAILED
    assert (await get_generation(p, gen["id"]))["status"] == "failed"


async def test_generation_routes_require_an_assignment(
    gplanner: Planner, callers: tuple[str, str, str]
):  # noqa: F811
    p = gplanner
    _, rojas, flores = callers
    exp = await p.create_experience("2026-05-18", "2026-05-29", FX.competency_c1)
    gen = await request_generation(p, f"/api/v1/experiences/{exp['id']}/sessions/generate")
    routes = [
        ("POST", f"/api/v1/classes/{p.class_id}/experience-proposals", {"term_id": str(FX.term_ii), "idea_text": "una feria"}),
        ("POST", f"/api/v1/experiences/{exp['id']}/criteria/generate", {"competency_id": str(FX.competency_c1)}),
        ("POST", f"/api/v1/experiences/{exp['id']}/evidences/generate", None),
        ("POST", f"/api/v1/experiences/{exp['id']}/sessions/generate", None),
        ("GET", f"/api/v1/generations/{gen['id']}", None),
    ]  # fmt: skip
    for method, path, body in routes:
        resp = await p.client.do(rojas, method, path, body)
        assert resp.status_code == 403 and error_code(resp) == "not_assigned_to_class", path
        assert (await p.client.do(flores, method, path, body)).status_code in (403, 404), path
