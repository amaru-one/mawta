"""Create (or reset the password of) one account: a users row, a memberships row, and, for
role=teacher, a teachers row. A whole new school is installed by `onboard` instead; this is for
adding one account to a school that already exists, or resetting a password. The tenant must
already exist, and no academic data is created here.

It writes users/memberships directly as the owner (ADMIN_DATABASE_URL), to seed the very first
account in a tenant: that needs real ownership/bypass privilege, which the app's own mawta_app
role does not and should not have.
"""

import argparse
import getpass
import sys
from datetime import date
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

import auth as authpkg
from settings import Settings

ROLES = ("teacher", "student", "supervisor", "admin", "director")


class UserAddError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="useradd", description=__doc__.split("\n\n")[0])
    p.add_argument("-tenant", "--tenant", default="", help="tenant UUID (must already exist)")
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


def _friendly(exc: psycopg.Error) -> UserAddError:
    constraint = exc.diag.constraint_name
    if constraint == "users_username_key":
        return UserAddError("that username is already taken")
    if constraint == "users_email_key":
        return UserAddError("that email is already registered")
    if constraint == "memberships_one_school_per_user":
        return UserAddError(
            "this user already has an active membership at a school — a person may belong to "
            "only one"
        )
    return UserAddError(f"{exc.diag.sqlstate}: {exc.diag.message_primary}")


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.username:
        raise UserAddError("-username is required")
    uname = args.username.strip().lower()

    tenant_id: UUID | None = None
    if not args.reset_password:
        if not args.tenant:
            raise UserAddError("-tenant is required")
        try:
            tenant_id = UUID(args.tenant)
        except ValueError as exc:
            raise UserAddError(f"-tenant: {exc}") from None

    password = args.password
    if args.generate_password:
        password, _ = authpkg.new_session_token()
        password = password[:20]
        print(f"generated password: {password}", file=sys.stderr)
    elif not password:
        password = getpass.getpass("password: ")

    settings = Settings()  # type: ignore[call-arg]
    if not settings.admin_database_url:
        raise UserAddError(
            "ADMIN_DATABASE_URL is required (a superuser/owner connection string; useradd cannot "
            "run as the app's own mawta_app role)"
        )
    with psycopg.connect(settings.admin_database_url, row_factory=dict_row) as conn:
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
            with conn.transaction():
                user = conn.execute(
                    """
                    insert into users (email, given_name, family_name, display_name, username,
                                       password_hash, password_changed_at)
                    values (lower(%s), %s, %s, %s, %s, %s, now())
                    returning id
                    """,
                    (args.email, args.given_name, args.family_name, display_name, uname, hashed),
                ).fetchone()
                membership = conn.execute(
                    """
                    insert into memberships (tenant_id, user_id, role, status, joined_at)
                    values (%s, %s, %s, 'active', now())
                    returning id
                    """,
                    (tenant_id, user["id"], args.role),
                ).fetchone()
                teacher_id = None
                if args.role == "teacher" and not args.no_teacher_profile:
                    teacher_id = conn.execute(
                        """
                        insert into teachers (tenant_id, membership_id, employee_code,
                                              display_name, title, hired_on)
                        values (%s, %s, %s, %s, %s, %s)
                        returning id
                        """,
                        (
                            tenant_id,
                            membership["id"],
                            args.employee_code or None,
                            display_name,
                            args.title or None,
                            hired_on,
                        ),
                    ).fetchone()["id"]
        except psycopg.Error as exc:
            raise _friendly(exc) from None
    print(f"user_id={user['id']}")
    print(f"membership_id={membership['id']}")
    if teacher_id is not None:
        print(f"teacher_id={teacher_id}")
    return 0


def _reset_password(conn: psycopg.Connection, username: str, password: str, cost: int) -> int:
    try:
        hashed = authpkg.hash_password(password, cost)
    except authpkg.PasswordLengthError as exc:
        raise UserAddError(f"hash password: {exc}") from None
    try:
        with conn.transaction():
            row = conn.execute(
                """
                update users
                   set password_hash = %s, password_changed_at = now(),
                       failed_login_count = 0, locked_until = null
                 where lower(username) = lower(%s) and deleted_at is null
                returning id
                """,
                (hashed, username),
            ).fetchone()
            if row is None:
                raise UserAddError(f"no user with username {username!r}")
            # Revoking every live session on a password change is the same policy as for a
            # self-service change.
            conn.execute(
                """
                update user_sessions set revoked_at = now(), revoked_reason = 'password_change'
                 where user_id = %s and revoked_at is null
                """,
                (row["id"],),
            )
    except psycopg.Error as exc:
        raise _friendly(exc) from None
    print(f"user_id={row['id']} password reset")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except UserAddError as exc:
        print(f"useradd: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
