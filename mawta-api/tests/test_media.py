"""Voice-note transcoding: what Chrome and Safari record becomes MP3 through ffmpeg.

These tests need a real ffmpeg on the PATH (README) and fail without one: CI installs it, and a
run that never transcodes anything must not look like a run that passed.
"""

import asyncio

import pytest

import media


async def record(*codec_args: str) -> bytes:
    """A two-second tone in the container a browser would produce."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        *codec_args, "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    return stdout


def is_mp3(data: bytes) -> bool:
    # An ID3 tag, or an MPEG audio frame sync (11 set bits).
    return data[:3] == b"ID3" or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


async def test_chrome_webm_opus_becomes_mp3():
    webm = await record("-c:a", "libopus", "-f", "webm")
    mp3 = await media.transcode_to_mp3(webm)
    assert is_mp3(mp3)


async def test_safari_fragmented_mp4_aac_becomes_mp3():
    mp4 = await record("-c:a", "aac", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4")
    mp3 = await media.transcode_to_mp3(mp4)
    assert is_mp3(mp3)


async def test_undecodable_input_is_a_transcode_error():
    with pytest.raises(media.TranscodeError):
        await media.transcode_to_mp3(b"this is not audio")
