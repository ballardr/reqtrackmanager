/**
 * Module: modules/context_strategy/reportFixtures
 *
 * Storybook-only builders for R1 and R4 report results (Module 1 Phase 13),
 * shaped like the backend's `ReportOut` for those reports. Kept beside the
 * stories rather than in the global `testing/` helpers so core test helpers
 * never import a module's types (same convention as `painPointScoringFixtures`).
 */
import type { ReportCatalogueEntry, ReportResult } from "../../api/reports";
import { buildReportCatalogueEntry, buildReportResult } from "../../testing/reportFixtures";
import type {
  OpenQuestionRegisterData, PainPointPrioritisationData, ReportOpenQuestionRow, ReportRankedPainPoint,
} from "./reportTypes";

const MODULE = "context_strategy";

/** The R1 catalogue entry (project scope). */
export function prioritisationEntry(overrides: Partial<ReportCatalogueEntry> = {}): ReportCatalogueEntry {
  return buildReportCatalogueEntry({
    module_key: MODULE, module_name: "Context & Strategy", key: "r1", slug: "pain-point-prioritisation",
    title: "Pain Point prioritisation", description: "Open Pain Points ranked by the chosen scoring model.",
    path: "/api/v1/projects/project-1/modules/context_strategy/reports/pain-point-prioritisation",
    params: [
      { name: "model_key", type: "string", default: null, choices: null, minimum: null, maximum: null, description: "Scoring model." },
      { name: "rollup", type: "string", default: "weighted_average", choices: ["weighted_average", "worst_case", "average"], minimum: null, maximum: null, description: "Roll-up." },
    ],
    ...overrides,
  });
}

/** The R4 catalogue entry (project scope). */
export function registerEntry(overrides: Partial<ReportCatalogueEntry> = {}): ReportCatalogueEntry {
  return buildReportCatalogueEntry({
    module_key: MODULE, module_name: "Context & Strategy", key: "r4", slug: "open-question-register",
    title: "Open Question register", description: "Unresolved Open Questions.", params: [], supports_include_children: true,
    path: "/api/v1/projects/project-1/modules/context_strategy/reports/open-question-register",
    ...overrides,
  });
}

/** One ranked Pain Point; a Major/Constant item by default. */
export function rankedPainPoint(overrides: Partial<ReportRankedPainPoint> = {}): ReportRankedPainPoint {
  return {
    id: "pp-1", project_id: "project-1", project_name: "Atlas Platform", title: "Report delays under poor connectivity",
    type_name: "Operator", status: "triaged", priority: "high", is_intentional: false, score: 0.8, band: "Critical",
    band_tone: "danger", is_blocker: false, blocker_personas: [], churn_risk: false, personas: [],
    matrix: { severity: "Major", severity_weight: 4, frequency: "Constant", frequency_weight: 4, confidence: "High", confidence_weight: 1 },
    rank: 1, ...overrides,
  };
}

/** R1's `data` for the shared `buildScoringScheme` levels: one model group of two scored items plus one intentional. */
export function prioritisationData(): PainPointPrioritisationData {
  return {
    rollup: "weighted_average",
    groups: [{
      model_key: "sxfxc", model_label: "Severity × Frequency × Confidence",
      severity_levels: [{ name: "Cosmetic", weight: 1 }, { name: "Minor", weight: 2 }, { name: "Moderate", weight: 3 }, { name: "Major", weight: 4 }, { name: "Blocker", weight: 5 }],
      frequency_levels: [{ name: "Rare", weight: 1 }, { name: "Occasional", weight: 2 }, { name: "Frequent", weight: 3 }, { name: "Constant", weight: 4 }],
      bands: [
        { label: "Low", min_score: 0, tone: "muted" }, { label: "Medium", min_score: 0.2, tone: "info" },
        { label: "High", min_score: 0.4, tone: "warning" }, { label: "Critical", min_score: 0.6, tone: "danger" },
      ],
      items: [
        rankedPainPoint(),
        rankedPainPoint({
          id: "pp-2", title: "Checkout times out", rank: 2, score: 0.25, band: "Medium", band_tone: "info", is_blocker: true,
          blocker_personas: ["Field Technician"], churn_risk: true, status: "accepted",
          matrix: { severity: "Blocker", severity_weight: 5, frequency: "Rare", frequency_weight: 1, confidence: null, confidence_weight: null },
        }),
        rankedPainPoint({ id: "pp-3", title: "Premium export limit", is_intentional: true, rank: null }),
      ],
    }],
  };
}

/** A full R1 result (ranking, blockers and matrix sections as the backend emits them). */
export function prioritisationResult(overrides: Partial<ReportResult> = {}): ReportResult {
  return buildReportResult({
    key: "r1", title: "Pain Point prioritisation", notes: ["Persona roll-up: Weighted average."],
    metrics: [{ label: "Blockers", value: 1 }],
    sections: [
      { key: "ranking", title: "Ranked Pain Points", columns: ["Model"], rows: [["sxfxc"]], note: "", gap: false },
      { key: "blockers", title: "Blockers", columns: ["Pain point"], rows: [["Checkout times out"]], note: "At least one persona is at the top Severity level.", gap: true },
      { key: "matrix", title: "Severity × Frequency matrix", columns: ["Model"], rows: [["sxfxc"]], note: "", gap: false },
      { key: "personas", title: "Per-persona breakdown", columns: ["Pain point", "Persona"], rows: [["Checkout times out", "Field Technician"]], note: "", gap: false },
    ],
    data: prioritisationData(), ...overrides,
  });
}

/** One open Open Question row. */
export function openQuestionRow(overrides: Partial<ReportOpenQuestionRow> = {}): ReportOpenQuestionRow {
  return {
    id: "oq-1", project_id: "project-1", project_name: "Atlas Platform", question: "Which regions are in scope?",
    priority: "high", status: "open", owner: "Alex Owner", due_date: "2026-12-01", days_open: 12, is_overdue: false,
    ...overrides,
  };
}

/** A full R4 result: one healthy, one overdue and one unowned question. */
export function registerResult(overrides: Partial<ReportResult> = {}): ReportResult {
  const data: OpenQuestionRegisterData = {
    items: [
      openQuestionRow(),
      openQuestionRow({ id: "oq-2", question: "Is SSO required at launch?", due_date: "2026-09-01", days_open: 40, is_overdue: true, status: "investigating" }),
      openQuestionRow({ id: "oq-3", question: "Who signs off the budget?", owner: null, priority: "low", due_date: null, status: "ready_for_decision" }),
    ],
  };
  return buildReportResult({
    key: "r4", title: "Open Question register", metrics: [{ label: "Open Questions", value: 3 }],
    sections: [
      { key: "open", title: "Open Questions", columns: ["Question"], rows: [["x"]], note: "", gap: false },
      { key: "overdue", title: "Overdue", columns: ["Question"], rows: [["x"]], note: "", gap: true },
      { key: "unowned", title: "Unowned", columns: ["Question"], rows: [["x"]], note: "", gap: true },
      { key: "by_priority", title: "By priority", columns: ["Priority", "Open"], rows: [["High", "2"], ["Low", "1"]], note: "", gap: false },
    ],
    data, ...overrides,
  });
}
