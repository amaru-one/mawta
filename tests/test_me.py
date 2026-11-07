"""/me and the profile name the school of this database, never a tenant."""

from tests.conftest import FX, Client, Login


async def test_me_and_profile_name_the_school(client: Client, login: Login):
    teacher = await login(FX.user_quispe)
    me = (await client.do(teacher, "GET", "/api/v1/me")).json()
    assert me["school"] == {"name": "I.E. Cristo Rey", "city": None, "timezone": "America/Lima"}
    assert "tenant" not in me

    profile = (await client.do(teacher, "GET", "/api/v1/profile")).json()
    assert profile["school_name"] == "I.E. Cristo Rey"
    assert "school_city" in profile and profile["school_city"] is None
    assert not any(key.startswith("tenant") for key in profile)
