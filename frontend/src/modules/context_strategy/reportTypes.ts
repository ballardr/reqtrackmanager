/**
 * Module: modules/context_strategy/reportTypes
 *
 * The `ReportResult.data` shapes this module's custom report views read
 * (Module 1 Phase 13), mirroring the dataclasses `collect_pain_point_
 * prioritisation` (R1) and `collect_open_question_register` (R4) return in
 * `backend/app/modules/context_strategy/reports.py`. Dates arrive as ISO
 * strings; scores are normalised 0–1 (shown as 0–100).
 */
import type { BadgeTone } from "../../api/types";
import type { OpenQuestionPriority, OpenQuestionStatus, PainPointRollup, PainPointStatus } from "./types";

/** `LevelRef`: a scoring level on a matrix axis. */
export interface ReportLevel {
  name: string;
  weight: number;
}

/** `PersonaScoreRow`: one persona's (or all-personas) score of a Pain Point. */
export interface ReportPersonaScore {
  persona: string;
  target_status: string;
  severity: string | null;
  frequency: string | null;
  confidence: string | null;
  score: number | null;
  band: string | null;
  is_blocker: boolean;
  severity_ratio: number | null;
}

/** `MatrixPoint`: where a Pain Point sits (its worst counted persona). */
export interface ReportMatrixPoint {
  severity: string;
  severity_weight: number;
  frequency: string;
  frequency_weight: number;
  confidence: string | null;
  confidence_weight: number | null;
}

/** `RankedPainPoint`: one Pain Point under one model and roll-up. */
export interface ReportRankedPainPoint {
  id: string;
  project_id: string;
  project_name: string;
  title: string;
  type_name: string;
  status: PainPointStatus;
  priority: string;
  is_intentional: boolean;
  /** Normalised 0–1; null = not scored under this model. */
  score: number | null;
  band: string | null;
  band_tone: BadgeTone | null;
  is_blocker: boolean;
  blocker_personas: string[];
  churn_risk: boolean;
  personas: ReportPersonaScore[];
  matrix: ReportMatrixPoint | null;
  rank: number | null;
}

/** `ScoredGroup`: Pain Points scored under one model. */
export interface ReportScoredGroup {
  model_key: string;
  model_label: string;
  severity_levels: ReportLevel[];
  frequency_levels: ReportLevel[];
  bands: { label: string; min_score: number; tone: BadgeTone }[];
  items: ReportRankedPainPoint[];
}

/** R1's `ReportResult.data`. */
export interface PainPointPrioritisationData {
  rollup: PainPointRollup;
  groups: ReportScoredGroup[];
}

/** `OpenQuestionRow`: one open Open Question. */
export interface ReportOpenQuestionRow {
  id: string;
  project_id: string;
  project_name: string;
  question: string;
  priority: OpenQuestionPriority;
  status: OpenQuestionStatus;
  owner: string | null;
  due_date: string | null;
  days_open: number;
  is_overdue: boolean;
}

/** R4's `ReportResult.data`. */
export interface OpenQuestionRegisterData {
  items: ReportOpenQuestionRow[];
}
