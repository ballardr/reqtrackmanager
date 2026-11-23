"""
Module: modules.context_strategy.record_attachments

Names the file-link table and record column of this module's five record
types for a custom report's record-images block
(`ModuleDefinition.record_attachments`). Only a record's own attachments are
listed, never a comment thread's files; a type whose attachments may show
identifiable people is declared in `NO_RECORD_ATTACHMENTS`.
"""

from __future__ import annotations

from app.modules.context_strategy.models import (
    FutureStateFile,
    GuidingPrincipleFile,
    OpenQuestionFile,
    PainPointFile,
    StrategyFile,
)
from app.modules.registry import RecordAttachmentProvider

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    "strategy": RecordAttachmentProvider(StrategyFile, StrategyFile.strategy_id),
    "future_state": RecordAttachmentProvider(FutureStateFile, FutureStateFile.future_state_id),
    "pain_point": RecordAttachmentProvider(PainPointFile, PainPointFile.pain_point_id),
    "guiding_principle": RecordAttachmentProvider(GuidingPrincipleFile, GuidingPrincipleFile.guiding_principle_id),
    "open_question": RecordAttachmentProvider(OpenQuestionFile, OpenQuestionFile.open_question_id),
}

NO_RECORD_ATTACHMENTS: dict[str, str] = {}
