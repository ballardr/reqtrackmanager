/**
 * Module: modules/context_strategy/contextStrategySort
 *
 * The sortable value of each sortable column on the Strategies, Guiding Principles, Future States and Open Questions
 * lists, for `sortRows`. The project pages and the organisation panels share them, so one record type orders the same
 * way in both. The lists load their whole filtered set in one request, so the order is applied in the browser; a
 * project page keeps the sort in the URL (`useUrlSort`, keyed by the `*_SORT_KEYS` below), a panel keeps it local.
 * Text sorts as the cell reads, a priority by rank (low, medium, high) rather than alphabetically, a version by number.
 */
import { TIME_SORT_KEYS } from "../../hooks/useListSort";
import { TIME_SORT_VALUES, type SortValue } from "../../utils/sortRows";
import {
  FUTURE_STATE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, OPEN_QUESTION_STATUS_LABEL, PAIN_POINT_STATUS_LABEL, STRATEGY_STATUS_LABEL,
  type FutureState, type GuidingPrinciple, type OpenQuestion, type PainPoint, type Strategy,
} from "./types";

type Values<Row> = Record<string, (row: Row) => SortValue>;

/** The rank of a priority, so High sorts after Medium after Low in ascending order. */
const PRIORITY_RANK: Record<"low" | "medium" | "high", number> = { low: 0, medium: 1, high: 2 };

export const STRATEGY_SORT_KEYS = ["title", "code", "priority", "status", "version", ...TIME_SORT_KEYS] as const;
export const STRATEGY_SORT_VALUES: Values<Strategy> = {
  ...TIME_SORT_VALUES,
  title: (s) => s.title,
  code: (s) => s.unique_code,
  priority: (s) => PRIORITY_RANK[s.priority],
  status: (s) => STRATEGY_STATUS_LABEL[s.status],
  version: (s) => s.version_number,
};

export const GUIDING_PRINCIPLE_SORT_KEYS = ["name", "code", "priority", "status", "version", ...TIME_SORT_KEYS] as const;
export const GUIDING_PRINCIPLE_SORT_VALUES: Values<GuidingPrinciple> = {
  ...TIME_SORT_VALUES,
  name: (g) => g.name,
  code: (g) => g.unique_code,
  priority: (g) => PRIORITY_RANK[g.priority],
  status: (g) => GUIDING_PRINCIPLE_STATUS_LABEL[g.status],
  version: (g) => g.version_number,
};

export const FUTURE_STATE_SORT_KEYS = ["title", "code", "status", "target_date", "version", ...TIME_SORT_KEYS] as const;
export const FUTURE_STATE_SORT_VALUES: Values<FutureState> = {
  ...TIME_SORT_VALUES,
  title: (fs) => fs.title,
  code: (fs) => fs.unique_code,
  status: (fs) => FUTURE_STATE_STATUS_LABEL[fs.status],
  target_date: (fs) => fs.target_date,
  version: (fs) => fs.version_number,
};

/** The Pain Points list's sortable columns (its Score column is ordered by the page, which holds the scores). */
export const PAIN_POINT_SORT_KEYS = ["title", "code", "type", "priority", "status", "score", ...TIME_SORT_KEYS] as const;
export const PAIN_POINT_SORT_VALUES: Values<PainPoint> = {
  ...TIME_SORT_VALUES,
  title: (p) => p.title,
  code: (p) => p.unique_code,
  type: (p) => p.pain_point_type_name,
  priority: (p) => PRIORITY_RANK[p.priority],
  status: (p) => PAIN_POINT_STATUS_LABEL[p.status],
};

export const OPEN_QUESTION_SORT_KEYS = ["question", "code", "priority", "status", "due_date", ...TIME_SORT_KEYS] as const;
export const OPEN_QUESTION_SORT_VALUES: Values<OpenQuestion> = {
  ...TIME_SORT_VALUES,
  question: (q) => q.question,
  code: (q) => q.unique_code,
  priority: (q) => PRIORITY_RANK[q.priority],
  status: (q) => OPEN_QUESTION_STATUS_LABEL[q.status],
  due_date: (q) => q.due_date,
};
