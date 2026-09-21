---
slug: /
sidebar_position: 1
title: Open Source Requirements Management Software (IBM DOORS Alternative)
sidebar_label: Overview
description: Open-source, self-hostable requirements management — a formal, auditable alternative to IBM DOORS, Jama Connect, Polarion, and Codebeamer, with full requirements traceability, review/approval workflows, and audit trails.
keywords:
  - requirements management
  - requirements management software
  - requirements management tool
  - open source requirements management
  - self-hosted requirements management
  - engineering requirements management system
  - ERMS
  - open source ALM
  - application lifecycle management
  - IBM DOORS alternative
  - IBM DOORS Next alternative
  - Jama Connect alternative
  - Jama Software alternative
  - Polarion alternative
  - Codebeamer alternative
  - Helix RM alternative
  - Visure Solutions alternative
  - ReqView alternative
  - requirements traceability matrix
  - requirements traceability
  - requirements baseline
  - change request management
  - change management workflow
  - requirements version control
  - requirements review workflow
  - requirement approval workflow
  - audit trail software
  - role-based access control
  - SOC 2 compliance software
  - ISO 27001 compliance tracking
  - OIDC single sign-on
  - SCIM provisioning
  - two-factor authentication
  - CSV requirements import export
  - regulated software requirements management
  - hardware requirements management
  - firmware requirements management
  - medical device requirements management
  - aerospace requirements management
  - automotive requirements management
  - AI assistant MCP integration
---

import Head from '@docusaurus/Head';

<Head>
  <script type="application/ld+json">{`
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      "name": "ReqTrackManager",
      "applicationCategory": "BusinessApplication",
      "operatingSystem": "Linux, macOS, Windows (via Docker)",
      "description": "Open-source, self-hostable engineering requirements management system (ERMS) - a formal, auditable alternative to IBM DOORS, Jama Connect, Polarion, and Codebeamer.",
      "url": "https://ballardr.github.io/reqtrackmanager/",
      "codeRepository": "https://github.com/ballardr/reqtrackmanager",
      "license": "https://github.com/ballardr/reqtrackmanager/blob/main/LICENSE",
      "offers": {
        "@type": "Offer",
        "price": "0",
        "priceCurrency": "USD"
      }
    }
  `}</script>
</Head>

# Overview

ReqTrackManager is an open-source engineering requirements management system (ERMS) — a formal, collaborative alternative to expensive legacy enterprise requirements tools for product teams that can't justify that cost, without falling back to a static requirements spreadsheet that nobody trusts by the second review cycle. Requirements get a real identity, a full version history, and a paper trail from first draft to shipped and verified; changes to already-approved requirements go through an actual review workflow instead of a silent edit.

It's built to sit at the center of how a hardware, firmware, or regulated-software team actually works day to day — not bolted on as an afterthought. Organisations contain projects, projects have role- and group-based access control enforced server-side, and every requirement and change request carries its own threaded discussion so the reasoning behind a decision lives next to the thing it's about.

## A look at the app

The screenshots below are captured from the seeded demo dataset — a fictional drone-inspection company with two projects at different lifecycle stages.

| Projects dashboard |
| --- |
| Favourites, role/stage filters, tile or list view |
| ![Projects dashboard listing two projects with status filters and a tile view](../../static/img/screenshots/projects-page.png) |

| Project overview |
| --- |
| Status breakdown, change-request funnel, stage progress, and an activity feed for one project |
| ![Project overview page showing requirement status breakdown and recent activity](../../static/img/screenshots/project-overview.png) |

| Requirement detail |
| --- |
| Version history, change log, and discussion thread for a single requirement |
| ![Requirement detail page showing its fields, version history, and discussion thread](../../static/img/screenshots/requirement-detail.png) |

## Where to go next

- New to the product? Read [Use cases](./use-cases.md) for concrete scenarios this was built for.
- Want to understand the model before clicking around? Start with [Concepts](../concepts/organisations-and-projects.md).
- Ready to run it yourself? [Installation & Deployment](../installation-deployment/overview.md) has a one-command local stack with this exact demo dataset.
- Want to see how a specific screen works, step by step? See [Workflows](../workflows/signing-in.md).
