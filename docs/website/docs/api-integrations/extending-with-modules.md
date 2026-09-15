---
sidebar_position: 7
---

# Extending with modules

Everything on this page's sibling pages — REST endpoints, SSO/SCIM, MCP tools — isn't limited to what ships in the core application. A [module](../modules/overview.md) can contribute its own REST endpoints (mounted under `/api/v1/orgs/{organization_id}/modules/<key>/...` and `/api/v1/projects/{project_id}/modules/<key>/...`, the same shape as core endpoints) and its own MCP tools (automatically prefixed with the module's key and registered alongside the hand-written ones in [AI assistants → Overview](./ai-assistants-mcp/overview.md#module-contributed-tools)) — the Compliance module, documented in [Modules → Compliance module](../modules/compliance-module.md), is the working example of both.

For the actual contract a module implements to do this — the `ModuleDefinition` shape, how a router gets mounted, how an MCP tool is declared and mechanically constrained — see [Modules → Building your own module](../modules/building-your-own-module.md), which covers it in full; this page exists only to point there rather than duplicate it.
