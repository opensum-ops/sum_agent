# Manual end-to-end smoke test

The agent's automated tests are unit-scoped. To exercise the full enroll →
inventory → poll → pickup → execute → report cycle, run this smoke test by hand
against a local `sum_server`.

## Prerequisites

- PostgreSQL reachable from `sum_server`.
- `sum_server` installed (sibling `../sum_server`).
- Two terminals.

## Bring up `sum_server`

```sh
cd ../sum_server
uv sync
export SUM_SERVER_DATABASE_URL=postgresql+asyncpg://sum:sum@localhost:5432/sum_server
export SUM_SERVER_SIGNING_PRIVATE_KEY="inline:$(python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export SUM_SERVER_ENV=dev
export SUM_SERVER_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export SUM_SERVER_BOOTSTRAP_ADMIN_PASSWORD=admin-pw-12345
uv run alembic upgrade head
uv run uvicorn sum_server.main:app --reload
```

## Create a Server + enrollment

In another terminal:

```sh
# Log in.
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"admin@example.com","password":"admin-pw-12345"}' \
    | jq -r .access_token)

# Create a Server.
SERVER_ID=$(curl -s -X POST http://localhost:8000/api/v1/servers \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"name":"smoke-host","status":"active"}' | jq -r .id)

# Create an enrollment.
ENROLL=$(curl -s -X POST http://localhost:8000/api/v1/agents/enrollments \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"server_id\":\"$SERVER_ID\"}" | jq -r .enrollment_token)
```

## Run the agent

```sh
cd ../sum_agent
uv sync
export SUM_AGENT_SERVER_URL=http://localhost:8000
export SUM_AGENT_TLS_INSECURE=true
uv run sum-agent enroll --token "$ENROLL"
uv run sum-agent run
```

The agent should log `agent_started`, then `inventory_submitted`, then poll
every 15 seconds.

## Dispatch a job

```sh
curl -s -X POST "http://localhost:8000/api/v1/servers/$SERVER_ID/jobs" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"capability":"rename_nic","payload":{"current_name":"eth0","new_name":"ens99"}}'
```

The agent will log `job_received`, then `job_finished`. On a host without an
`eth0` it will report `failed` with `interface_not_found`, which is also a
valid path through the agent.

## Verify the audit trail

```sh
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/audit \
    | jq '.items[].action' | sort -u
```

You should see `agent.enrolled`, `agent.inventory_submitted`, `job.create`,
`job.picked_up`, and `job.failed` (or `job.completed`) at minimum.
