/**
 * Module: pages/PoliciesPage
 *
 * The Policies page: the published policies, one at a time, chosen from a side menu. Reachable without signing in
 * (the people a privacy policy concerns most have not signed in yet), so a signed-out visitor reads only the public
 * endpoints. A signed-in person also sees, under the organisation's name, the policies of each organisation they
 * belong to that they may read. Every body is rendered through `PolicyBodyView`.
 *
 * Responsibilities: list the readable policies (the server's first, then one group per organisation), show the
 * selected one (the first by default) with its effective date and version. With none readable the page does not
 * exist: it redirects to the front page. The address `/policies/:policyId` selects one.
 */
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { MemberPolicy, MemberPolicySummary, PublicPolicy } from "../api/types";
import { PolicyBodyView } from "../components/PolicyBodyView";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useMemberPolicies, usePublishedPolicies } from "../hooks/usePublishedPolicies";
import { formatPlainDate } from "../utils/localDate";

/** Which read a policy comes from: the public server policies, or the signed-in person's organisations. */
type PolicySource = "server" | "organisation";

function SelectedPolicy({ policyId, source }: { policyId: string; source: PolicySource }) {
  const text = useStrings().policies;
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
  return (
    <article className="stack" aria-labelledby="policy-title">
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

/**
 * The menu: server policies as plain links, then one expandable group per organisation (an organisation with a
 * single policy is one link naming both).
 */
function menuGroups(
  server: { id: string; title: string }[], member: MemberPolicySummary[], line: (organisation: string, title: string) => string,
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
  return groups;
}

export function PoliciesPage() {
  const text = useStrings().policies;
  const { policyId } = useParams<{ policyId?: string }>();
  const server = usePublishedPolicies();
  const member = useMemberPolicies();
  if (!server.loaded || !member.loaded) return <Spinner />;
  // With nothing to read there is no page: the address goes to the front page, which is the sign-in page for
  // someone signed out and the project list for someone signed in.
  if (server.policies.length === 0 && member.policies.length === 0) return <Navigate to="/" replace />;
  const all: { id: string; source: PolicySource }[] = [
    ...server.policies.map((p) => ({ id: p.id, source: "server" as const })),
    ...member.policies.map((p) => ({ id: p.id, source: "organisation" as const })),
  ];
  const active = all.find((p) => p.id === policyId) ?? all[0];
  return (
    <ResourceMenu
      title={text.heading} ariaLabel={text.navLabel} groups={menuGroups(server.policies, member.policies, text.orgPolicyLine)}
      active={active.id}
    >
      <SelectedPolicy policyId={active.id} source={active.source} />
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
