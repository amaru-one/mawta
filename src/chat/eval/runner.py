"""Runs the question bank through the chat graph, in-process and with the real model, and judges
each answer with the checks (D007).

The database is a throwaway one: migrated with Alembic, the demo school installed with the same
loader `onboard` uses, and the lived year loaded from `seed_demo.sql`. Each case runs `repeat`
times, because the model is not deterministic. With Langfuse configured, the bank is the dataset
`chat-director-bank`, each repetition is a dataset run, every answer is a trace (the chat's own
tracer) and every check is a score on it.
"""

import json
import logging
import secrets
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

import curriculum
from chat import repo
from chat.eval.bank import Case
from chat.eval.checks import Answer, CheckResult, ToolCall, failures, passed, run_checks
from chat.graph import SYSTEM_PROMPT
from chat.llm import LLM
from chat.service import ChatService
from chat.tracing import LangfuseTracer
from db import Database, RequestCtx, admin_engine, sa_url
from onboarding import load as loader
from onboarding import spec as spec_mod
from onboarding.validate import validate
from settings import Settings

log = logging.getLogger("mawta.chat-eval")

ROOT = Path(__file__).resolve().parents[3]
DATASET = "chat-director-bank"
Log = Callable[[str], None]


def _with_options(url: str, options: str) -> str:
    return f"{url}?options={options.replace(' ', '%20').replace('=', '%3D')}"


@dataclass
class EvalDatabase:
    """A throwaway database with San Felipe frozen in it."""

    name: str
    admin_url: str  # the superuser, on this database
    app_url: str  # the superuser running as mawta_app (so SET ROLE mawta_chat works)
    langgraph_url: str  # the superuser, search_path langgraph
    cluster_url: str  # the superuser, on the cluster's own database: to drop this one

    @classmethod
    def create(cls, admin_url: str, demo_dir: Path, log_line: Log = print) -> "EvalDatabase":
        for name in ("ejemplo-san-felipe.json", "seed_demo.sql"):
            if not (demo_dir / name).is_file():
                raise FileNotFoundError(f"{demo_dir / name} (the mawta-demo checkout)")
        name = f"mawta_eval_{secrets.token_hex(4)}"
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        db_url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
        log_line(f"base {name}: migraciones…")
        engine = create_engine(sa_url(db_url))
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["skip_logging"] = True
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        engine.dispose()
        log_line("colegio (ejemplo-san-felipe.json)…")
        cat = curriculum.load()
        spec = spec_mod.decode((demo_dir / "ejemplo-san-felipe.json").read_text(encoding="utf-8"))
        validate(spec, cat)
        owner = admin_engine(db_url)
        with owner.connect() as conn:
            loader.load(conn, spec, cat, bcrypt_cost=4)
            conn.commit()
        owner.dispose()
        log_line("año vivido (seed_demo.sql)…")
        with psycopg.connect(db_url) as conn:
            conn.execute((demo_dir / "seed_demo.sql").read_bytes())
            conn.commit()
        return cls(
            name=name,
            admin_url=db_url,
            app_url=_with_options(db_url, "-c role=mawta_app"),
            langgraph_url=_with_options(db_url, "-c search_path=langgraph"),
            cluster_url=admin_url,
        )

    def drop(self) -> None:
        with psycopg.connect(self.cluster_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(self.name))
            )


@dataclass
class CaseRun:
    case: Case
    repeat: int
    answer: Answer
    checks: list[CheckResult]
    latency_ms: int
    trace_id: str | None = None

    @property
    def passed(self) -> bool:
        return passed(self.checks)

    @property
    def failures(self) -> list[str]:
        return failures(self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.id,
            "category": self.case.category,
            "repeat": self.repeat,
            "passed": self.passed,
            "failures": self.failures,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "latency_ms": self.latency_ms,
            "trace_id": self.trace_id,
            "answer": self.answer.text,
            "tool_calls": [
                {"name": c.name, "input": c.input, "is_error": c.is_error}
                for c in self.answer.tool_calls
            ],
            "error": self.answer.error,
        }


async def ask(
    service: ChatService, db: Database, ctx: RequestCtx, school: str, key: str, question: str
) -> tuple[Answer, str | None, int]:
    """One question through the graph, as the route does it, collecting what the checks need.
    Returns the answer, the Langfuse trace id (if any) and the latency."""
    assert ctx.actor_id is not None
    system = SYSTEM_PROMPT.format(school=school)
    text: list[str] = []
    calls: list[ToolCall] = []
    blocks: list[dict[str, Any]] = []
    error: str | None = None
    started = time.monotonic()
    with service.tracer.question(
        thread_key=key, user_id=str(ctx.actor_id), question=question, system=system
    ) as trace:
        config = {
            "configurable": {
                "thread_id": key,
                "system": system,
                "db": db,
                "ctx": ctx,
                "trace": trace,
            }
        }
        graph_input = {
            "messages": [{"role": "user", "content": question}],
            "model_calls": 0,
            "stop_reason": None,
        }
        try:
            async for chunk in service.graph.astream(graph_input, config, stream_mode="custom"):
                kind = chunk["kind"]
                if kind == "text":
                    text.append(chunk["delta"])
                elif kind == "block":
                    blocks.append(chunk["block"])
                elif kind == "tool_call":
                    calls.append(
                        ToolCall(
                            chunk["name"],
                            dict(chunk["input"] or {}),
                            chunk["result"],
                            bool(chunk["is_error"]),
                        )
                    )
                elif kind == "error":
                    error = chunk["codigo"]
        except Exception:
            log.exception("case %s failed", key)
            error = "respuesta_fallida"
        latency_ms = int((time.monotonic() - started) * 1000)
        answer = Answer("".join(text), calls, blocks, error)
        trace.finish(
            answer=answer.text,
            blocks=blocks,
            latency_ms=latency_ms,
            stop_reason=f"error:{error}" if error else "ok",
        )
        return answer, trace.trace_id, latency_ms


def ensure_dataset(client: Any, cases: Sequence[Case]) -> None:
    """The bank as a Langfuse dataset, every case upserted by its id."""
    try:
        client.get_dataset(DATASET)
    except Exception:
        client.create_dataset(
            name=DATASET,
            description="Banco de preguntas del chat del director (roadmap nivel 1, D007). "
            "Las respuestas esperadas salen de mawta-demo (San Felipe).",
        )
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET,
            id=case.id,
            input={"question": case.question},
            expected_output={
                "tools": list(case.tools),
                "args": {k: list(v) for k, v in case.args.items()},
                "no_args": list(case.no_args),
                "facts": list(case.facts),
                "period": case.period,
                "clarify": case.clarify,
                "out_of_scope": case.out_of_scope,
            },
            metadata={"category": case.category, "source": case.source},
        )


def record(client: Any, run_name: str, run: CaseRun, metadata: dict[str, str]) -> None:
    """Each check as a BOOLEAN score on the answer's trace, and the trace linked to the dataset
    item under the run."""
    if run.trace_id is None:
        return
    for check in run.checks:
        client.create_score(
            name=check.name,
            value=1.0 if check.passed else 0.0,
            trace_id=run.trace_id,
            data_type="BOOLEAN",
            comment=check.detail,
        )
    client.create_score(
        name="pasa_todo",
        value=1.0 if run.passed else 0.0,
        trace_id=run.trace_id,
        data_type="BOOLEAN",
        comment=", ".join(run.failures) or "todas las comprobaciones",
    )
    client.api.dataset_run_items.create(
        run_name=run_name,
        dataset_item_id=run.case.id,
        trace_id=run.trace_id,
        metadata={**metadata, "repeat": str(run.repeat)},
    )


async def run_bank(
    settings: Settings,
    cases: Sequence[Case],
    *,
    repeat: int = 3,
    run_name: str = "chat-eval",
    langfuse: bool = True,
    llm: LLM | None = None,
    log_line: Log = print,
) -> list[CaseRun]:
    """Every case `repeat` times through the chat graph on settings.database_url. `llm` replaces
    the model (tests). Returns one CaseRun per case and repetition."""
    db = Database(settings.database_url)
    service = ChatService(settings, llm=llm)
    runs: list[CaseRun] = []
    async with AsyncExitStack() as stack:
        await service.start(stack)
        if not service.ready:
            raise RuntimeError(
                "the chat has no model: check CHAT_MODEL, its provider's key or URL, and "
                "LANGGRAPH_DATABASE_URL"
            )
        client = (
            service.tracer.client
            if langfuse and isinstance(service.tracer, LangfuseTracer)
            else None
        )
        if client is not None:
            ensure_dataset(client, cases)
        actor = uuid.uuid4()
        ctx = RequestCtx(actor_id=actor, request_id="chat-eval", role="director")
        async with db.chat_tx(ctx) as conn:
            school = await repo.school_name(conn)
        metadata = {"model": settings.chat_model, "run": run_name}
        batch = secrets.token_hex(3)
        for rep in range(1, repeat + 1):
            rep_name = f"{run_name} · corrida {rep}/{repeat}" if repeat > 1 else run_name
            for case in cases:
                key = f"eval:{batch}:{case.id}:{rep}"
                answer, trace_id, latency_ms = await ask(
                    service, db, ctx, school, key, case.question
                )
                run = CaseRun(case, rep, answer, run_checks(case, answer), latency_ms, trace_id)
                runs.append(run)
                if client is not None:
                    record(client, rep_name, run, metadata)
                mark = "ok  " if run.passed else "FALLA"
                detail = ", ".join(run.failures) if run.failures else f"{latency_ms} ms"
                log_line(f"  [{rep}/{repeat}] {mark} {case.id}: {detail}")
        if isinstance(service.tracer, LangfuseTracer):
            service.tracer.flush()
        await db.close()
    return runs


def pass_rate(runs: Sequence[CaseRun]) -> float:
    """Runs where every check passed, over all runs (the exit gate asks for ≥ 90 %)."""
    return 100.0 * sum(r.passed for r in runs) / len(runs) if runs else 0.0


def summary(runs: Sequence[CaseRun]) -> str:
    """Per case, per check and per category, plus the overall pass rate."""
    lines: list[str] = []
    by_case: dict[str, list[CaseRun]] = {}
    for run in runs:
        by_case.setdefault(run.case.id, []).append(run)
    lines.append("Por caso:")
    for case_id, case_runs in by_case.items():
        ok = sum(r.passed for r in case_runs)
        failed: dict[str, int] = {}
        for r in case_runs:
            for name in r.failures:
                failed[name] = failed.get(name, 0) + 1
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(failed.items())) or "—"
        lines.append(f"  {case_id:28} {ok}/{len(case_runs)}  {detail}")
    lines.append("Por comprobación:")
    totals: dict[str, list[int]] = {}
    for run in runs:
        for check in run.checks:
            t = totals.setdefault(check.name, [0, 0])
            t[0] += check.passed
            t[1] += 1
    for name, (ok, n) in totals.items():
        lines.append(f"  {name:28} {ok}/{n}")
    lines.append("Por categoría:")
    by_cat: dict[str, list[CaseRun]] = {}
    for run in runs:
        by_cat.setdefault(run.case.category, []).append(run)
    for category, cat_runs in by_cat.items():
        lines.append(f"  {category:28} {pass_rate(cat_runs):5.1f} %")
    lines.append(
        f"Total: {sum(r.passed for r in runs)}/{len(runs)} corridas pasan todas las "
        f"comprobaciones ({pass_rate(runs):.1f} %)"
    )
    return "\n".join(lines)


def to_json(runs: Sequence[CaseRun], model: str, run_name: str) -> str:
    return json.dumps(
        {
            "model": model,
            "run": run_name,
            "pass_rate": pass_rate(runs),
            "runs": [r.as_dict() for r in runs],
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
