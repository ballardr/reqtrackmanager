"""Tests for the helpers that read and write the levels held by one Pain Point score row.

Every reader of a score row (roll-up, matrix, export, API output, grid) goes through `score_level_ids`, and
every writer through `assign_score_level_ids`, so the storage of a row's levels can change in one place. These
pin the axis-keyed shape that the rest of the module depends on.
"""

from __future__ import annotations

import uuid

from app.modules.context_strategy.models import PainPointScore, PainPointScoreAxis
from app.modules.context_strategy.pain_point_scores import (
    ScoreEntryInput,
    assign_score_level_ids,
    entry_level_ids,
    score_level_ids,
)


def _row(**levels: uuid.UUID) -> PainPointScore:
    row = PainPointScore()
    row.axes = [PainPointScoreAxis(axis_key=key, level_id=level) for key, level in levels.items()]
    return row


def test_score_level_ids_returns_only_the_scored_axes() -> None:
    severity = uuid.uuid4()
    assert score_level_ids(_row(severity=severity)) == {"severity": severity}
    assert score_level_ids(_row()) == {}


def test_entry_level_ids_drops_unscored_axes() -> None:
    severity = uuid.uuid4()
    entry = ScoreEntryInput(None, {"severity": severity, "frequency": None})
    assert entry_level_ids(entry) == {"severity": severity}


def test_assign_score_level_ids_reports_whether_anything_changed() -> None:
    severity, frequency = uuid.uuid4(), uuid.uuid4()
    row = _row()
    assert assign_score_level_ids(row, {"severity": severity, "frequency": frequency}) is True
    assert score_level_ids(row) == {"severity": severity, "frequency": frequency}
    assert assign_score_level_ids(row, {"severity": severity, "frequency": frequency}) is False


def test_assign_score_level_ids_replaces_the_set() -> None:
    severity, frequency, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = _row(severity=severity, frequency=frequency)
    assert assign_score_level_ids(row, {"severity": other}) is True
    assert score_level_ids(row) == {"severity": other}
    assert assign_score_level_ids(row, {"severity": None}) is True
    assert score_level_ids(row) == {}
