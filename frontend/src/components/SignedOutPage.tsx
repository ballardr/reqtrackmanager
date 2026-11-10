/**
 * Module: components/SignedOutPage
 *
 * The page shell every signed-out page sits in (sign in, sign up, password reset): an optional login background, a
 * narrow centred column for the page's cards and the page footer. One component so these pages keep the same width,
 * spacing and footer placement (docs/ux-style-guide.md, one component per pattern).
 *
 * Responsibilities: place the footer either directly below the cards (`after_content`, the default) or at the bottom
 * edge of the window (`bottom_of_page`). The footer is ordinary page flow in both cases, never fixed, so a short
 * window scrolls with the footer after the cards. The position is the one the caller passes (an organisation's own
 * sign-in page passes its resolved value), otherwise the platform setting from the public platform branding read.
 */
import type { CSSProperties, ReactNode } from "react";

import { fileUrl } from "../api/client";
import { usePlatformBranding } from "../hooks/usePlatformBranding";
import { AppFooter } from "./AppFooter";

/** The footer placements; the values are the ones the backend stores (`services.branding.FOOTER_POSITIONS`). */
export type FooterPosition = "after_content" | "bottom_of_page";

/**
 * @param children The page's cards (and any announcements above them).
 * @param backgroundFileId The login background image, or null/undefined for none.
 * @param footerPosition The placement to use; when omitted the platform setting applies.
 */
export function SignedOutPage({ children, backgroundFileId, footerPosition }: {
  children: ReactNode;
  backgroundFileId?: string | null;
  footerPosition?: string | null;
}) {
  const platform = usePlatformBranding();
  const position: FooterPosition = (footerPosition ?? platform?.footer_position) === "bottom_of_page" ? "bottom_of_page" : "after_content";
  const background: CSSProperties | undefined = backgroundFileId
    ? { backgroundImage: `url(${fileUrl(backgroundFileId)})`, backgroundSize: "cover", backgroundPosition: "center" }
    : undefined;
  return (
    <div className="signed-out-page" data-footer-position={position} style={background}>
      <div className="signed-out-main">
        <div className="container stack signed-out-content">
          {children}
          {position === "after_content" && <AppFooter />}
        </div>
      </div>
      {position === "bottom_of_page" && <AppFooter />}
    </div>
  );
}
