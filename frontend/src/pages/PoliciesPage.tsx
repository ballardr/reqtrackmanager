/**
 * Module: pages/PoliciesPage
 *
 * The Policies page: the published policies, one at a time, chosen from a side menu. Reachable without signing in
 * (the people a privacy policy concerns most have not signed in yet), so it reads only the public endpoints and
 * renders each body through `PolicyBodyView`.
 *
 * Responsibilities: list the published policies, show the selected one (the first by default) with its effective
 * date and version, and say so plainly when none is published. The address `/policies/:policyId` selects one.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { PublicPolicy } from "../api/types";
import { PolicyBodyView } from "../components/PolicyBodyView";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { usePublishedPolicies } from "../hooks/usePublishedPolicies";
import { formatPlainDate } from "../utils/localDate";

function SelectedPolicy({ policyId }: { policyId: string }) {
  const text = useStrings().policies;
  const [state, setState] = useState<{ id: string; policy: PublicPolicy | null; failed: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.get<PublicPolicy>(`/api/v1/public/policies/${policyId}`).then(
      (policy) => { if (!cancelled) setState({ id: policyId, policy, failed: false }); },
      () => { if (!cancelled) setState({ id: policyId, policy: null, failed: true }); },
    );
    return () => { cancelled = true; };
  }, [policyId]);
  if (!state || state.id !== policyId) return <Spinner />;
  if (!state.policy) return <div role="alert">{text.notFound}</div>;
  const { policy } = state;
  return (
    <article className="stack" aria-labelledby="policy-title">
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <h2 id="policy-title" style={{ margin: 0 }}>{policy.title}</h2>
        <div className="text-muted">
          {policy.effective_from && <span>{text.effectiveFrom(formatPlainDate(policy.effective_from))}. </span>}
          <span>{text.versionLine(policy.version, new Date(policy.published_at).toLocaleDateString())}</span>
        </div>
      </div>
      <PolicyBodyView body={policy.body} />
    </article>
  );
}

export function PoliciesPage() {
  const text = useStrings().policies;
  const { policyId } = useParams<{ policyId?: string }>();
  const { policies, loaded } = usePublishedPolicies();
  if (!loaded) return <Spinner />;
  if (policies.length === 0) {
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{text.heading}</h1>
        <div className="text-muted">{text.noneBody}</div>
      </div>
    );
  }
  const active = policies.find((p) => p.id === policyId) ?? policies[0];
  const groups: ResourceMenuGroupDef<string>[] = policies.map((p) => ({ key: p.id, label: p.title, href: `/policies/${p.id}` }));
  return (
    <ResourceMenu title={text.heading} ariaLabel={text.navLabel} groups={groups} active={active.id}>
      <SelectedPolicy policyId={active.id} />
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
