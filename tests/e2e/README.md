# Manual end-to-end smoke test

The agent's automated tests are unit-scoped. To exercise the full enroll →
inventory → heartbeat → presence cycle, run this smoke test by hand against a
local `sum_server`.

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

## Enroll via the web UI

1. Open `http://localhost:8000/login` and sign in with the bootstrap admin.
2. Hosts → **Enroll host** → create the host; the wizard shows the exact
   commands and the one-time token.
3. In the agent terminal, run them:

```sh
cd ../sum_agent
uv sync
export SUM_AGENT_SERVER_URL=http://localhost:8000
uv run sum-agent enroll --token <one-time-token>
uv run sum-agent run
```

The agent logs `agent_started`, then `inventory_submitted`, and heartbeats
every 30 seconds.

## What to verify

- The host's pill flips to **online** within one heartbeat interval; the
  host's display name becomes the reported hostname.
- The Overview tab fills with facts (hostname, kernel, OS, addressing);
  Storage / Network / Hardware tabs show the collected components.
- `Ctrl-C` the agent: the pill becomes **stopped** (goodbye received).
- `kill -9` the agent instead: the pill degrades to **unreachable** after the
  online window (default 90 s), since no goodbye was sent.
- Reboot the machine (systemd host): the pill shows **rebooting** during
  shutdown, then returns to **online** when the agent comes back.

## Verify the audit trail

```sh
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"admin@example.com","password":"admin-pw-12345"}' \
    | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/audit \
    | jq '.items[].action' | sort -u
```

You should see `agent.enrolled`, `agent.inventory_submitted`, and
`host.reported_shutdown` after a clean stop. A `kill -9` followed by a host
reboot also produces `host.unclean_reboot` (boot_id changed with no goodbye).
