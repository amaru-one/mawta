"""Locating and replacing the people a transcript names.

Offsets are Unicode code points, so what the sweep stores is stable across languages.
"""

from dataclasses import dataclass

from mawta_api.repo import redaction as repo

# Replacement tokens left in transcript_redacted.
TOKEN_STUDENT = "[ESTUDIANTE]"
TOKEN_PERSON = "[PERSONA]"


def classmate_token(n: int) -> str:
    return f"[COMPAÑERO_{n}]"


@dataclass
class Fragment:
    """One person reference the model pointed at: the exact words as they appear in the
    transcript, who they refer to and, for a classmate, the roster key it matched."""

    text: str
    refers_to: str
    student_key: str


@dataclass
class Span:
    """One occurrence of a fragment in the transcript."""

    start: int
    end: int
    frag: Fragment


class LocateError(Exception):
    pass


def locate(transcript: str, frags: list[Fragment]) -> list[Span]:
    """Find every whole-word occurrence of each fragment. The model is told to copy fragments
    exactly; a case difference is forgiven, anything else is not: a fragment that does not occur
    is an error the model gets one chance to fix. Longer fragments claim their text first, so
    "la mamá de Lucía" wins over "Lucía" inside it; a fragment whose every occurrence lies inside
    a longer one is fine."""
    order = sorted(range(len(frags)), key=lambda i: -len(frags[i].text))  # stable
    claimed = [False] * len(transcript)
    spans: list[Span] = []
    for i in order:
        frag = frags[i]
        needle = frag.text
        n = len(needle)
        found = False
        for start in range(len(transcript) - n + 1):
            end = start + n
            if not _equal_fold(transcript[start:end], needle) or not _word_boundary(
                transcript, start, end
            ):
                continue
            found = True
            if any(claimed[start:end]):
                continue
            for k in range(start, end):
                claimed[k] = True
            spans.append(Span(start, end, frag))
        if not found:
            raise LocateError(
                f'el fragmento "{frag.text}" no aparece en la transcripción; copia el texto exacto'
            )
    spans.sort(key=lambda s: s.start)
    return spans


def _equal_fold(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return all(x == y or x.lower() == y.lower() for x, y in zip(a, b, strict=True))


def _is_word(ch: str) -> bool:
    return ch.isalpha() or ch.isdigit()


def _word_boundary(s: str, start: int, end: int) -> bool:
    if start > 0 and _is_word(s[start - 1]) and _is_word(s[start]):
        return False
    return not (end < len(s) and _is_word(s[end]) and _is_word(s[end - 1]))


def redact(transcript: str, spans: list[Span]) -> tuple[str, list[str]]:
    """The redacted transcript from spans sorted by start, and the replacement token of each
    span. Classmates are numbered by first appearance, and the same classmate keeps the same
    number."""
    numbers: dict[str, int] = {}
    tokens: list[str] = []
    out: list[str] = []
    prev = 0
    for s in spans:
        if s.frag.refers_to == repo.REFERS_TO_ASSIGNED_STUDENT:
            token = TOKEN_STUDENT
        elif s.frag.refers_to == repo.REFERS_TO_CLASSMATE:
            n = numbers.setdefault(s.frag.student_key, len(numbers) + 1)
            token = classmate_token(n)
        else:
            token = TOKEN_PERSON
        tokens.append(token)
        out.append(transcript[prev : s.start])
        out.append(token)
        prev = s.end
    out.append(transcript[prev:])
    return "".join(out), tokens


def attribution(spans: list[Span], unreadable: bool, reassigned: bool) -> tuple[str, str | None]:
    """Whether a swept note is usable as evidence of its assigned student. A note that names
    classmates and never the assigned student was most likely recorded on the wrong student.
    reassigned means a teacher moved the note on purpose: that decision stands unless the note
    cannot be read at all."""
    if unreadable:
        return repo.ATTRIBUTION_DISCARDED, repo.DISCARD_UNREADABLE
    if reassigned:
        return repo.ATTRIBUTION_REASSIGNED, None
    assigned = any(s.frag.refers_to == repo.REFERS_TO_ASSIGNED_STUDENT for s in spans)
    classmate = any(s.frag.refers_to == repo.REFERS_TO_CLASSMATE for s in spans)
    if classmate and not assigned:
        return repo.ATTRIBUTION_DISCARDED, repo.DISCARD_MENTIONS_OTHER_STUDENT
    return repo.ATTRIBUTION_OK, None
