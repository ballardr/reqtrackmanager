"""
Module: services.email_templates

Renders outgoing HTML and plain-text email bodies from the Jinja2 templates in `backend/app/templates/email/`
(docs/decisions.md, "HTML email template system", has the safety reasoning).

Design decisions:
- Templates load only from static files (`FileSystemLoader`), never from a runtime string
  (`Environment.from_string`): organisation or user text (organisation name, header title, footer address,
  notification title and body) is passed only as data to `render(**context)`, never compiled as template
  source. That rules out server-side template injection, so a `SandboxedEnvironment` is unnecessary.
- `autoescape` is always on, restricted by `select_autoescape` to `.html.jinja` (the `.txt.jinja` siblings are
  never markup). No template uses `|safe` or `markupsafe.Markup(...)` on organisation or user data; the one
  near-case, turning `email_footer_address` newlines into `<br>`, uses the `nl2br` filter, which escapes first
  and marks the escaped result `Markup` afterwards.
- The `xmlattr` filter is not used in any template.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

if TYPE_CHECKING:
    from app.services.email_branding import EmailBranding

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html.jinja",), default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _nl2br(value: str | None) -> Markup:
    """Converts embedded newlines to `<br>` tags, safely: escapes the raw
    value first and only marks the already-escaped pieces as safe HTML
    when joining them — never the other way round (mark-safe-then-hope)."""
    if not value:
        return Markup("")
    return Markup("<br>\n").join(escape(value).split("\n"))


_env.filters["nl2br"] = _nl2br


def render_email(
    template_name: str, *, branding: EmailBranding, unsubscribe_url: str | None = None, **content: object
) -> tuple[str, str]:
    """Renders one email's HTML and plain-text bodies from a matching
    `<template_name>.html.jinja` / `<template_name>.txt.jinja` pair.

    Args:
        template_name: Base name shared by the template pair, e.g.
            `"notification"`.
        branding: Resolved branding (`services.email_branding.
            resolve_email_branding`) — injected into every template's
            context as `branding`, alongside the derived `logo_src`
            (`"cid:brand_logo"` when a logo is configured, else omitted
            from the header entirely) and the current year for the
            footer's copyright line.
        unsubscribe_url: The recipient's one-click unsubscribe link
            (`security.create_email_unsubscribe_token`), or `None` to omit
            the footer link entirely (e.g. the "send test email" action,
            which isn't a notification a recipient needs to opt out of).
        **content: Template-specific variables (e.g. `title`/`body_text`
            for a notification, `items`/`cta_url` for a digest).

    Returns:
        A `(html, text)` tuple.
    """
    context = {
        "branding": branding,
        "logo_src": "cid:brand_logo" if branding.logo_bytes else None,
        "unsubscribe_url": unsubscribe_url,
        "now_year": datetime.now(UTC).year,
        **content,
    }
    html = _env.get_template(f"{template_name}.html.jinja").render(**context)
    text = _env.get_template(f"{template_name}.txt.jinja").render(**context)
    return html, text


def render_page(template_name: str, *, branding: EmailBranding, **content: object) -> str:
    """Renders a standalone HTML page (not an email) from
    `<template_name>.html.jinja` — used only by the one-click-unsubscribe
    landing page (`routers/notifications.py::unsubscribe`), which returns
    HTML directly to a browser rather than sending mail."""
    context = {"branding": branding, "logo_src": None, "unsubscribe_url": None, "now_year": datetime.now(UTC).year, **content}
    return _env.get_template(f"{template_name}.html.jinja").render(**context)
