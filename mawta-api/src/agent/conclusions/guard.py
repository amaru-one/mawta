"""The last check before a proposal reaches a teacher (and, once saved, SIAGIE): no replacement
token and no name of a student on the roster may appear in the text.

Voice notes and score feedback reach the model as the teacher wrote or said them, names
included, so this check is what keeps every name out of the conclusion.
"""

import re
from typing import Any

_TOKEN_PATTERN = re.compile(r"\[[^\]\s]{2,}\]")
_ACCENTS = str.maketrans("áéíóúüàèìòù", "aeiouuaeiou")


def fold(text: str) -> str:
    """Lowercase and strip accents, so "María" and "Maria" are one name."""
    return text.lower().translate(_ACCENTS)


def guard(text: str, names: list[str]) -> str:
    """Why a text cannot be used, or "" when it can."""
    if match := _TOKEN_PATTERN.search(text):
        return (
            f"el texto contiene la marca {match.group(0)}; escribe sin nombres ni marcas, "
            "en tercera persona"
        )
    words = _tokenize(text)
    for name in names:
        if _contains_name(words, name):
            return f"el texto contiene un nombre de estudiante («{name}»); nunca nombres a nadie"
    return ""


def name_words(students: list[dict[str, Any]]) -> list[str]:
    """The individual names of the students that the output must not contain. Very short names
    (two letters or fewer) are skipped: they collide with ordinary words."""
    seen: set[str] = set()
    out: list[str] = []

    def add(value: str | None) -> None:
        for word in (value or "").split():
            if len(word) <= 2 or fold(word) in seen:
                continue
            seen.add(fold(word))
            out.append(word)

    for s in students:
        add(s["given_name"])
        add(s["paternal_surname"])
        add(s["preferred_name"])
        add(s["maternal_surname"])
    return out


def _tokenize(text: str) -> list[tuple[str, bool]]:
    """(folded word, capitalised) for every run of letters."""
    return [(fold(w), w[0].isupper()) for w in re.findall(r"[^\W\d_]+", text)]


def _contains_name(words: list[tuple[str, bool]], name: str) -> bool:
    """Whether a name occurs as a capitalised word: a name that is also a common word ("Rosa",
    "Flor") only counts when written as a name, so "una flor" in a science conclusion is not
    rejected."""
    target = fold(name)
    return any(capitalized and folded == target for folded, capitalized in words)
