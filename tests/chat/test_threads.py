"""Chats belong to one director."""

import httpx

from tests.chat.conftest import ANA, BETO, QUISPE, Session


async def test_requests_without_a_director_session_are_refused(
    client: httpx.AsyncClient, session: Session
):
    response = await client.get("/threads")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_session"
    response = await client.get("/threads", headers=await session(QUISPE, "teacher"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_director"
    assert (await client.get("/health")).status_code == 200


async def test_a_director_creates_renames_and_deletes_a_chat(
    client: httpx.AsyncClient, session: Session
):
    me = await session(ANA)

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


async def test_nobody_else_sees_or_touches_a_chat(client: httpx.AsyncClient, session: Session):
    owner = await session(ANA)
    thread = (await client.post("/threads", headers=owner)).json()

    for intruder in (await session(BETO),):  # the school's other director
        ids = [t["id"] for t in (await client.get("/threads", headers=intruder)).json()]
        assert thread["id"] not in ids
        path = f"/threads/{thread['id']}"
        assert (await client.patch(path, json={"title": "x"}, headers=intruder)).status_code == 404
        assert (await client.get(f"{path}/messages", headers=intruder)).status_code == 404
        assert (await client.delete(path, headers=intruder)).status_code == 404
        asked = await client.post(f"{path}/messages", json={"texto": "hola"}, headers=intruder)
        assert asked.status_code == 404

    assert (await client.get(f"/threads/{thread['id']}/messages", headers=owner)).status_code == 200
