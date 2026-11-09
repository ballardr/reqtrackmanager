/**
 * Module: components/AnnouncementSeverityMark
 *
 * The severity of an announcement as a coloured icon with its name: Information, Warning or Critical.
 *
 * Responsibilities: carry severity by more than colour (WCAG 1.4.1), with a distinct icon per level and the
 * level's name as text. The name is visually hidden where the surrounding layout already shows the message
 * (the banner and login pages), and visible in the administration table, so assistive technology and a
 * colour-blind reader always get the level.
 *
 * Design decisions: it replaces the severity badge; there is one component for the notices and the
 * administration table so the two cannot drift.
 */
import { Info, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react";

import type { AnnouncementSeverity } from "../api/types";
import { ANNOUNCEMENT_SEVERITY_LABEL } from "../api/types";

const ICON: Record<AnnouncementSeverity, LucideIcon> = {
  information: Info,
  warning: TriangleAlert,
  critical: OctagonAlert,
};

/**
 * @param severity The level to show.
 * @param showLabel Shows the level's name beside the icon; otherwise the name is visually hidden.
 */
export function AnnouncementSeverityMark({ severity, showLabel }: { severity: AnnouncementSeverity; showLabel?: boolean }) {
  const Icon = ICON[severity];
  const label = ANNOUNCEMENT_SEVERITY_LABEL[severity];
  return (
    <span className={`announcement-severity announcement-severity--${severity}`} data-severity={severity}>
      <Icon aria-hidden="true" />
      <span className={showLabel ? undefined : "sr-only"}>{showLabel ? label : `${label}:`}</span>
    </span>
  );
}
