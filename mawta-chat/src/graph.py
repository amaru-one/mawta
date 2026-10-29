"""The chat's LangGraph graph (level 0): agent <-> tools, until it answers.

Level 1 adds nodes (classify the question, verify numbers) around these two
without rewriting them (roadmap principle 4).

The conversation history lives in the graph state, persisted by the
checkpointer in the langgraph database, one thread per chat, in the
OpenAI-compatible message shape. It is only ever appended to: assistant
messages are replayed exactly as the model returned them.

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

CUT_OFF = "La respuesta quedó incompleta. Intenta preguntarlo de forma más breve o por partes."

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


def has_tool_calls(message: dict[str, Any]) -> bool:
    return message["role"] == "assistant" and bool(message.get("tool_calls"))


def tool_input(arguments: str) -> tuple[Any, bool]:
    """A tool call's arguments arrive as a JSON string. Returns (input, ok); an
    empty string is no input, and anything that is not JSON is answered as a
    tool error so the model can try again."""
    if not arguments.strip():
        return {}, True
    try:
        return json.loads(arguments), True
    except ValueError:
        return None, False


def build_graph(llm: LLM, max_model_calls: int, checkpointer: Any):
    async def agent(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        writer = get_stream_writer()
        if state["model_calls"] >= max_model_calls:
            writer({"kind": "text", "delta": LIMIT_REACHED})
            return {
                "messages": [{"role": "assistant", "content": LIMIT_REACHED}],
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
        if turn.stop_reason == "content_filter":
            writer(
                {
                    "kind": "error",
                    "codigo": "rechazada",
                    "mensaje": "No puedo responder esa pregunta.",
                }
            )
        elif turn.stop_reason == "length" and not has_tool_calls(turn.message):
            writer({"kind": "error", "codigo": "cortada", "mensaje": CUT_OFF})
        return {
            "messages": [turn.message],
            "model_calls": state["model_calls"] + 1,
            "stop_reason": turn.stop_reason,
        }

    async def tools(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        writer = get_stream_writer()
        configurable = config.get("configurable", {})
        results: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = state["messages"][-1]["tool_calls"]
        async with configurable["db"].tenant_tx(configurable["principal"]) as conn:
            for call in calls:
                name = call["function"]["name"]
                writer({"kind": "status", "texto": TOOL_STATUS.get(name, "Consultando…")})
                tool_in, ok = tool_input(call["function"]["arguments"])
                if not ok:
                    outcome = ToolOutcome(
                        result={"error": "the arguments are not valid JSON"}, is_error=True
                    )
                else:
                    try:
                        outcome = await run_tool(name, tool_in, conn)
                    except Exception:
                        log.exception("tool %s failed", name)
                        outcome = ToolOutcome(result={"error": "the query failed"}, is_error=True)
                for shown in outcome.blocks:
                    writer({"kind": "block", "block": shown})
                writer(
                    {
                        "kind": "tool_call",
                        "name": name,
                        "input": tool_in,
                        "result": outcome.result,
                        "is_error": outcome.is_error,
                    }
                )
                # An error is said in the content itself: the format has no
                # is_error flag.
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(outcome.result, ensure_ascii=False, default=str),
                    }
                )
        return {"messages": results}

    # A tool call is always answered with its tool message, even after a
    # truncated or refused turn: a history with an unanswered tool call is
    # rejected by the API on the next question.
    def after_agent(state: ChatState) -> Literal["tools", "__end__"]:
        if state["stop_reason"] != "limit" and has_tool_calls(state["messages"][-1]):
            return "tools"
        return "__end__"  # END; a Literal, so LangGraph can draw the edge

    graph = StateGraph(ChatState)
    # LangGraph's own signatures leave some generics unresolved (CachePolicy,
    # BaseCheckpointSaver) in parameters this graph does not use.
    graph.add_node("agent", agent)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("tools", tools)  # pyright: ignore[reportUnknownMemberType]
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)  # pyright: ignore[reportUnknownMemberType]
