/**
 * Module: components/AuthCard
 *
 * The centred card every signed-out form page sits in (sign up, forgot password, reset password): a narrow
 * container with the card inside, rendered as a `<form>` when it has a submit handler so Enter submits. One
 * component so these pages keep the same width, spacing and form semantics (docs/ux-style-guide.md, one
 * component per pattern). The page footer (policies link, versions) sits beneath the card.
 */
import type { FormEvent, ReactNode } from "react";

import { AppFooter } from "./AppFooter";

/**
 * @param children The card's content.
 * @param onSubmit When given, the card is a `<form>` that calls this on submit; otherwise a plain `<div>`.
 */
export function AuthCard({ children, onSubmit }: { children: ReactNode; onSubmit?: (e: FormEvent) => void }) {
  return (
    <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
      {onSubmit ? (
        <form className="card stack" onSubmit={onSubmit}>
          {children}
        </form>
      ) : (
        <div className="card stack">{children}</div>
      )}
      <AppFooter />
    </div>
  );
}
