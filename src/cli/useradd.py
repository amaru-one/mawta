"""Create (or reset the password of) one account: a users row, a memberships row, and, for
role=teacher, a teachers row. A whole new school is installed by `onboard` instead; this is for
adding one account to the school that already exists in this database, or resetting a password.
No academic data is created here.

It writes users/memberships directly as the owner (ADMIN_DATABASE_URL), which the app's own
mawta_app role is not.
"""

import argparse
import getpass
import sys
from datetime import date
from typing import Any

from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import DBAPIError

import auth as authpkg
from db import admin_engine
from mawta_schema.tables import Membership, School, Teacher, User, UserSession
from settings import Settings

ROLES = ("teacher", "student", "supervisor", "admin", "director")


class UserAddError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="useradd", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("-username", "--username", default="", help="login username; required")
    p.add_argument("-password", "--password", default="", help="password (omit to be prompted)")
    p.add_argument("-generate-password", "--generate-password", action="store_true",
                   help="mint a random password and print it once")  # fmt: skip
    p.add_argument("-email", "--email", default="")
    p.add_argument("-given-name", "--given-name", default="")
    p.add_argument("-family-name", "--family-name", default="")
    p.add_argument("-display-name", "--display-name", default="", help='default "given family"')
    p.add_argument("-role", "--role", default="teacher", help="|".join(ROLES))
    p.add_argument("-title", "--title", default="Docente de Secundaria")
    p.add_argument("-hired-on", "--hired-on", default="", help="YYYY-MM-DD")
    p.add_argument("-employee-code", "--employee-code", default="")
    p.add_argument("-no-teacher-profile", "--no-teacher-profile", action="store_true")
    p.add_argument("-reset-password", "--reset-password", action="store_true",
                   help="update an existing username's password instead of creating an account")  # fmt: skip
    return p


def _friendly(exc: DBAPIError) -> UserAddError:
    diag: Any = getattr(exc.orig, "diag", None)
    constraint = diag.constraint_name if diag is not None else None
    if constraint == "users_username_key":
        return UserAddError("that username is already taken")
    if constraint == "users_email_key":
        return UserAddError("that email is already registered")
    if constraint == "memberships_one_school_per_user":
        return UserAddError(
            "this user already has an active membership at a school — a person may belong to "
            "only one"
        )
    if diag is None:
        return UserAddError(str(exc.orig))
    return UserAddError(f"{diag.sqlstate}: {diag.message_primary}")


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.username:
        raise UserAddError("-username is required")
    uname = args.username.strip().lower()

    password = args.password
    if args.generate_password:
        password, _ = authpkg.new_session_token()
        password = password[:20]
        print(f"generated password: {password}", file=sys.stderr)
    elif not password:
        password = getpass.getpass("password: ")

    settings = Settings()  # pyright: ignore[reportCallIssue]
    if not settings.admin_database_url:
        raise UserAddError(
            "ADMIN_DATABASE_URL is required (a superuser/owner connection string; useradd cannot "
            "run as the app's own mawta_app role)"
        )
    with admin_engine(settings.admin_database_url).connect() as conn:
        if args.reset_password:
            return _reset_password(conn, uname, password, settings.bcrypt_cost)
        if not (args.email and args.given_name and args.family_name):
            raise UserAddError("-email, -given-name and -family-name are required")
        if args.role not in ROLES:
            raise UserAddError(f"-role must be one of {'|'.join(ROLES)}, got {args.role!r}")
        display_name = args.display_name or f"{args.given_name} {args.family_name}"
        try:
            hashed = authpkg.hash_password(password, settings.bcrypt_cost)
        except authpkg.PasswordLengthError as exc:
            raise UserAddError(f"hash password: {exc}") from None
        hired_on = None
        if args.hired_on:
            try:
                hired_on = date.fromisoformat(args.hired_on)
            except ValueError as exc:
                raise UserAddError(f"-hired-on: {exc}") from None
        try:
            with conn.begin():
                if conn.execute(select(School.id)).first() is None:
                    raise UserAddError(
                        "this database has no school yet: install it with onboard first"
                    )
                user_id = conn.execute(
                    insert(User)
                    .values(
                        email=func.lower(args.email),
                        given_name=args.given_name,
                        family_name=args.family_name,
                        display_name=display_name,
                        username=uname,
                        password_hash=hashed,
                        password_changed_at=func.now(),
                    )
                    .returning(User.id)
                ).scalar_one()
                membership_id = conn.execute(
                    insert(Membership)
                    .values(user_id=user_id, role=args.role, status="active", joined_at=func.now())
                    .returning(Membership.id)
                ).scalar_one()
                teacher_id = None
                if args.role == "teacher" and not args.no_teacher_profile:
                    teacher_id = conn.execute(
                        insert(Teacher)
                        .values(
                            membership_id=membership_id,
                            employee_code=args.employee_code or None,
                            display_name=display_name,
                            title=args.title or None,
                            hired_on=hired_on,
                        )
                        .returning(Teacher.id)
                    ).scalar_one()
        except DBAPIError as exc:
            raise _friendly(exc) from None
    print(f"user_id={user_id}")
    print(f"membership_id={membership_id}")
    if teacher_id is not None:
        print(f"teacher_id={teacher_id}")
    return 0


def _reset_password(conn: Connection, username: str, password: str, cost: int) -> int:
    try:
        hashed = authpkg.hash_password(password, cost)
    except authpkg.PasswordLengthError as exc:
        raise UserAddError(f"hash password: {exc}") from None
    try:
        with conn.begin():
            user_id = conn.execute(
                update(User)
                .where(func.lower(User.username) == func.lower(username), User.deleted_at.is_(None))
                .values(
                    password_hash=hashed,
                    password_changed_at=func.now(),
                    failed_login_count=0,
                    locked_until=None,
                )
                .returning(User.id)
            ).scalar_one_or_none()
            if user_id is None:
                raise UserAddError(f"no user with username {username!r}")
            # Revoking every live session on a password change is the same policy as for a
            # self-service change.
            conn.execute(
                update(UserSession)
                .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                .values(revoked_at=func.now(), revoked_reason="password_change")
            )
    except DBAPIError as exc:
        raise _friendly(exc) from None
    print(f"user_id={user_id} password reset")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except UserAddError as exc:
        print(f"useradd: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
