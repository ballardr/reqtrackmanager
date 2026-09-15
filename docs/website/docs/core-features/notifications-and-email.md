---
sidebar_position: 6
---

# Notifications and email

## In-app notifications

The bell icon in the top bar shows recent notifications — project joins, stage transitions, change-request activity, password changes, permission grants, and more — with an unread-count badge. Clicking a notification marks it read and, for anything about a specific requirement, change request, or project, jumps straight to it; **Mark all read** clears every unread one without navigating anywhere. The full notification history — searchable, not limited to the dropdown's recent slice — lives on the **Notifications** page in the nav's Global section.

## Per-type preferences and digests

**Preferences → Notification preferences** lets each person choose, per notification type, whether they want it in-app, by email, or both, and whether email notifications arrive instantly or batched into a daily digest — so nobody has to choose between "know everything immediately" and "silence."

| Notification preferences |
| --- |
| Per-type in-app/email toggles and instant-vs-digest delivery |
| ![Notification preferences page with per-type in-app and email toggles](../../static/img/screenshots/notification-preferences.png) |

## Outgoing email

Outgoing email is a branded, self-contained HTML template — light/dark theme aware, with a plain-text fallback and an embedded (not externally hosted) logo — that resolves an organisation's own branding, falling back to the platform default. Every email includes a one-click, no-login **unsubscribe** link that updates the same preference the logged-in Preferences page controls, logged to the audit trail either way.

```mermaid
flowchart LR
    Event[Notifiable event occurs] --> Pref{Preference for this type?}
    Pref -->|In-app| Bell["Bell dropdown + Notifications page"]
    Pref -->|"Email, instant"| Send[Send branded email now]
    Pref -->|"Email, digest"| Queue[Queue for daily digest]
    Queue --> Digest[Daily digest email]
    Send --> Unsub["Unsubscribe link (no login required)"]
    Digest --> Unsub
    Unsub --> Audit["Preference updated + audit log entry"]
```

## Where this fits

See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md) for the underlying model, and [Workflows → Notifications](../workflows/notifications.md) for the end-to-end task walkthrough.
