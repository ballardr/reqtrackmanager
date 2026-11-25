/**
 * Module: components/AppFooter
 *
 * The footer every page ends with: the server's company name (a website link after an optional prefix such as
 * "Hosted by"), postal address and identifier when set, the Policies link (always present: it holds the licences)
 * and the application and API versions, separated by `|`. Rendered by `Layout` and the signed-out shell
 * (`SignedOutPage`); signed-out pages show the application version only because the API version needs a session.
 *
 * Groups wrap in muted, centred lines at the end of the scrolling content. A separator is drawn only between two
 * groups on one line: after layout each group sharing a line with the previous one is marked (`data-joined`) and
 * the stylesheet draws the `|` in a zero-width gap, so marking never moves a group (no measure/mark loop).
 * A website is a link only when it has no scheme (`https://` is added) or is an `http(s)` address.
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useStrings } from "../context/TerminologyContext";
import { useBackendVersion } from "../hooks/useBackendVersion";
import { usePlatformBranding } from "../hooks/usePlatformBranding";
import { APP_VERSION } from "../version";

/**
 * The link target for a stored website, or null when it must not become a link. An address with no scheme
 * (`www.company.com`) gets `https://`; one with any scheme other than http(s) (`javascript:`) is never linked.
 */
function webHref(value: string): string | null {
  if (/^https?:\/\//i.test(value)) return value;
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) return null;
  return `https://${value}`;
}

/**
 * Whether each group shares its line with the group before it (the first group never does).
 *
 * @param tops The vertical offset of each group within the footer; groups on one line have equal offsets.
 */
function joinedToPrevious(tops: number[]): boolean[] {
  return tops.map((top, index) => index > 0 && top === tops[index - 1]);
}

/** The footer landmark; takes no props. */
export function AppFooter() {
  const strings = useStrings();
  const platform = usePlatformBranding();
  const backendVersion = useBackendVersion();
  const name = platform?.email_footer_company_name?.trim();
  const website = platform?.email_footer_website?.trim();
  // The address keeps its line breaks in storage; the footer shows it on one line.
  const address = platform?.email_footer_address?.replace(/\s*\n\s*/g, ", ").trim();
  const href = website ? webHref(website) : null;
  // The prefix ("Hosted by") belongs to a company name, so it needs one; the identifier follows the address.
  const prefix = name ? platform?.footer_prefix?.trim() : undefined;
  const companyId = platform?.company_id?.trim()
    ? [platform.company_id_label?.trim(), platform.company_id.trim()].filter(Boolean).join(" ")
    : undefined;
  // The company name is the website's link; with no name the website itself is the label.
  const company = name || website;
  const groups: ReactNode[] = [];
  if (company) {
    groups.push(
      <span key="company">
        {prefix && `${prefix} `}
        {href ? <a className="text-muted" href={href} target="_blank" rel="noopener noreferrer">{company}</a> : company}
      </span>,
    );
  }
  if (address) groups.push(<span key="address">{address}</span>);
  if (companyId) groups.push(<span key="companyId">{companyId}</span>);
  groups.push(<Link key="policies" className="text-muted" to="/policies">{strings.policies.footerLabel}</Link>);
  groups.push(<span key="versions">{strings.footer.version(APP_VERSION, backendVersion?.version ?? null)}</span>);
  const footerRef = useRef<HTMLElement>(null);
  const [joined, setJoined] = useState<boolean[]>([]);
  // Re-measured when the groups change (company details load after the first paint) and when any size changes (a
  // resize, a web font arriving); the state is replaced only when the result differs.
  const groupKeys = groups.map((_, index) => index).join();
  useLayoutEffect(() => {
    const footer = footerRef.current;
    if (!footer) return undefined;
    const measure = () => {
      const next = joinedToPrevious(Array.from(footer.children, (child) => (child as HTMLElement).offsetTop));
      setJoined((previous) => (previous.length === next.length && previous.every((value, index) => value === next[index]) ? previous : next));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(footer);
    Array.from(footer.children).forEach((child) => observer.observe(child));
    return () => observer.disconnect();
  }, [groupKeys]);
  return (
    <footer ref={footerRef} className="app-footer text-muted" aria-label={strings.footer.landmark}>
      {groups.map((group, index) => (
        <span key={index} className="app-footer-group" data-joined={joined[index] ? "true" : undefined}>{group}</span>
      ))}
    </footer>
  );
}
