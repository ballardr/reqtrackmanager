/**
 * Module: components/AuthCard
 *
 * The centred card every signed-out form page sits in (sign up, forgot password, reset password): rendered as a
 * `<form>` when it has a submit handler so Enter submits, one component for one width, spacing and semantics. The
 * page shell and footer come from `SignedOutPage`.
 */
import type { FormEvent, ReactNode } from "react";

import { SignedOutPage } from "./SignedOutPage";

/**
 * @param children The card's content.
 * @param onSubmit When given, the card is a `<form>` that calls this on submit; otherwise a plain `<div>`.
 */
export function AuthCard({ children, onSubmit }: { children: ReactNode; onSubmit?: (e: FormEvent) => void }) {
  return (
    <SignedOutPage>
      {onSubmit ? (
        <form className="card stack" onSubmit={onSubmit}>
          {children}
        </form>
      ) : (
        <div className="card stack">{children}</div>
      )}
    </SignedOutPage>
  );
}
