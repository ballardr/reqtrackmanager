# ReqTrackManager

ReqTrackManager is an open-source engineering requirements management system for product development teams. The initial v1 implementation provides a practical foundation for organizing projects, requirements, change requests, and basic audit history while keeping the architecture ready for later enterprise and observability enhancements.

## What is included in v1

- React-based web frontend for browsing the product overview
- Python FastAPI backend with REST endpoints for organizations, projects, requirements, and change requests
- PostgreSQL-backed data model with temporal fields for audit-friendly history
- Docker Compose-based local stack for database and application services
- Prometheus-compatible metrics endpoint and health checks

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm start
```

### Docker Compose

```bash
docker compose up --build
```

## Verification

The backend includes smoke tests for the health and metrics endpoints.

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## Architecture notes

The v1 implementation is intentionally structured to minimize rework for later stages. The data model already includes temporal fields and a modular backend layout so role-based access control, richer workflow automation, and more advanced observability can be introduced without a large rewrite.