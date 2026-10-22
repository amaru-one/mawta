"""Chats belong to one director in one school."""

import httpx

from tests.conftest import (
    TENANT_A,
    TENANT_B,
    USER_FLORES,
    USER_QUISPE,
    USER_ROJAS,
    MakeToken,
    bearer,
)


async def test_requests_without_a_valid_token_are_refused(
    client: httpx.AsyncClient, make_token: MakeToken
):
    assert (await client.get("/threads")).status_code == 401
    teacher = make_token(USER_QUISPE, TENANT_A, role="teacher")
    response = await client.get("/threads", headers=bearer(teacher))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_a_director_creates_renames_and_deletes_a_chat(
    client: httpx.AsyncClient, make_token: MakeToken
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))

    created = await client.post("/threads", headers=me)
    assert created.status_code == 201
    thread = created.json()
    assert thread["title"] == "Nuevo chat"

    renamed = await client.patch(
        f"/threads/{thread['id']}", json={"title": "  Evidencias  "}, headers=me
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Evidencias"

    ids = [t["id"] for t in (await client.get("/threads", headers=me)).json()]
    assert thread["id"] in ids

    assert (await client.delete(f"/threads/{thread['id']}", headers=me)).status_code == 204
    ids = [t["id"] for t in (await client.get("/threads", headers=me)).json()]
    assert thread["id"] not in ids
    assert (await client.delete(f"/threads/{thread['id']}", headers=me)).status_code == 404


async def test_nobody_else_sees_or_touches_a_chat(client: httpx.AsyncClient, make_token: MakeToken):
    owner = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=owner)).json()

    for intruder in (
        bearer(make_token(USER_ROJAS, TENANT_A)),  # same school, another person
        bearer(make_token(USER_FLORES, TENANT_B)),  # another school
    ):
        ids = [t["id"] for t in (await client.get("/threads", headers=intruder)).json()]
        assert thread["id"] not in ids
        path = f"/threads/{thread['id']}"
        assert (await client.patch(path, json={"title": "x"}, headers=intruder)).status_code == 404
        assert (await client.get(f"{path}/messages", headers=intruder)).status_code == 404
        assert (await client.delete(path, headers=intruder)).status_code == 404

    assert (await client.get(f"/threads/{thread['id']}/messages", headers=owner)).status_code == 200
