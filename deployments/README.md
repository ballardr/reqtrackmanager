# Deployments

Compose stacks for running ReqTrackManager. Run each from its own directory, with its `.env` beside it.

| Directory | Contents | Use it for |
| --- | --- | --- |
| [`minimal/`](minimal/docker-compose.yml) | `db`, `storage`, `backend`, `frontend`, `mcp-server`, `converter` | A small installation or an evaluation on one host |
| [`full/`](full/docker-compose.yml) | The minimal stack plus optional profiles: `observability` (Prometheus, Loki, Tempo, Alloy, Grafana), `backup`, `restore`, `docs` | A production deployment |

The development and test stack is separate and lives in [`tests/container/`](../tests/container/docker-compose.yml); it is never used for a real deployment. See [docs/deployment.md](../docs/deployment.md).
