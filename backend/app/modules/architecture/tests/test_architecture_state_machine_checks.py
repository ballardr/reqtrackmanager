"""Tests for the modelling checks of a state machine diagram (`state_machine_checks.check`): each error and each warning
on its own, and a sound diagram with none. The checks are a pure function of the states and transitions, so these run on
plain objects with no database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.architecture.enums import FindingSeverity
from app.modules.architecture.state_machine_checks import check


def _state(code: str, kind: str = "state", parent=None, name: str | None = None):
    return SimpleNamespace(id=uuid.uuid4(), unique_code=code, name=name or code, kind=kind, parent_state_id=parent)


def _arrow(source, target, event: str = "", guard: str = ""):
    return SimpleNamespace(source_state_id=source.id, target_state_id=target.id, event=event, guard=guard)


def _codes(findings, severity: FindingSeverity | None = None) -> list[tuple[str, str]]:
    return [(f.code, f.subject) for f in findings if severity is None or f.severity == severity]


def _sound():
    start, running, stop = _state("STE-001", "initial"), _state("STE-002"), _state("STE-003", "final")
    return [start, running, stop], [_arrow(start, running), _arrow(running, stop, "halt")]


def test_a_sound_diagram_has_no_findings():
    states, transitions = _sound()
    assert check(states, transitions) == []


def test_an_empty_diagram_has_no_initial_state():
    assert _codes(check([], [])) == [("no_initial", "")]


def test_no_initial_state_at_the_top_level_is_an_error_even_with_a_nested_one():
    outer = _state("STE-001")
    inner = _state("STE-002", "initial", parent=outer.id)
    findings = check([outer, inner], [])
    assert ("no_initial", "") in _codes(findings, FindingSeverity.ERROR)
    assert not any(f.code == "unreachable" for f in findings)  # no entry point, so reachability is not reported


def test_more_than_one_initial_state_in_a_level_is_an_error():
    states, transitions = _sound()
    second = _state("STE-004", "initial")
    findings = check([*states, second], [*transitions, _arrow(second, states[1])])
    assert ("multiple_initial", "STE-004") in _codes(findings, FindingSeverity.ERROR)


def test_an_initial_state_with_an_incoming_transition_is_an_error():
    states, transitions = _sound()
    findings = check(states, [*transitions, _arrow(states[1], states[0])])
    assert ("initial_incoming", "STE-001") in _codes(findings, FindingSeverity.ERROR)


def test_a_final_state_with_an_outgoing_transition_is_an_error():
    states, transitions = _sound()
    findings = check(states, [*transitions, _arrow(states[2], states[1])])
    assert ("final_outgoing", "STE-003") in _codes(findings, FindingSeverity.ERROR)


def test_a_transition_ending_outside_the_diagram_is_an_error():
    states, transitions = _sound()
    stranger = _state("STE-099")
    findings = check(states, [*transitions, _arrow(states[1], stranger)])
    assert ("transition_outside", "") in _codes(findings, FindingSeverity.ERROR)


def test_an_unreachable_state_is_a_warning_and_never_an_error():
    states, transitions = _sound()
    island = _state("STE-004")
    findings = check([*states, island, ], [*transitions, _arrow(island, states[2])])
    assert ("unreachable", "STE-004") in _codes(findings, FindingSeverity.WARNING)
    assert not _codes(findings, FindingSeverity.ERROR)


def test_a_state_entered_directly_makes_its_composite_reachable():
    start, outer = _state("STE-001", "initial"), _state("STE-002")
    inner, done = _state("STE-003", parent=outer.id), _state("STE-004", "final")
    findings = check([start, outer, inner, done], [_arrow(start, inner), _arrow(inner, done)])
    assert "unreachable" not in {f.code for f in findings if f.subject in ("STE-002", "STE-003")}


def test_a_non_final_state_with_no_outgoing_transition_is_a_warning():
    states, transitions = _sound()
    dead_end = _state("STE-004")
    findings = check([*states, dead_end], [*transitions, _arrow(states[1], dead_end, "fail")])
    assert ("no_outgoing", "STE-004") in _codes(findings, FindingSeverity.WARNING)


def test_a_composite_state_is_left_through_a_nested_state():
    start, outer = _state("STE-001", "initial"), _state("STE-002")
    inside, done = _state("STE-003", parent=outer.id), _state("STE-004", "final")
    inner_start = _state("STE-005", "initial", parent=outer.id)
    findings = check(
        [start, outer, inside, inner_start, done],
        [_arrow(start, outer), _arrow(inner_start, inside), _arrow(inside, done, "exit")],
    )
    assert ("no_outgoing", "STE-002") not in _codes(findings)


def test_two_transitions_with_the_same_event_and_no_guard_are_ambiguous():
    states, transitions = _sound()
    findings = check(states, [*transitions, _arrow(states[1], states[2], "HALT")])
    assert _codes(findings, FindingSeverity.WARNING) == [("ambiguous", "STE-002")]


def test_a_guard_makes_the_same_event_unambiguous():
    states, transitions = _sound()
    findings = check(states, [*transitions, _arrow(states[1], states[2], "halt", guard="forced")])
    assert not findings


def test_a_choice_needs_two_outgoing_transitions():
    start, choice, stop = _state("STE-001", "initial"), _state("STE-002", "choice"), _state("STE-003", "final")
    findings = check([start, choice, stop], [_arrow(start, choice), _arrow(choice, stop, guard="ok")])
    assert ("choice_few_outgoing", "STE-002") in _codes(findings, FindingSeverity.WARNING)


def test_a_composite_state_needs_an_initial_child():
    start, outer = _state("STE-001", "initial"), _state("STE-002")
    inner, stop = _state("STE-003", parent=outer.id), _state("STE-004", "final")
    findings = check([start, outer, inner, stop], [_arrow(start, outer), _arrow(outer, stop, "done"), _arrow(inner, stop)])
    assert ("composite_no_initial", "STE-002") in _codes(findings, FindingSeverity.WARNING)


def test_errors_come_before_warnings():
    states, transitions = _sound()
    island = _state("STE-004")
    findings = check([*states, island], [*transitions, _arrow(states[2], states[1])])
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: s != FindingSeverity.ERROR)
