"""Normalize browser-recorded audio into one canonical format (port of internal/media).

Chrome's MediaRecorder produces audio/webm;codecs=opus; Safari, which has no WebM support at
all, produces audio/mp4. A note recorded in one browser is therefore silently undecodable in
the other. Transcoding every upload to MP3 (decodable by every major browser) removes the
mismatch at the source.
"""

import asyncio

CANONICAL_MIME_TYPE = "audio/mpeg"


class TranscodeError(Exception):
    pass


async def transcode_to_mp3(data: bytes) -> bytes:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-vn", "-ac", "1", "-ar", "44100", "-b:a", "96k", "-f", "mp3", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
    except OSError as exc:
        raise TranscodeError(f"ffmpeg transcode: {exc}") from exc
    stdout, stderr = await proc.communicate(data)
    if proc.returncode != 0:
        raise TranscodeError(f"ffmpeg transcode: exit {proc.returncode}: {stderr.decode()}")
    if not stdout:
        raise TranscodeError(f"ffmpeg transcode produced no output: {stderr.decode()}")
    return stdout
