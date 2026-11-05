/**
 * Module: modules/product_feedback/requestSections
 *
 * The sections of a request's page, in their built-in order, and the key a person's own order is saved under.
 * A project's default order is a project setting (`FeedbackSettings.request_page_sections`); the order shown is
 * the person's, else the project's, else this one (`utils/sectionOrder`).
 */
import type { SectionOption } from "../../components/SectionOrderEditor";

/** Every section a request page can show, in the built-in order; the label is what the arrange controls call it. */
export const REQUEST_PAGE_SECTIONS: readonly SectionOption[] = [
  { key: "details", label: "Details" },
  { key: "references", label: "External references" },
  { key: "scoring", label: "Scoring" },
  { key: "demand", label: "Demand" },
  { key: "loop", label: "Close the loop" },
  { key: "versions", label: "Version history" },
  { key: "evidence", label: "Evidence" },
  { key: "comments", label: "Comments" },
];

/** The built-in order of the section keys. */
export const REQUEST_SECTION_KEYS: readonly string[] = REQUEST_PAGE_SECTIONS.map((s) => s.key);

/** The key in a person's saved preferences holding their own order (empty means the project's). */
export const REQUEST_SECTIONS_PREFERENCE = "product_feedback.request_sections";
