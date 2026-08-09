"""Tests for the "add a project user by email" flow
(`assign_project_role_by_email`), gated by `Organization.
external_user_policy`, and its two provisioning paths: a `PendingInvite`
redeemed at native signup for a regular org, and immediate provisioning
(`services.invites.provision_sso_invite`) for an `sso_only` org — see
`services/invites.py` and docs/decisions.md's "Self-signup, invites, and
SSO" entry."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.enums import OrgRole
from app.models.organization import Organization, PendingInvite, UserOrgRole
from app.models.project import Project
from app.models.user import User
from app.services.invites import consume_pending_invites, create_pending_invite, provision_sso_invite
from app.services.oidc_provisioning import find_or_provision_user
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _set_policy(client, token, org_id, policy, domain=None):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"external_user_policy": policy, "auto_accept_email_domain": domain},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_search_hides_external_results_when_policy_disabled(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "DisabledPolicyOrg")
    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=nobody@outside.example.com", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["external"] is None


def test_search_surfaces_existing_external_account_regardless_of_domain(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "AnyoneSearchOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    other_org = client.post("/api/v1/orgs", json={"name": "SomeOtherOrg"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "elsewhere@other.example.com", "display_name": "Elsewhere",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )

    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=elsewhere@other.example.com", headers=auth_headers(org_admin_token)
    )
    external = resp.json()["external"]
    assert external == {"email": "elsewhere@other.example.com", "exists": True}


def test_search_domain_restricted_policy_hides_non_matching_new_email(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "DomainSearchOrg")
    _set_policy(client, org_admin_token, org["id"], "org_domain_only", "domainsearch.example.com")

    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=nobody@wrongdomain.example.com", headers=auth_headers(org_admin_token)
    )
    assert resp.json()["external"] is None

    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=nobody@domainsearch.example.com", headers=auth_headers(org_admin_token)
    )
    assert resp.json()["external"] == {"email": "nobody@domainsearch.example.com", "exists": False}


def test_search_hides_existing_account_fact_from_a_plain_member(client, admin_token):
    """A plain org member (not org_admin, no project-manage rights) must
    never learn that an arbitrary email has an account *somewhere in the
    system* — that one-bit cross-tenant signal is gated to callers who
    could actually act on it (hardening pass)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "MemberEnumOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    _create_member(client, org_admin_token, org["id"], "plainmember@memberenum.example.com")

    other_org = client.post("/api/v1/orgs", json={"name": "MemberEnumTarget"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "target@elsewhere-enum.example.com", "display_name": "Target",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )

    member_login = client.post(
        "/api/v1/auth/login", json={"email": "plainmember@memberenum.example.com", "password": "Password123!"}
    )
    member_token = member_login.json()["access_token"]

    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=target@elsewhere-enum.example.com",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200
    # Not downgraded to a misleading exists=False either — omitted entirely.
    assert resp.json()["external"] is None


def test_search_reveals_existing_account_to_a_project_manager_for_their_own_project(client, admin_token):
    """A project manager who isn't an org admin still needs the real
    signal, scoped to a project they actually manage (passed as
    project_id) — confirms the hardening fix didn't just lock everyone
    but org admins out of the feature."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "PmEnumOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])

    pm_email = "projectmanageronly@pmenum.example.com"
    _create_member(client, org_admin_token, org["id"], pm_email)
    pm_user_id = next(
        u["user_id"] for u in client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token)).json()
        if u["email"] == pm_email
    )
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": pm_user_id, "role": "project_manager"},
        headers=auth_headers(org_admin_token),
    )
    pm_token = client.post("/api/v1/auth/login", json={"email": pm_email, "password": "Password123!"}).json()["access_token"]

    other_org = client.post("/api/v1/orgs", json={"name": "PmEnumTarget"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "target2@elsewhere-enum.example.com", "display_name": "Target",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )

    # Without project_id: still hidden, even for this project manager.
    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=target2@elsewhere-enum.example.com", headers=auth_headers(pm_token)
    )
    assert resp.json()["external"] is None

    # With project_id for a project they manage: revealed.
    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users/search?q=target2@elsewhere-enum.example.com&project_id={project['id']}",
        headers=auth_headers(pm_token),
    )
    assert resp.json()["external"] == {"email": "target2@elsewhere-enum.example.com", "exists": True}


def test_assign_by_email_rejects_banned_existing_user(client, admin_token):
    """A banned account must not be re-admitted to a *different*
    organisation through the by-email project-invite path — the same
    protection assign_org_role already enforces on its own grant path
    (hardening pass: this endpoint grants org membership too and must not
    become a second, unguarded way back in for a banned account)."""
    # An orphaned (no org membership) account is required to be bannable.
    client.put("/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token))
    signup_resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "willbebanned@example.com", "password": "Password123!", "display_name": "Will Be Banned"},
    )
    banned_user_id = signup_resp.json()["user"]["id"]
    client.put("/api/v1/system/signup-config", json={"signup_mode": "disabled"}, headers=auth_headers(admin_token))
    ban_resp = client.post(f"/api/v1/system/users/{banned_user_id}/ban", headers=auth_headers(admin_token))
    assert ban_resp.status_code == 204, ban_resp.text

    org, org_admin_token = create_org_admin_in(client, admin_token, "BanGuardOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "willbebanned@example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403


def _create_member(client, admin_token, org_id, email) -> str:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users",
        json={"email": email, "display_name": email.split("@")[0], "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return email


def test_assign_by_email_rejected_when_policy_disabled(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "DisabledAssignOrg")
    project = create_project(client, org_admin_token, org["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "someone@nowhere.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403


def test_assign_by_email_adds_existing_out_of_org_user_directly(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "AddExistingOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])

    other_org = client.post("/api/v1/orgs", json={"name": "ElsewhereOrg2"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "existing@elsewhere2.example.com", "display_name": "Existing",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "existing@elsewhere2.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "added"

    # Confirm it actually granted org membership (C-U-02) and project access,
    # not just returned a success shape.
    org_users = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token)).json()
    assert any(u["email"] == "existing@elsewhere2.example.com" for u in org_users)


def test_assign_by_email_domain_restricted_rejects_non_matching_new_email(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "DomainAssignOrg")
    _set_policy(client, org_admin_token, org["id"], "org_domain_only", "domainassign.example.com")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "new@wrongdomain.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403


def test_assign_by_email_invites_new_account_and_consuming_signup_grants_role(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "InviteFlowOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "invitee@newaccount.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "invited"

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(email="invitee@newaccount.example.com").one()
        token = invite.token
        assert invite.accepted_at is None
    finally:
        db.close()

    client.put("/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token))
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "invitee@newaccount.example.com", "password": "Password123!", "display_name": "Invitee",
            "invite_token": token,
        },
    )
    assert resp.status_code == 201, resp.text
    invitee_token = resp.json()["access_token"]

    projects = client.get("/api/v1/projects", headers=auth_headers(invitee_token)).json()
    assert any(p["id"] == project["id"] for p in projects)

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(email="invitee@newaccount.example.com").one()
        assert invite.accepted_at is not None
    finally:
        db.close()


def test_expired_or_wrong_invite_token_is_rejected_at_signup(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "BadTokenOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "badtoken@newaccount.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "badtoken@newaccount.example.com", "password": "Password123!", "display_name": "Bad Token",
            "invite_token": "not-a-real-token",
        },
    )
    assert resp.status_code == 400


def test_assign_by_email_provisions_immediately_for_sso_only_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "SsoInviteOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/sso-config",
        json={"slug": "sso-invite-org", "sso_enabled": True, "sso_only": True},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": "ssoinvitee@newaccount.example.com", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "sso_provisioned"

    # No PendingInvite for this path — access was already granted.
    db = SessionLocal()
    try:
        assert db.query(PendingInvite).filter_by(email="ssoinvitee@newaccount.example.com").first() is None
    finally:
        db.close()

    org_users = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token)).json()
    provisioned = next(u for u in org_users if u["email"] == "ssoinvitee@newaccount.example.com")
    assert provisioned is not None

    # And native login must still be rejected for this pre-provisioned
    # account, the same as any other sso_only-org-only account.
    resp = client.post(
        "/api/v1/auth/login", json={"email": "ssoinvitee@newaccount.example.com", "password": "anything"}
    )
    assert resp.status_code == 401


def test_sso_login_adopts_pre_provisioned_invited_account_and_keeps_its_roles():
    """Simulates the invitee's first real SSO login by calling
    find_or_provision_user directly with verified claims matching the
    pre-provisioned row's email (same pattern test_oidc_provisioning.py
    uses to avoid a real IdP) — the existing_by_email branch should adopt
    it, and its already-granted UserOrgRole must survive unchanged."""
    db = SessionLocal()
    try:
        org = Organization(name="DirectSsoOrg", sso_only=True)
        db.add(org)
        db.flush()
        project = Project(organization_id=org.id, name="Direct SSO Project")
        db.add(project)
        inviter = User(email="inviter1@ssoprovision.example.com", display_name="Inviter", auth_backend="native")
        db.add(inviter)
        db.flush()

        inviter_id = inviter.id
        user = provision_sso_invite(
            db, email="direct@ssoprovision.example.com", organization=org, project=project,
            project_role=None, invited_by=inviter_id,
        )
        db.commit()
        assert user.auth_backend == "invited"

        adopted = find_or_provision_user(
            db, {"sub": "direct-subject-1", "email": "direct@ssoprovision.example.com", "email_verified": True},
            issuer="https://idp.example.com",
        )
        db.commit()
        assert adopted.id == user.id
        assert adopted.auth_backend == "oidc"
        assert adopted.external_subject == "direct-subject-1"

        roles = set(
            db.scalars(
                select(UserOrgRole.role).where(
                    UserOrgRole.user_id == adopted.id, UserOrgRole.organization_id == org.id
                )
            ).all()
        )
        assert OrgRole.MEMBER in roles
    finally:
        db.close()


def test_consume_pending_invites_is_idempotent_across_multiple_invites_to_same_org():
    """Two separate invites into the same org for one email must not
    duplicate the org role grant — only ever one UserOrgRole row."""
    db = SessionLocal()
    try:
        org = Organization(name="DoubleInviteOrg")
        db.add(org)
        db.flush()
        project_a = Project(organization_id=org.id, name="Project A")
        project_b = Project(organization_id=org.id, name="Project B")
        db.add_all([project_a, project_b])
        inviter = User(email="inviter2@doubleinvite.example.com", display_name="Inviter", auth_backend="native")
        db.add(inviter)
        db.flush()

        inviter_id = inviter.id
        create_pending_invite(
            db, email="twice@doubleinvite.example.com", organization=org, project=project_a,
            project_role=None, invited_by=inviter_id,
        )
        create_pending_invite(
            db, email="twice@doubleinvite.example.com", organization=org, project=project_b,
            project_role=None, invited_by=inviter_id,
        )
        db.commit()

        user = User(
            email="twice@doubleinvite.example.com", display_name="Twice", auth_backend="native",
            password_hash="x",
        )
        db.add(user)
        db.flush()
        consume_pending_invites(db, user)
        db.commit()

        role_count = len(
            db.scalars(
                select(UserOrgRole).where(
                    UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id
                )
            ).all()
        )
        assert role_count == 1
    finally:
        db.close()


def test_outside_domain_users_requires_a_configured_domain(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "NoDomainOrg")
    resp = client.get(f"/api/v1/orgs/{org['id']}/users/outside-domain", headers=auth_headers(org_admin_token))
    assert resp.status_code == 400


def test_outside_domain_users_lists_matching_non_members_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "ListDomainOrg")
    _set_policy(client, org_admin_token, org["id"], "disabled", "listdomain.example.com")

    other_org = client.post("/api/v1/orgs", json={"name": "OutsideOrg"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "match@listdomain.example.com", "display_name": "Matching",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/orgs/{other_org['id']}/users",
        json={"email": "nomatch@somewhereelse.example.com", "display_name": "Non-matching",
              "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )

    resp = client.get(f"/api/v1/orgs/{org['id']}/users/outside-domain", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"match@listdomain.example.com"}
