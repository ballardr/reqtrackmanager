---
sidebar_position: 14
---

# Two-factor authentication

## Enrolling

From **Preferences → Security**, toggle **Enable 2FA**:

1. A QR code appears — scan it with an authenticator app (Google Authenticator, 1Password, and similar apps all work, since this uses the standard TOTP algorithm).
2. Enter the code the app generates to confirm. Enrollment isn't complete until this confirmation code is accepted — scanning the QR code alone leaves 2FA off.

| Two-factor authentication setup |
| --- |
| Scan the QR code with an authenticator app, then confirm with a generated code |
| ![Preferences Security tab showing the 2FA QR code and confirmation field](../../static/img/screenshots/two-factor-setup.png) |

## Signing in afterward

Once enabled, signing in becomes two steps: your password first, then a code from the authenticator app. See [Signing in](./signing-in.md).

## Disabling 2FA

Toggle **Enable 2FA** off from the same **Preferences → Security** tab. This immediately invalidates your current session — the next request logs you out and back in for a fresh one, by design (the same as a password change: a stale, already-open session shouldn't be able to silently ride out a security-relevant change made by someone with a stolen session).

## If your organisation requires it

If your organisation requires every member to have 2FA enabled (**Organisation admin → Advanced settings**) and you haven't set it up yet, you can still sign in and reach **Preferences → Security** to turn it on — but nothing else in that organisation works until you do. This is enforced by the server, not just suggested in the UI.

## Where this fits

See [Core Features → Two-factor authentication](../core-features/two-factor-authentication.md) for the underlying mechanics, and [Preferences and help](./preferences-and-help.md) for the rest of the Security tab.
