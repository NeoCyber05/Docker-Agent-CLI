"""Domain-specific system-prompt guidance contributed by the Docker plugin.

The core agent prompt is domain-agnostic. Each infrastructure plugin ships its own
usage guidance through ``capabilities_payload()["instructions"]`` so the control plane
can compose a system prompt from only the plugins that are actually connected. Keeping
this text next to the Docker tools (rather than in the core prompt) is what lets other
infrastructure plugins — Kubernetes, cloud providers, etc. — be added without editing
the core.
"""

from __future__ import annotations

DOCKER_INSTRUCTIONS = """\
## Docker stacks (`docker.*` tools)

Every Docker deployment or stack change MUST go through `docker.deploy_stack`. This is
the model-facing deploy tool: it runs the server-side `plan_stack` gate, policy checks,
Compose YAML generation, and pending plan review before anything is applied. Do NOT
invoke `plan_stack`, `apply_stack`, or `docker.commit_action` directly.

Before `docker.deploy_stack`:
- build the complete draft (`stackName`, `intent`, `services`, and any `networks`, `volumes`, or `configFiles`);
- use `docker.validate_spec` only as an optional diagnostic when you need to inspect or correct a draft before deploy. Do not treat it as a required preflight because `docker.deploy_stack` re-runs validation internally;
- use `docker.resolve_dependency` only as an optional diagnostic when debugging multi-service dependency order.

`docker.validate_spec` and `docker.deploy_stack` use the same full draft preflight: image/config/app-source validation, published-port conflicts, dependency order, resource limits, database port exposure, volume safety/references, and network references. Do not call a separate port-conflict tool.

Use each observation to correct the next action. Call `docker.deploy_stack` only with the
corrected complete draft. If `docker.deploy_stack` returns `status: blocked`, read the blocker, correct the draft, and try again. A normal plan review may include a Preflight report artifact; treat it as evidence that the server-side gate ran, not as a separate tool you need to call.

When planning services:
- Provide a list of `services` (array of objects). Each service must specify `name` (string) and `kind` ("catalog" or "custom").
- **Catalog Services (Backing services)**:
  - Use `kind: "catalog"` for standard databases and proxies.
  - Specify `catalogId` from the allowed list: `postgresql:16`, `postgresql:15`, `redis:7`, `redis:6`, `mysql:8.0`, `mongodb:6.0`, `nginx:1.27`.
  - Do NOT specify `image` for catalog services.
- **Custom Services (User applications)**:
  - Use `kind: "custom"` and specify the `image` name.
  - Do NOT specify `catalogId`.
- **High-level Abstractions**:
  - Do NOT specify raw compose `ports`, `restart`, `deploy.resources`, or `logging` settings. The system automatically configures secure and policy-compliant defaults for these.
  - If the user explicitly requests a specific network name (e.g. "wp-net"), specify it in the `networkName` property of the stack plan (e.g. `networkName: "wp-net"`).
  - For persistent storage, specify a `persistence: { size: "10Gi" }` block. For custom services, also specify the container target path: `persistence: { path: "/app/data", size: "10Gi" }`.
  - For resource sizing, use `resources: "small" | "medium" | "large"`.
  - For exposure, use `exposure: "public"` to make a service accessible. You may optionally request a specific host port with `hostPort: <port>` and container port with `containerPort: <port>`. If `hostPort` is omitted, a free port in the range 8000-9000 is automatically allocated.
- **Networks (multi-tier / isolation)**:
  - Declare top-level networks in `networks` (array of objects). Each entry needs `name`; optional fields: `driver` (`bridge` | `overlay`), `internal`, `external`, `labels`.
  - Assign a service to one or more networks with `networks: ["frontend", "backend"]` on that service. Omit `networks` on a service to attach it to the default network only.
  - The reserved name `default` is always created; use `networkName` to rename it. Do NOT declare a network named `default` in `networks`.
  - Example — nginx on a public frontend network, API and DB on an internal backend network:

    ```json
    {
      "networks": [
        { "name": "frontend" },
        { "name": "backend", "internal": true }
      ],
      "services": [
        { "name": "web", "kind": "catalog", "catalogId": "nginx:1.27", "exposure": "public", "networks": ["frontend"] },
        { "name": "api", "kind": "custom", "image": "node:20-alpine", "networks": ["frontend", "backend"] },
        { "name": "db", "kind": "catalog", "catalogId": "postgresql:16", "persistence": {}, "networks": ["backend"] }
      ]
    }
    ```
- **Volumes (named volumes with driver options)**:
  - Declare top-level named volumes in `volumes` (array of objects). Each entry needs `name`; optional fields: `driver`, `driverOpts`, `labels`, `external`.
  - Mount declared volumes on a service with `volumeMounts`: `[{ "volume": "pgdata", "target": "/var/lib/postgresql/data" }]`. Add `"readOnly": true` for read-only mounts.
  - `persistence` still auto-creates a `{serviceName}_data` volume for databases and custom apps — use that for simple single-volume storage.
  - Example — PostgreSQL with a custom driver and a shared cache volume:

    ```json
    {
      "volumes": [
        { "name": "pgdata", "driver": "local" },
        { "name": "cache", "driverOpts": { "type": "tmpfs", "device": "tmpfs" } }
      ],
      "services": [
        { "name": "db", "kind": "catalog", "catalogId": "postgresql:16", "volumeMounts": [{ "volume": "pgdata", "target": "/var/lib/postgresql/data" }] },
        { "name": "cache", "kind": "catalog", "catalogId": "redis:7", "volumeMounts": [{ "volume": "cache", "target": "/data" }] }
      ]
    }
    ```
- Put non-secret config in `environment`. NEVER put passwords, tokens, or API keys in `environment` — leave them out; the tool will auto-generate them where it knows how (postgres, mysql, mongo) or block and ask the user.
- Never construct a connection-string/URI value that embeds a username or password yourself (e.g. `mongodb://user:pass@host/db`). If a custom service depends on a generated database, declare the env var name only (`MONGO_URI`, `MONGODB_URI`, or `DATABASE_URL` for Mongo; WordPress+MySQL/MariaDB is wired automatically) and leave its value empty — the tool injects the real staged credential automatically.

## Docker operations and diagnostics

When something looks broken - unhealthy containers, crash loops, or deploy issues -
call `docker.get_health` and `docker.get_logs`, then diagnose before acting. Use
`docker.inspect_drift`, `docker.list_stacks`, and `docker.get_stack_status` to compare
desired vs running state.

## Removing / cleaning Docker containers

- `docker.destroy_stack` tears down stacks **managed by docker-agent** (with a stack YAML file).
  If it returns `stack_file_not_found`, the stack is not tracked - do NOT retry
  `docker.destroy_stack` with guessed names.
- `docker.stop_stack` stops containers for a managed stack **without removing them**
  (`docker compose stop`). Use this when the user wants to pause services but keep
  the stack definition; use `docker.deploy_stack` with the desired stack draft to start again.
- Use `docker.remove_container` only for **specific orphan containers** blocking the current
  task (name conflict, leftover from a failed deploy). Pass exact container names from
  `docker.exec_docker ps` - never batch-remove all stopped containers or unrelated projects.
- Containers belonging to a stack still managed by docker-agent cannot be removed with
  `docker.remove_container`; use `docker.stop_stack` to stop services or `docker.destroy_stack` to tear down.
- If deploy fails due to a name conflict, remove only the conflicting container(s) with
  `docker.remove_container`, or suggest renaming the service before calling `docker.deploy_stack` again.

## Docker config files for bind mounts

When a service bind-mounts a single config FILE (a host path with an extension),
declare the mount with `configMounts` — do NOT use raw compose `volumes`:

  configMounts: [
    { "hostPath": "./nginx.conf", "containerPath": "/etc/nginx/nginx.conf" }
  ]

You MUST also provide that file's full content in the `configFiles` map, keyed by
the same `hostPath`:

  configFiles: { "./nginx.conf": "<full file content>" }

The agent writes these files to the project directory before `docker compose up`.
Do NOT provide content for directory mounts (paths without an extension, e.g.
`./data` for PostgreSQL data) — Docker creates those directories itself.
If you bind-mount a config file but omit its content, the plan is blocked.

For custom application services (e.g. `node:20-alpine` with `command: "node server.js"`),
you MUST provide the application source via `configFiles` (and `configMounts` if
needed) or ask the user for the source — do NOT assume the script exists in the base
image. If `docker.validate_spec` or `docker.deploy_stack` reports `missing_app_source`, ask the user
for the code or supply a minimal starter file via `configFiles` and re-plan.

## Reporting Docker deployment outcomes

After `docker.deploy_stack` returns, read its observation text before summarizing. If it
contains "apply failed", "rollback", "unhealthy", or any error marker, you MUST tell
the user the deployment did NOT succeed — state the exact failure reason and rollback
outcome (restored previous state / removed / rollback FAILED, manual cleanup needed).
NEVER describe a stack as deployed, running, or healthy unless the observation is
unambiguously successful ("Stack applied." with no failure/rollback markers)."""


__all__ = ["DOCKER_INSTRUCTIONS"]
