/**
 * Module: components/PoliciesLink
 *
 * A link to the Policies page that appears only when at least one policy is published, so a deployment with none
 * shows nothing. Used in the login pages' footer and the navigation rail's footer.
 */
import { Link } from "react-router-dom";

import { useStrings } from "../context/TerminologyContext";
import { usePublishedPolicies } from "../hooks/usePublishedPolicies";

/**
 * @param className Optional class for the link.
 */
export function PoliciesLink({ className }: { className?: string }) {
  const text = useStrings().policies;
  const { policies } = usePublishedPolicies();
  if (policies.length === 0) return null;
  return <Link to="/policies" className={className}>{text.footerLabel}</Link>;
}
