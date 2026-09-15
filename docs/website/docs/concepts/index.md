---
sidebar_position: 1
---

# Concepts

Coming in Phase 2.

Smoke test for Phase 1's themed Mermaid setup (ported from `docs/solution-architecture.md`) — remove or replace once Phase 2 lands real Concepts content.

```mermaid
flowchart LR
    User[User] --> UI[React Web Frontend]
    UI --> API[Python Backend API]
    API --> DB[(PostgreSQL)]
    API --> FS[(File Storage)]
    API --> Mail[Email Delivery]
    API --> Alloy[Grafana Alloy]
    Alloy --> Loki[Grafana Loki]
    Alloy --> Tempo[Grafana Tempo]
    Alloy --> Prom[Prometheus]
    Prom --> Grafana[Grafana Dashboard]
```
