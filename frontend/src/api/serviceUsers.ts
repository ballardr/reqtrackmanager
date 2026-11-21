/**
 * Module: api/serviceUsers
 *
 * The shapes of the service-user endpoints (`/api/v1/orgs/{id}/service-users`, `routers/orgs/service_users.py`) and
 * the label map of what the access review flags on one. A service user is an organisation's integration identity: no
 * password and no sign-in, with personal access tokens an organisation administrator issues.
 */
import { principalRef, type OrgRole, type Principal, type PrincipalRef } from "./types";

/** What the access review flags on a service user. */
export type ServiceUserFlag = "no_responsible" | "administrator";

export const SERVICE_USER_FLAG_LABEL: Record<ServiceUserFlag, string> = {
  no_responsible: "No responsible party",
  administrator: "Administrator rights",
};

export interface ServiceUser {
  user_id: string;
  name: string;
  description: string;
  /** The supplied notification address, or null when the account has only a generated one. */
  email: string | null;
  has_deliverable_email: boolean;
  is_active: boolean;
  is_archived: boolean;
  responsible: Principal | null;
  roles: OrgRole[];
  flags: ServiceUserFlag[];
  active_token_count: number;
  last_used_at: string | null;
  created_at: string;
  created_by_display_name: string | null;
}

/** The values of the create and edit forms. */
export interface ServiceUserDraft {
  name: string;
  description: string;
  email: string;
  responsible: PrincipalRef | null;
}

export const BLANK_SERVICE_USER: ServiceUserDraft = { name: "", description: "", email: "", responsible: null };

/** The draft an edit form starts from: the stored values, with a generated address shown as blank. */
export function draftFromServiceUser(user: ServiceUser): ServiceUserDraft {
  return {
    name: user.name, description: user.description, email: user.email ?? "",
    responsible: principalRef(user.responsible),
  };
}

export interface ServiceUserToken {
  id: string;
  name: string;
  token_prefix: string;
  allowed_projects: { id: string; name: string }[];
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
  created_by_display_name: string | null;
}

/** Returned once, at issue: the only response that carries the secret. */
export interface ServiceUserTokenCreated extends ServiceUserToken {
  token: string;
  notice: string;
}

export const serviceUsersPath = (organizationId: string) => `/api/v1/orgs/${organizationId}/service-users`;
