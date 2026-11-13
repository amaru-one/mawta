"""The question bank is well formed: enough cases of each kind, and every case names real tools
and parameters."""

from collections import Counter

from chat.eval.bank import ADVERSARIAL, CASES, CLARIFY, D003, DEMO, FILTERS, Case
from chat.tools import REGISTRY


def test_the_bank_has_at_least_30_cases_of_every_kind():
    assert len(CASES) >= 30
    counts = Counter(c.category for c in CASES)
    assert counts[D003] >= 12, "D003's questions"
    assert counts[DEMO] == 6, "the six questions of the 2026-10-31 demo"
    assert counts[ADVERSARIAL] >= 8, "rankings, attendance, out of scope, injected instructions"
    assert counts[CLARIFY] >= 3, "ambiguous students and sections"


def test_ids_are_unique_and_every_case_says_where_its_answer_comes_from():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    assert all(c.source for c in CASES)
    assert all(c.question.strip() for c in CASES)


def test_cases_name_real_tools_and_parameters():
    for case in CASES:
        for tool in case.tools:
            assert tool is None or tool in REGISTRY, f"{case.id}: {tool}"
        params = {p for t in case.tools if t for p in REGISTRY[t].params}
        for name in case.args:
            assert name in params, f"{case.id}: {name} is not a parameter of {case.tools}"
        for name in case.no_args:
            assert name in FILTERS, f"{case.id}: {name} is not a filter"


def test_the_adversarial_cases_cover_every_kind_the_roadmap_asks_for():
    adversarial = [c for c in CASES if c.category == ADVERSARIAL]
    assert any("ranking" in c.question.lower() or "mejores" in c.question for c in adversarial)
    assert any("asistencia" in c.facts for c in adversarial)
    assert sum(c.out_of_scope for c in adversarial) >= 2
    assert any(
        "ignora" in c.question.lower() or "select" in c.question.lower() for c in adversarial
    )


def test_a_case_is_frozen_data():
    case: Case = CASES[0]
    try:
        case.question = "otra"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("cases must be immutable")
