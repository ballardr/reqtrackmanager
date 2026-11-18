/**
 * Module: modules/context_strategy/contextStrategySort
 *
 * The sortable value of each sortable column on the Strategies, Guiding Principles, Future States and Open Questions
 * lists, for `sortRows`. The project pages and the organisation panels share them, so one record type orders the same
 * way in both. The lists load their whole filtered set in one request, so the order is applied in the browser; a
 * project page keeps the sort in the URL (`useUrlSort`, keyed by the `*_SORT_KEYS` below), a panel keeps it local.
 * Text sorts as the cell reads, a priority by rank (low, medium, high) rather than alphabetically, a version by number.
 */
import type { SortValue } from "../../utils/sortRows";
import {
  FUTURE_STATE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, OPEN_QUESTION_STATUS_LABEL, STRATEGY_STATUS_LABEL,
  type FutureState, type GuidingPrinciple, type OpenQuestion, type Strategy,
} from "./types";

type Values<Row> = Record<string, (row: Row) => SortValue>;

/** The rank of a priority, so High sorts after Medium after Low in ascending order. */
const PRIORITY_RANK: Record<"low" | "medium" | "high", number> = { low: 0, medium: 1, high: 2 };

export const STRATEGY_SORT_KEYS = ["title", "code", "priority", "status", "version"] as const;
export const STRATEGY_SORT_VALUES: Values<Strategy> = {
  title: (s) => s.title,
  code: (s) => s.unique_code,
  priority: (s) => PRIORITY_RANK[s.priority],
  status: (s) => STRATEGY_STATUS_LABEL[s.status],
  version: (s) => s.version_number,
};

export const GUIDING_PRINCIPLE_SORT_KEYS = ["name", "code", "priority", "status", "version"] as const;
export const GUIDING_PRINCIPLE_SORT_VALUES: Values<GuidingPrinciple> = {
  name: (g) => g.name,
  code: (g) => g.unique_code,
  priority: (g) => PRIORITY_RANK[g.priority],
  status: (g) => GUIDING_PRINCIPLE_STATUS_LABEL[g.status],
  version: (g) => g.version_number,
};

export const FUTURE_STATE_SORT_KEYS = ["title", "code", "status", "target_date", "version"] as const;
export const FUTURE_STATE_SORT_VALUES: Values<FutureState> = {
  title: (fs) => fs.title,
  code: (fs) => fs.unique_code,
  status: (fs) => FUTURE_STATE_STATUS_LABEL[fs.status],
  target_date: (fs) => fs.target_date,
  version: (fs) => fs.version_number,
};

export const OPEN_QUESTION_SORT_KEYS = ["question", "code", "priority", "status", "due_date"] as const;
export const OPEN_QUESTION_SORT_VALUES: Values<OpenQuestion> = {
  question: (q) => q.question,
  code: (q) => q.unique_code,
  priority: (q) => PRIORITY_RANK[q.priority],
  status: (q) => OPEN_QUESTION_STATUS_LABEL[q.status],
  due_date: (q) => q.due_date,
};
