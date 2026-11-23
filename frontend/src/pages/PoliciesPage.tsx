/**
 * Module: pages/PoliciesPage
 *
 * The Policies page: the published policies, one at a time, chosen from a side menu. It is reachable without signing in (a
 * signed-out visitor reads only the public endpoints); a signed-in person also sees, under each organisation's name, the policies
 * of the organisations they may read. Every body is rendered through `PolicyBodyView`.
 *
 * Responsibilities: list the readable policies (the server's first, then one group per organisation) and last the built-in
 * Licences group (product licence, third-party components, fonts), which is not a policy; show the selected policy (the first,
 * or Licences when none is readable) with its effective date and version. `/policies/:policyId` and
 * `/policies/licences/:section` are read from the location so the signed-out page, outside a route, resolves them too.
 */
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { api } from "../api/client";
import type { MemberPolicy, MemberPolicySummary, PendingPolicy, PublicPolicy } from "../api/types";
import { LicencesSection } from "../components/LicencesPanel";
import { PolicyBodyView } from "../components/PolicyBodyView";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useAcceptPolicy, usePolicyAcceptance } from "../hooks/usePolicyAcceptance";
import { useMemberPolicies, usePublishedPolicies } from "../hooks/usePublishedPolicies";
import { formatPlainDate } from "../utils/localDate";
import { LICENCE_SECTIONS, parsePoliciesPath, type LicenceSection } from "../utils/policiesPath";

/** Which read a policy comes from: the public server policies, or the signed-in person's organisations. */
type PolicySource = "server" | "organisation";

/** The panel above a policy the person must accept: why, and the Accept action, shown only for the version being read so a changed text is not accepted unseen. */
function AcceptPanel({ policy }: { policy: PendingPolicy }) {
  const text = useStrings().policies;
  const accept = useAcceptPolicy();
  return (
    <section className="card stack" aria-label={text.acceptHeading}>
      <strong>{text.acceptHeading}</strong>
      <p style={{ margin: 0 }}>{text.acceptBody(policy.version)}</p>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-primary" onClick={() => void accept(policy)}>{text.accept}</button>
      </div>
    </section>
  );
}

function SelectedPolicy({ policyId, source }: { policyId: string; source: PolicySource }) {
  const text = useStrings().policies;
  const { pending } = usePolicyAcceptance();
  const [state, setState] = useState<{ id: string; policy: PublicPolicy | MemberPolicy | null; failed: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    const path = source === "server" ? `/api/v1/public/policies/${policyId}` : `/api/v1/policies/mine/${policyId}`;
    api.get<PublicPolicy | MemberPolicy>(path).then(
      (policy) => { if (!cancelled) setState({ id: policyId, policy, failed: false }); },
      () => { if (!cancelled) setState({ id: policyId, policy: null, failed: true }); },
    );
    return () => { cancelled = true; };
  }, [policyId, source]);
  if (!state || state.id !== policyId) return <Spinner />;
  if (!state.policy) return <div role="alert">{text.notFound}</div>;
  const { policy } = state;
  const toAccept = pending.find((p) => p.id === policy.id && p.version === policy.version);
  return (
    <article className="stack" aria-labelledby="policy-title">
      {toAccept && <AcceptPanel policy={toAccept} />}
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <h2 id="policy-title" style={{ margin: 0 }}>{policy.title}</h2>
        <div className="text-muted">
          {"organization_name" in policy && <span>{policy.organization_name}. </span>}
          {policy.effective_from && <span>{text.effectiveFrom(formatPlainDate(policy.effective_from))}. </span>}
          <span>{text.versionLine(policy.version, new Date(policy.published_at).toLocaleDateString())}</span>
        </div>
      </div>
      <PolicyBodyView body={policy.body} />
    </article>
  );
}

/** The menu key of a licence section (a policy's key is its id, which never has this shape). */
const licenceKey = (section: LicenceSection) => `licences-${section}`;

/** The menu: server policies as plain links, then one expandable group per organisation (one link when it has a single policy), then Licences. */
function menuGroups(
  server: { id: string; title: string }[], member: MemberPolicySummary[], line: (organisation: string, title: string) => string,
  licences: { group: string; sections: Record<LicenceSection, string> },
): ResourceMenuGroupDef<string>[] {
  const groups: ResourceMenuGroupDef<string>[] = server.map((p) => ({ key: p.id, label: p.title, href: `/policies/${p.id}` }));
  const byOrganisation = new Map<string, MemberPolicySummary[]>();
  for (const p of member) byOrganisation.set(p.organization_id, [...(byOrganisation.get(p.organization_id) ?? []), p]);
  for (const [organizationId, rows] of byOrganisation) {
    const children = rows.map((p) => ({ key: p.id, label: p.title, href: `/policies/${p.id}` }));
    groups.push(
      rows.length === 1
        ? { key: rows[0].id, label: line(rows[0].organization_name, rows[0].title), href: children[0].href }
        : { key: `organisation:${organizationId}`, label: rows[0].organization_name, href: children[0].href, children },
    );
  }
  groups.push({
    key: "licences", label: licences.group, href: `/policies/licences/${LICENCE_SECTIONS[0]}`,
    children: LICENCE_SECTIONS.map((section) => ({ key: licenceKey(section), label: licences.sections[section], href: `/policies/licences/${section}` })),
  });
  return groups;
}

export function PoliciesPage() {
  const text = useStrings().policies;
  const licences = useStrings().licences;
  const selection = parsePoliciesPath(useLocation().pathname);
  const server = usePublishedPolicies();
  const member = useMemberPolicies();
  if (!server.loaded || !member.loaded) return <Spinner />;
  const all: { id: string; source: PolicySource }[] = [
    ...server.policies.map((p) => ({ id: p.id, source: "server" as const })),
    ...member.policies.map((p) => ({ id: p.id, source: "organisation" as const })),
  ];
  // An address naming a policy that is not readable shows the first one, so the page never dead-ends; with no policy
  // readable, the Licences group is what there is to show.
  const policy = selection.kind === "policy" ? (all.find((p) => p.id === selection.id) ?? all[0]) : undefined;
  const section: LicenceSection = selection.kind === "licences" ? selection.section : LICENCE_SECTIONS[0];
  const active = policy ? policy.id : licenceKey(section);
  return (
    <ResourceMenu
      title={text.heading} ariaLabel={text.navLabel}
      groups={menuGroups(server.policies, member.policies, text.orgPolicyLine, {
        group: licences.group,
        sections: { product: licences.productSection, components: licences.componentsSection, fonts: licences.fontsSection },
      })}
      active={active}
    >
      {policy ? <SelectedPolicy policyId={policy.id} source={policy.source} /> : <LicencesSection section={section} />}
    </ResourceMenu>
  );
}

/** The page for someone who is not signed in: the same content in a plain container, with a way to the sign-in page. */
export function PublicPoliciesPage() {
  const strings = useStrings();
  return (
    <div className="container stack" style={{ paddingTop: "2rem" }}>
      <div><Link to="/login">{strings.passwordReset.backToLogin}</Link></div>
      <PoliciesPage />
    </div>
  );
}
