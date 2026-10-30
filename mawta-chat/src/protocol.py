"""Protocol v1 between the chat service and the UI.

While answering, the service streams Server-Sent Events. Every event carries
"version" and "tipo"; the UI ignores a tipo it does not know.

Streamed events:
    estado   {"texto"}                         what the chat is doing now
    texto    {"delta"}                         a fragment of the answer text
    tabla    {"titulo", "columnas", "filas", "nota"}
    barras_apiladas {"titulo", "categorias", "grupos": [{"etiqueta", "valores"}], "nota"}
                                               one bar per group, split into categorias
                                               (AD, A, B, C), drawn at 100 %
    matriz   {"titulo", "columnas", "filas": [{"grupo", "etiqueta", "celdas"}], "nota"}
                                               rows grouped under a heading × columns; a
                                               null cell is empty
    error    {"codigo", "mensaje"}
    fin      {"message_id"}                    the answer is complete and saved

Saved blocks (chat.messages.blocks) are the same shapes, consolidated: the
streamed texto deltas become one {"tipo": "texto", "md": "..."} block.
"""

import json
from typing import Any

PROTOCOL_VERSION = 1


def event(tipo: str, **fields: Any) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "tipo": tipo, **fields}


def to_sse(evt: dict[str, Any]) -> dict[str, str]:
    """The shape sse_starlette's EventSourceResponse expects."""
    return {
        "event": evt["tipo"],
        "data": json.dumps(evt, ensure_ascii=False, default=str),
    }
