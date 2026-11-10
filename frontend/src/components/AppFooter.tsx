/**
 * Module: components/AppFooter
 *
 * The footer every page ends with, signed in or not: the server's company name (a link to its website, after an
 * optional prefix such as "Hosted by"), postal address and company identifier when set, the link to the published policies when any can be read, and the application and API
 * versions, separated by `|`.
 *
 * Responsibilities: lay the groups out in one muted, wrapping line at the end of the page's scrolling content (never
 * fixed, so it takes no viewport height); a group that is absent leaves no separator. Rendered by `Layout` for signed-in pages and by the signed-out page shells
 * (`AuthCard`, the sign-in pages). The API version needs a session, so signed-out pages show the application version
 * only. Company details come from the public platform branding read; a website is a link only when it has no
 * scheme (then `https://` is added) or is an `http(s)` address.
 */
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useStrings } from "../context/TerminologyContext";
import { useBackendVersion } from "../hooks/useBackendVersion";
import { usePlatformBranding } from "../hooks/usePlatformBranding";
import { useMemberPolicies, usePublishedPolicies } from "../hooks/usePublishedPolicies";
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

/** The footer landmark; takes no props. */
export function AppFooter() {
  const strings = useStrings();
  const platform = usePlatformBranding();
  const backendVersion = useBackendVersion();
  const { policies: serverPolicies } = usePublishedPolicies();
  const { policies: memberPolicies } = useMemberPolicies();
  const hasPolicies = serverPolicies.length > 0 || memberPolicies.length > 0;
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
  if (hasPolicies) groups.push(<Link key="policies" className="text-muted" to="/policies">{strings.policies.footerLabel}</Link>);
  groups.push(<span key="versions">{strings.footer.version(APP_VERSION, backendVersion?.version ?? null)}</span>);
  return (
    <footer className="app-footer text-muted" aria-label={strings.footer.landmark}>
      {groups.map((group, index) => (
        <Fragment key={index}>
          {index > 0 && <span aria-hidden="true">|</span>}
          {group}
        </Fragment>
      ))}
    </footer>
  );
}
