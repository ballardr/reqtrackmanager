/**
 * Module: components/AnnouncementSeverityMark
 *
 * The severity of an announcement (Information, Warning, Critical) as a coloured icon with its name, so severity
 * is carried by more than colour (WCAG 1.4.1). The name is visually hidden where the layout already shows the
 * message (banner, login pages) and visible in the administration table. One component serves both.
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
