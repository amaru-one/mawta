"""Review the director chat's real questions and feedback.

    uv run chat-review --days 7
    uv run chat-review --days 30 --json review.json

Reads chat.question_bank, chat.messages and chat.message_feedback from the school database (using
ADMIN_DATABASE_URL / MAWTA_MIGRATIONS_URL / --db-url so RLS across directors does not hide rows)
and prints the missing-tools backlog, negative feedback with Langfuse trace ids, partial answers,
and draft cases for src/chat/eval/bank.py.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from chat.review import collect_report, format_text, to_json
from db import sa_url
from settings import Settings


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chat-review", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--days", type=int, default=7, help="ventana de días (7; 0 = todo el historial)")
    p.add_argument("--limit", type=int, default=20, help="máximo de ítems por sección (20)")
    p.add_argument(
        "--db-url",
        default=os.environ.get("MAWTA_MIGRATIONS_URL") or os.environ.get("ADMIN_DATABASE_URL"),
        help="URL de conexión de la base del colegio (o MAWTA_MIGRATIONS_URL / ADMIN_DATABASE_URL)",
    )
    p.add_argument("--json", default="", help="guarda el reporte completo en este archivo JSON")
    return p


async def _load(db_url: str, *, days: int, limit: int):
    engine = create_async_engine(sa_url(db_url))
    try:
        async with engine.connect() as conn:
            return await collect_report(conn, days=days, limit=limit)
    finally:
        await engine.dispose()


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db_url = args.db_url
    if not db_url:
        env = Settings(_env_file=".env", database_url="postgres://x")  # pyright: ignore[reportCallIssue]
        db_url = env.admin_database_url
    if not db_url:
        raise SystemExit(
            "chat-review: falta --db-url (o MAWTA_MIGRATIONS_URL / ADMIN_DATABASE_URL)"
        )
    report = asyncio.run(_load(db_url, days=args.days, limit=args.limit))
    print(format_text(report))
    if args.json:
        Path(args.json).write_text(to_json(report), encoding="utf-8")
        print(f"\nreporte JSON guardado en {args.json}")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"chat-review: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
