"""The chat's LangGraph graph (level 0): agent <-> tools, until it answers.

Level 1 adds nodes (classify the question, verify numbers) around these two
without rewriting them (roadmap principle 4).

The conversation history lives in the graph state, persisted by the
checkpointer in the langgraph database, one thread per chat. It is only ever
appended to: assistant content is replayed exactly as the model returned it.

Nodes report progress through the custom stream (get_stream_writer); the
route turns those reports into protocol v1 events.
"""

import json
import logging
import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import START, StateGraph

from llm import LLM
from tools import TOOL_STATUS, TOOLS, ToolOutcome, run_tool

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Mawta's data assistant for the leadership of {school}, a school in Peru. \
You answer the director's questions about their school using only the data your tools return.

Today you have a single tool, secciones_del_colegio, which lists the school's sections. \
When a question needs data your tools do not cover, say briefly that you cannot look that up yet; \
never estimate or invent numbers, names or facts.

You do not judge people: do not evaluate, rank or criticise teachers or students. Report data.

When a tool has returned a table, the director already sees it below your text: \
summarise what matters instead of repeating every row.

Answer in Spanish, in a clear and brief way, as you would to a school director."""

LIMIT_REACHED = (
    "No pude terminar de responder: la pregunta necesitó más consultas de las que "
    "puedo hacer en una sola respuesta. Intenta preguntarlo por partes."
)


class ChatState(TypedDict):
    messages: Annotated[list[dict[str, Any]], operator.add]
    model_calls: int
    stop_reason: str | None


def thread_key(tenant_id: Any, user_id: Any, thread_id: Any) -> str:
    """The LangGraph thread id: the checkpoints table has no RLS, so the school
    and the director are always part of the key."""
    return f"{tenant_id}:{user_id}:{thread_id}"


def has_tool_use(message: dict[str, Any]) -> bool:
    return message["role"] == "assistant" and any(
        b.get("type") == "tool_use" for b in message["content"] if isinstance(b, dict)
    )


def build_graph(llm: LLM, max_model_calls: int, checkpointer: Any):
    async def agent(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        writer = get_stream_writer()
        if state["model_calls"] >= max_model_calls:
            writer({"kind": "text", "delta": LIMIT_REACHED})
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": LIMIT_REACHED}],
                    }
                ],
                "stop_reason": "limit",
            }

        turn = await llm.respond(
            config.get("configurable", {})["system"],
            state["messages"],
            TOOLS,
            lambda text: writer({"kind": "text", "delta": text}),
        )
        writer(
            {
                "kind": "usage",
                "model": turn.model,
                "input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
            }
        )
        if turn.stop_reason == "refusal":
            writer(
                {
                    "kind": "error",
                    "codigo": "rechazada",
                    "mensaje": "No puedo responder esa pregunta.",
                }
            )
        return {
            "messages": [{"role": "assistant", "content": turn.content}],
            "model_calls": state["model_calls"] + 1,
            "stop_reason": turn.stop_reason,
        }

    async def tools(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        writer = get_stream_writer()
        configurable = config.get("configurable", {})
        results = []
        tool_uses = [b for b in state["messages"][-1]["content"] if b.get("type") == "tool_use"]
        async with configurable["db"].tenant_tx(configurable["principal"]) as conn:
            for block in tool_uses:
                name = block["name"]
                writer({"kind": "status", "texto": TOOL_STATUS.get(name, "Consultando…")})
                try:
                    outcome = await run_tool(name, block.get("input"), conn)
                except Exception:
                    log.exception("tool %s failed", name)
                    outcome = ToolOutcome(result={"error": "the query failed"}, is_error=True)
                for shown in outcome.blocks:
                    writer({"kind": "block", "block": shown})
                writer(
                    {
                        "kind": "tool_call",
                        "name": name,
                        "input": block.get("input"),
                        "result": outcome.result,
                        "is_error": outcome.is_error,
                    }
                )
                result = {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(outcome.result, ensure_ascii=False, default=str),
                }
                if outcome.is_error:
                    result["is_error"] = True
                results.append(result)
        return {"messages": [{"role": "user", "content": results}]}

    # A tool_use is always answered with its tool_result, even after a
    # truncated or refused turn: a history with an unanswered tool_use is
    # rejected by the API on the next question.
    def after_agent(state: ChatState) -> Literal["tools", "__end__"]:
        if state["stop_reason"] != "limit" and has_tool_use(state["messages"][-1]):
            return "tools"
        return "__end__"  # END; a Literal, so LangGraph can draw the edge

    graph = StateGraph(ChatState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
