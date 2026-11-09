/**
 * Module: components/PoliciesLink
 *
 * A link to the Policies page that appears only when at least one policy can be read (a server policy, or for a
 * signed-in person an organisation policy), so a deployment with none shows nothing. Used in the login pages' footer and the navigation rail's footer.
 */
import { Link } from "react-router-dom";

import { useStrings } from "../context/TerminologyContext";
import { useMemberPolicies, usePublishedPolicies } from "../hooks/usePublishedPolicies";

/**
 * @param className Optional class for the link.
 */
export function PoliciesLink({ className }: { className?: string }) {
  const text = useStrings().policies;
  const { policies } = usePublishedPolicies();
  const { policies: memberPolicies } = useMemberPolicies();
  if (policies.length === 0 && memberPolicies.length === 0) return null;
  return <Link to="/policies" className={className}>{text.footerLabel}</Link>;
}
