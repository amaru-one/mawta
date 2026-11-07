"""What the migrated schema promises beyond its tables: one school, private chats, and the
chat service reading only its views."""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError


@pytest.fixture
def db(alembic_runner, alembic_engine: Engine):
    alembic_runner.migrate_up_to("heads")
    with alembic_engine.connect() as conn:
        yield conn
        conn.rollback()


def as_director(conn: Connection, user_id: uuid.UUID) -> None:
    """Act as the chat service does: role mawta_chat, with the director in app.actor_id."""
    conn.execute(text("set local role mawta_chat"))
    conn.execute(text("select set_config('app.actor_id', :id, true)"), {"id": str(user_id)})


def add_user(conn: Connection, name: str) -> uuid.UUID:
    return conn.execute(
        text(
            "insert into users (email, given_name, family_name)"
            " values (:email, :name, 'Prueba') returning id"
        ),
        {"email": f"{name}@example.org", "name": name},
    ).scalar_one()


def test_the_database_holds_one_school(db: Connection) -> None:
    db.execute(text("insert into school (name) values ('I.E. Cristo Rey')"))
    with pytest.raises(IntegrityError, match="school_singleton_key"):
        db.execute(text("insert into school (name) values ('I.E. San Martín')"))


def test_a_director_only_sees_their_own_chats(db: Connection) -> None:
    ana, beto = add_user(db, "ana"), add_user(db, "beto")
    for user in (ana, beto):
        db.execute(text("insert into chat.threads (user_id) values (:u)"), {"u": user})

    as_director(db, ana)
    owners = db.execute(text("select user_id from chat.threads")).scalars().all()
    assert owners == [ana]
    renamed = db.execute(
        text("update chat.threads set title = 'ajeno' where user_id = :u"), {"u": beto}
    )
    assert renamed.rowcount == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        db.execute(text("insert into chat.threads (user_id) values (:u)"), {"u": beto})


def test_the_chat_role_reads_views_not_tables(db: Connection) -> None:
    as_director(db, uuid.uuid4())
    db.execute(text("select count(*) from chat_api.students"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text("select count(*) from public.students"))


def test_every_student_reference_is_declared_for_privacy(db: Connection) -> None:
    undeclared = db.execute(text("select * from privacy.undeclared_student_references")).all()
    assert undeclared == []


def test_no_multi_school_leftovers(db: Connection) -> None:
    leftovers = db.execute(
        text(
            """select 'column ' || attrelid::regclass || '.' || attname from pg_attribute
                where attname = 'tenant_id' and not attisdropped
               union all
               select 'function ' || oid::regproc from pg_proc
                where prosrc ilike '%tenant%' or proname ilike '%tenant%'"""
        )
    ).scalars()
    assert list(leftovers) == []


def test_the_app_can_become_the_chat_role_without_its_privileges(db: Connection) -> None:
    membership = db.execute(
        text(
            """select inherit_option, set_option from pg_auth_members
                where roleid = 'mawta_chat'::regrole and member = 'mawta_app'::regrole"""
        )
    ).one()
    assert (membership.inherit_option, membership.set_option) == (False, True)
    assert (
        db.execute(
            text("select rolcanlogin from pg_roles where rolname = 'mawta_chat'")
        ).scalar_one()
        is False
    )


def test_langgraph_keeps_its_checkpoints_in_its_own_schema(db: Connection) -> None:
    owner = db.execute(
        text("select nspowner::regrole::text from pg_namespace where nspname = 'langgraph'")
    ).scalar_one()
    assert owner == "mawta_langgraph"
