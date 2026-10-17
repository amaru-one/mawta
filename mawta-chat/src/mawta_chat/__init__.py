"""mawta-chat: the director chat service."""


def main() -> None:
    """Run the service with uvicorn (`uv run mawta-chat`)."""
    import os

    import uvicorn

    uvicorn.run(
        "mawta_chat.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8001")),
    )
