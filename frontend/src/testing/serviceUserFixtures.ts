/**
 * Module: testing/serviceUserFixtures
 *
 * Service users and tokens in the server's response shape, for stories of the service-user components.
 */
import type { ServiceUser, ServiceUserToken } from "../api/serviceUsers";

export const ORG_ID = "org-1";

export function buildServiceUser(overrides: Partial<ServiceUser> = {}): ServiceUser {
  return {
    user_id: "su-1", name: "Build agent", description: "Runs the nightly import.", email: null, has_deliverable_email: false,
    is_active: true, is_archived: false,
    responsible: { type: "org_group", id: "g-1", label: "Platform team", member_count: 3, exists: true },
    roles: ["member"], flags: [], active_token_count: 1, last_used_at: "2026-11-20T10:00:00Z",
    created_at: "2026-11-01T09:00:00Z", created_by_display_name: "Ana Lee", ...overrides,
  };
}

export function buildToken(overrides: Partial<ServiceUserToken> = {}): ServiceUserToken {
  return {
    id: "tok-1", name: "Nightly", token_prefix: "rtm_pat_ab12", allowed_projects: [],
    expires_at: "2099-01-01T00:00:00Z", revoked_at: null, last_used_at: null, created_at: "2026-11-02T09:00:00Z",
    created_by_display_name: "Ana Lee", ...overrides,
  };
}

export const SERVICE_USERS: ServiceUser[] = [
  buildServiceUser(),
  buildServiceUser({
    user_id: "su-2", name: "Report mailer", description: "", responsible: null, flags: ["no_responsible", "administrator"],
    roles: ["member", "org_admin"], active_token_count: 0, last_used_at: null, email: "reports@example.com", has_deliverable_email: true,
  }),
  buildServiceUser({ user_id: "su-3", name: "Retired job", is_active: false, active_token_count: 0, last_used_at: "2026-10-01T10:00:00Z" }),
];
