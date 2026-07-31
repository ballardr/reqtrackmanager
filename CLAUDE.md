# Project Instructions

## Validation

- User inputs may be written casually and can include imprecise terminology
- Agents must not only validate their own outputs but also challenge assumptions made by other agents where relevent.

## Documentation Requirements

- Prefer diagrams in documentation wherever they will improve clarity
- User Mermaid diagrams by default where possible
- Every diagram must include explanitory context immediately before or after it, including:
    - what the diagram represents
    - how to read the diagram (key actors, flows, boundaries), and
    - why it matters in the surrounding context
- Validate Mermaid diagrams before finalising to ensure they render correctly (no broken fences, no malformed syntax, no dangling nodes)

When writing requirements:
- every requirement must include explicit reasoning
- Reasoning must state:
    - Why the requirement exists
    - What risk, defect class or constraint it addresses
    - The expected outcome if implemented

Any documentation output must maintain logical coherence, hierarchical consistancy and technology alignment.

All source files must include file-level documentation describing:
- The purpose of the module
- The responsibilities of the module
- Any important design decisions
- External dependencies or integrations

Example:

```python
"""
Module: user_service

Provides user account management functionality including:
- User creation
- User lookup
- User lifecycle management

This module is used by the API layer and should not directly access
HTTP request objects.
"""
```

## Function Documentation

Every function, method, and class must have documentation explaining:
- What it does
- Parameters and their types
- Return values
- Exceptions that may be raised
- Important side effects

Example:
```python
def calculate_total(items: list[Item]) -> Decimal:
    """
    Calculates the total cost of a collection of items.

    Args:
        items: List of items to calculate.

    Returns:
        The total monetary value of all items.

    Raises:
        ValueError: If an item has an invalid price.
    """
```

## Architecture and Environment Requirements

- The project must include a Docker Compose stack for testing, and this stack may also be used for general local running.
- The project must include documentation that:
  - describes what the project is
  - explains how to set up the development environment
  - explains how to run the project in both development and production environments
- The architecture should be designed with future scaling in mind, while starting with a single frontend container and a single backend container.
- The project should use PostgreSQL as its backend data store.
- The project must provide a method for monitoring service health, including container health checks and a Prometheus-compatible metrics endpoint that can be scraped for monitoring.
- The project should support Loki-based log aggregation and Tempo-based tracing, and the documentation should include setup instructions for both, including how to configure and use Grafana Alloy for shipping logs, traces, and metrics to these systems.
- As some requirements may be sensitive, designs must keep security at the forefront of architectural decisions.

## Documentation and Decision Governance

- The requirements document at [docs/requirements.md](docs/requirements.md) is fully authoritative and must not be changed by the agent. All decisions should be made in compliance with the requirements laid out in this document.
- The architecture document at [docs/solution-architecture.md](docs/solution-architecture.md) should be updated when there are architectural changes.
- The decisions log at [docs/decisions.md](docs/decisions.md) should be used to record architectural and implementation decisions.

## README Requirements

The README.md must always reflect the current state of the project.

When making significant changes, update the README to include:
- Project purpose
- Installation instructions
- Configuration requirements
- Usage examples
- Architecture overview
- Development workflow
- Known limitations
- Code Quality Rules
- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
