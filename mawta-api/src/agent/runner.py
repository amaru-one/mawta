"""Runs generations for the registered agents.

Run never holds a database transaction open while the model is called: it prepares in one
transaction, calls the model, then applies the answer in another, against fresh data.
"""

import json
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

import applog
from agent import JOB_KIND, Agent, InvalidAnswer, Prepared, Spec
from agent import llm as llm_pkg
from agent.llm import LLMError, Model, Prices
from db import Database, TenantCtx
from errors import AppError, NotFound
from repo import agent_generations as gens
from repo.events import log_event

# Messages a teacher reads when a generation fails. They never carry a technical cause: that
# goes to agent_generations.error_detail.
MSG_RETRY_LATER = "Mawta no pudo generar ahora. Intenta de nuevo en un momento o escríbelo a mano."
MSG_INVALID_ANSWER = (
    "Mawta no logró una propuesta válida esta vez. Intenta de nuevo o escríbelo a mano."
)
MSG_UNAVAILABLE = "Mawta no está disponible en este momento. Puedes escribirlo a mano."
MSG_GONE = "Lo que pediste generar ya no existe. Vuelve a cargar la pantalla."


class Outcome(StrEnum):
    """How an attempt ended when it did not fail transiently: SKIPPED (nothing to do) or FAILED
    (recorded as failed, do not retry). COMPLETED is a completed generation."""

    COMPLETED = ""
    SKIPPED = "skipped"
    FAILED = "failed"


class _ApplyFailed(Exception):
    """Carries an agent.apply error out of its transaction, which rolls back what apply wrote."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


def final_message(exc: Exception) -> tuple[str, bool]:
    """Map an error that retrying will not fix to the teacher's message. Domain errors (the
    experience was deleted, a competency is no longer in it) are final; database and network
    errors are not."""
    if isinstance(exc, NotFound):
        return MSG_GONE, True
    if isinstance(exc, AppError):
        if exc.status == 404:
            return MSG_GONE, True
        if exc.status < 500:
            return exc.message, True
    return "", False


def _usage_of(prices: Prices, u: llm_pkg.Usage) -> gens.Usage:
    return gens.Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_tokens,
        cache_write_tokens=u.cache_write_tokens,
        cost_usd=prices.cost(u) if prices.known() else 0.0,
    )


def _add_usage(a: gens.Usage, b: gens.Usage) -> gens.Usage:
    return replace(
        a,
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
        cost_usd=a.cost_usd + b.cost_usd,
    )


def repair_spec(spec: Spec, previous: Any, why: InvalidAnswer) -> Spec:
    """Ask the model once more, telling it what was wrong with its previous answer."""
    prompt = (
        f"{spec.prompt}\n\n<respuesta_anterior>\n{json.dumps(previous, ensure_ascii=False)}\n"
        f"</respuesta_anterior>\n\nTu respuesta anterior no se pudo usar: {why.reason}\n"
        "Vuelve a responder con el objeto JSON pedido, corrigiendo eso y usando solo los ids "
        "entregados."
    )
    return replace(spec, prompt=prompt)


class Runner:
    """Runs generations for the registered agents."""

    def __init__(
        self,
        database: Database,
        model: Model,
        prices: Prices,
        logger: logging.Logger | None,
        *agents: Agent,
    ) -> None:
        self.db = database
        self.model = model
        self.prices = prices
        self.logger = logger
        self.agents: dict[str, Agent] = {a.name: a for a in agents}
        self.models: dict[str, tuple[Model, Prices]] = {}

    def bind(self, agent: Agent, model: Model, prices: Prices) -> "Runner":
        """Register an agent that runs on its own model and prices instead of the runner's default
        (e.g. the redaction sweep on a small, cheap model)."""
        self.agents[agent.name] = agent
        self.models[agent.name] = (model, prices)
        return self

    def _model_for(self, agent_name: str) -> tuple[Model, Prices]:
        return self.models.get(agent_name, (self.model, self.prices))

    async def run(
        self, tenant_id: UUID, payload: dict, attempt: int, max_attempts: int
    ) -> tuple[Outcome, Exception | None]:
        """Execute one attempt of a generation job. A returned exception means a transient failure
        the queue should retry; anything final is recorded on the generation and reported through
        the Outcome."""
        try:
            generation_id = UUID(str(payload["generation_id"]))
        except (KeyError, ValueError, TypeError):
            return Outcome.SKIPPED, None
        tc = TenantCtx(tenant_id=tenant_id, request_id=f"job:{JOB_KIND}")
        last_attempt = attempt >= max_attempts

        # 1. Claim the generation and read its context.
        gen: dict = {}
        prep = Prepared()
        ag: Agent | None = None
        outcome = Outcome.COMPLETED
        try:
            async with self.db.tenant_tx(tc) as conn:
                try:
                    started, ok = await gens.start_generation(conn, generation_id)
                except NotFound:
                    outcome = Outcome.SKIPPED
                    started, ok = None, False
                if not ok:
                    outcome = Outcome.SKIPPED
                else:
                    assert started is not None
                    gen = started
                    ag = self.agents.get(gen["agent"])
                    if ag is None:
                        outcome = Outcome.FAILED
                        await self._fail(
                            conn, gen, MSG_UNAVAILABLE, f"no agent registered for {gen['agent']}",
                            gens.Usage(),
                        )  # fmt: skip
                    else:
                        try:
                            prep = await ag.prepare(conn, gen)
                        except Exception as exc:
                            msg, final = final_message(exc)
                            if not final:
                                raise
                            outcome = Outcome.FAILED
                            await self._fail(conn, gen, msg, str(exc), gens.Usage())
                        else:
                            if prep.result is not None:
                                await self._complete(
                                    conn,
                                    gen,
                                    prep.result,
                                    gens.Usage(prompt_version=ag.prompt_version),
                                )
        except Exception as exc:
            return Outcome.COMPLETED, exc
        if outcome != Outcome.COMPLETED or prep.result is not None:
            return outcome, None
        assert ag is not None and prep.spec is not None

        # 2. Call the model (with one repair round for an unusable answer), then 3. apply the
        # answer in a fresh transaction.
        model, prices = self._model_for(gen["agent"])
        usage = gens.Usage(model=model.name, prompt_version=ag.prompt_version)
        spec = prep.spec
        for round_no in range(2):
            resp, call_err = await self._call(model, prices, gen, attempt, spec)
            usage = _add_usage(usage, _usage_of(prices, resp.usage))
            if call_err is not None:
                if call_err.permanent:
                    return Outcome.FAILED, await self._fail_tx(
                        tc, gen, MSG_INVALID_ANSWER, str(call_err), usage
                    )
                if last_attempt:
                    return Outcome.FAILED, await self._fail_tx(
                        tc, gen, MSG_RETRY_LATER, str(call_err), usage
                    )
                try:
                    async with self.db.tenant_tx(tc) as conn:
                        await gens.record_generation_usage(conn, gen["id"], usage)
                except Exception as exc:
                    return Outcome.COMPLETED, exc
                return Outcome.COMPLETED, call_err

            final = False
            apply_err: Exception | None = None
            tx_err: Exception | None = None
            try:
                async with self.db.tenant_tx(tc) as conn:
                    current = await gens.get_generation(conn, gen["id"])
                    if current["status"] != gens.GENERATION_RUNNING or gens.expired(current):
                        # Expired or finished elsewhere: never store a late answer.
                        final = True
                        if current["status"] == gens.GENERATION_RUNNING:
                            await self._fail(
                                conn,
                                current,
                                gens.EXPIRED_GENERATION_MESSAGE,
                                "answer arrived after the deadline",
                                usage,
                            )
                    else:
                        try:
                            result = await ag.apply(conn, current, prep, resp.input)
                        except Exception as exc:
                            raise _ApplyFailed(exc) from exc  # roll back anything apply wrote
                        final = True
                        await self._complete(conn, current, result, usage)
            except _ApplyFailed as failed:
                apply_err = failed.cause
            except Exception as exc:
                tx_err = exc
            if final and tx_err is None and apply_err is None:
                return Outcome.COMPLETED, None
            if apply_err is None:
                return Outcome.COMPLETED, tx_err
            if isinstance(apply_err, InvalidAnswer) and round_no == 0:
                spec = repair_spec(spec, resp.input, apply_err)
                continue
            if isinstance(apply_err, InvalidAnswer):
                return Outcome.FAILED, await self._fail_tx(
                    tc, gen, MSG_INVALID_ANSWER, str(apply_err), usage
                )
            msg, is_final = final_message(apply_err)
            if is_final:
                return Outcome.FAILED, await self._fail_tx(tc, gen, msg, str(apply_err), usage)
            return Outcome.COMPLETED, apply_err
        return Outcome.FAILED, await self._fail_tx(
            tc, gen, MSG_INVALID_ANSWER, "no usable answer after repair", usage
        )

    async def _call(
        self, model: Model, prices: Prices, gen: dict, attempt: int, spec: Spec
    ) -> tuple[llm_pkg.Response, LLMError | None]:
        """One model call; logs its usage."""
        start = time.monotonic()
        error: LLMError | None = None
        try:
            resp = await model.generate(
                llm_pkg.Request(
                    system=spec.system,
                    prompt=spec.prompt,
                    tool=spec.tool,
                    max_tokens=spec.max_tokens,
                )
            )
        except LLMError as exc:
            error, resp = exc, exc.response
        except Exception as exc:  # anything else from a model is a transient failure
            error, resp = (
                LLMError(f"llm: {type(exc).__name__}", permanent=False),
                llm_pkg.Response(),
            )
        applog.log_agent_usage(
            self.logger,
            generation_id=str(gen["id"]),
            agent=gen["agent"],
            kind=gen["kind"],
            model=model.name,
            attempt=attempt,
            duration_ms=int((time.monotonic() - start) * 1000),
            outcome="error" if error else "success",
            error_class=("permanent" if error.permanent else "transient") if error else "",
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_read_tokens=resp.usage.cache_read_tokens,
            cache_write_tokens=resp.usage.cache_write_tokens,
            cost_usd=prices.cost(resp.usage) if prices.known() else None,
        )
        return resp, error

    async def _complete(
        self, conn: AsyncConnection, gen: dict, result: Any, usage: gens.Usage
    ) -> None:
        await gens.complete_generation(conn, gen["id"], result, usage)
        await _log_generation_event(conn, "agent.generation.completed", gen)

    async def _fail(
        self, conn: AsyncConnection, gen: dict, message: str, detail: str, usage: gens.Usage
    ) -> None:
        await gens.fail_generation(conn, gen["id"], message, detail, usage)
        await _log_generation_event(conn, "agent.generation.failed", gen)

    async def _fail_tx(
        self, tc: TenantCtx, gen: dict, message: str, detail: str, usage: gens.Usage
    ) -> Exception | None:
        """Record a failure in its own transaction. Its error, if any, is what the worker sees."""
        try:
            async with self.db.tenant_tx(tc) as conn:
                current = await gens.get_generation(conn, gen["id"])
                if current["status"] in (gens.GENERATION_COMPLETED, gens.GENERATION_FAILED):
                    return None
                await self._fail(conn, current, message, detail, usage)
        except Exception as exc:
            return exc
        return None


async def _log_generation_event(conn: AsyncConnection, action: str, gen: dict) -> None:
    await log_event(
        conn,
        action,
        "agent_generation",
        gen["id"],
        {"agent": gen["agent"], "kind": gen["kind"]},
        None,
        gen["class_id"],
    )


_ = datetime, UTC
