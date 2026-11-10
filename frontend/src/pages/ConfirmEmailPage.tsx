/**
 * Module: pages/ConfirmEmailPage
 *
 * Signed-out page the link in the sign-up confirmation email opens (`/confirm-email#token=...`): it spends the link
 * (`POST /auth/confirm-email`) and says whether the address is now confirmed.
 *
 * Responsibilities: read the link's secret from the URL fragment and remove it from the address bar at once, send it
 * once, and show the outcome with a way to sign in.
 *
 * Design decisions: the secret is in the fragment, which browsers never send to a server, so it stays out of access
 * logs and referrers. The page does not sign the person in: they sign in with the password they chose.
 */
import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import { AuthCard } from "../components/AuthCard";
import { t } from "../i18n/strings";

const strings = t();

type Outcome = "working" | "done" | "invalid" | "missing";

/**
 * @returns The secret in the current URL fragment (`#token=...`), or `""` when there is none.
 */
function tokenFromFragment(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
}

export function ConfirmEmailPage() {
  const [token] = useState(tokenFromFragment);
  const [outcome, setOutcome] = useState<Outcome>(token ? "working" : "missing");
  const sent = useRef(false);

  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
    if (!token || sent.current) return;
    sent.current = true; // the link works once: a repeated effect run must not spend it twice
    api
      .post("/api/v1/auth/confirm-email", { token })
      .then(() => setOutcome("done"))
      .catch((err: unknown) => setOutcome(err instanceof ApiError && err.status === 429 ? "working" : "invalid"));
  }, [token]);

  return (
    <AuthCard>
      <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.confirmEmail.title}</h1>
      {outcome === "working" && <p role="status">{strings.confirmEmail.working}</p>}
      {outcome === "done" && <p role="status">{strings.confirmEmail.done}</p>}
      {outcome === "invalid" && <p role="alert">{strings.confirmEmail.invalid}</p>}
      {outcome === "missing" && <p role="alert">{strings.confirmEmail.missing}</p>}
      <a className="btn" href="/login">
        {strings.confirmEmail.signIn}
      </a>
    </AuthCard>
  );
}
