"""Evaluate the director chat on the question bank, with the real model (roadmap level 1, D007).

    uv run chat-eval --model openrouter:qwen/qwen3-30b-a3b-instruct-2507
    uv run chat-eval --model local:qwen3.8-27b-6bit --reasoning-effort none --repeat 1
    uv run chat-eval --model local:x --case d003-jalados --case adv-asistencia --no-langfuse

It creates a throwaway database (Alembic, then `ejemplo-san-felipe.json` and `seed_demo.sql` from
the mawta-demo checkout), runs every case through the chat graph `--repeat` times, prints the
checks, and, with LANGFUSE_* set, records the dataset `chat-director-bank`, one dataset run per
repetition, a trace per answer and a score per check.

Settings come from the environment and `.env` as for the app (OPENROUTER_API_KEY, LOCAL_LLM_URL,
LANGFUSE_*); the database ones are replaced by the throwaway database.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from chat.eval import bank, runner
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chat-eval", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--model", required=True, help='"proveedor:modelo", como CHAT_MODEL')
    p.add_argument("--reasoning-effort", default="", help="como CHAT_REASONING_EFFORT")
    p.add_argument(
        "--demo",
        default=os.environ.get("MAWTA_DEMO_DIR") or str(ROOT.parent / "mawta-demo"),
        help="carpeta de mawta-demo (o MAWTA_DEMO_DIR)",
    )
    p.add_argument(
        "--admin-url",
        default=os.environ.get("MAWTA_EVAL_ADMIN_URL") or os.environ.get("ADMIN_DATABASE_URL"),
        help="superusuario del clúster donde crear la base desechable (o MAWTA_EVAL_ADMIN_URL, "
        "ADMIN_DATABASE_URL)",
    )
    p.add_argument("--repeat", type=int, default=3, help="veces que corre cada caso (3)")
    p.add_argument("--case", action="append", default=[], help="solo este caso; se repite")
    p.add_argument("--category", choices=bank.CATEGORIES, help="solo esta categoría")
    p.add_argument("--run-name", default="", help="nombre de la corrida en Langfuse")
    p.add_argument("--no-langfuse", action="store_true", help="no registra nada en Langfuse")
    p.add_argument("--keep-db", action="store_true", help="no borra la base desechable")
    p.add_argument("--json", default="", help="guarda los resultados completos en este archivo")
    p.add_argument("--gate", type=float, default=90.0, help="porcentaje mínimo para salir con 0")
    return p


def select(case_ids: list[str], category: str | None) -> list[bank.Case]:
    cases = list(bank.CASES)
    if category:
        cases = [c for c in cases if c.category == category]
    if case_ids:
        unknown = [i for i in case_ids if i not in bank.BY_ID]
        if unknown:
            raise SystemExit(f"chat-eval: casos desconocidos: {', '.join(unknown)}")
        cases = [c for c in cases if c.id in case_ids]
    return cases


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.admin_url:
        # The app's .env may name the superuser; the database_url is irrelevant here.
        env = Settings(_env_file=".env", database_url="postgres://x")  # pyright: ignore[reportCallIssue]
        args.admin_url = env.admin_database_url
    if not args.admin_url:
        raise SystemExit(
            "chat-eval: falta --admin-url (o MAWTA_EVAL_ADMIN_URL / ADMIN_DATABASE_URL)"
        )
    cases = select(args.case, args.category)
    if not cases:
        raise SystemExit("chat-eval: ningún caso seleccionado")
    run_name = args.run_name or f"{args.model} {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    print(f"chat-eval · {args.model} · {len(cases)} casos × {args.repeat}")
    db = runner.EvalDatabase.create(args.admin_url, Path(args.demo))
    try:
        settings = Settings(  # pyright: ignore[reportCallIssue]
            database_url=db.app_url,
            admin_database_url=db.admin_url,
            langgraph_database_url=db.langgraph_url,
            chat_model=args.model,
            chat_reasoning_effort=args.reasoning_effort,
            worker_enabled=False,
        )
        if settings.langfuse_ready() and not args.no_langfuse:
            print(f"Langfuse: dataset {runner.DATASET}, corrida «{run_name}»")
        else:
            print("Langfuse: no (sin LANGFUSE_* o --no-langfuse); solo salida local")
        runs = asyncio.run(
            runner.run_bank(
                settings,
                cases,
                repeat=args.repeat,
                run_name=run_name,
                langfuse=not args.no_langfuse,
            )
        )
    finally:
        if args.keep_db:
            print(f"base conservada: {db.admin_url}")
        else:
            db.drop()
    print()
    print(runner.summary(runs))
    if args.json:
        Path(args.json).write_text(runner.to_json(runs, args.model, run_name), encoding="utf-8")
        print(f"resultados en {args.json}")
    rate = runner.pass_rate(runs)
    print(
        f"Puerta de salida: {'pasa' if rate >= args.gate else 'no pasa'} ({rate:.1f} % ≥ {args.gate:g} %)"
    )
    return 0 if rate >= args.gate else 1


def main() -> None:
    try:
        sys.exit(run())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"chat-eval: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
