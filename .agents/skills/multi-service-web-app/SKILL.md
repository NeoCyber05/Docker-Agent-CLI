---
name: multi-service-web-app
description: >-
  Reference architecture for full-stack web applications deployed as Docker Compose stacks.
  Use this skill whenever the user wants to deploy a multi-service web app, multi-tier
  architecture, frontend + backend + database stack, microservices behind a reverse proxy,
  MERN/MEAN/LAMP/Django stack, or any request involving service wiring between web-facing
  containers and backing services (databases, caches, queues). Also trigger when the user
  mentions service dependencies, container networking for web apps, or asks how to connect
  a frontend to an API to a database in Docker. Even if the user only says "deploy my app"
  and the app clearly has multiple tiers, consult this skill.
---

# Multi-Service Web App Stacks

A reference for building production-grade Docker Compose stacks that combine web-facing
services (frontends, APIs, reverse proxies) with backing services (databases, caches,
message queues). This skill focuses on **architecture decisions** — how services connect,
which networks to create, what to expose, and how to wire environment variables.

> For complete YAML templates of common stacks, read
> [references/stack-patterns.md](references/stack-patterns.md).

## When to Use

- Deploying a web application with 2+ services (e.g., app + database)
- Designing network topology for frontend/backend/data tiers
- Wiring service dependencies with health-check-gated startup
- Choosing port mapping strategy (what to expose to the host vs. keep internal)
- Setting up a reverse proxy (Nginx, Traefik, Caddy) in front of app services
- Orchestrating background workers alongside a web API (Celery, Sidekiq, BullMQ)

## Architecture Principles

### Tier Separation

Think of a web stack in three tiers:

| Tier       | Examples                          | Faces the internet? |
|------------|-----------------------------------|---------------------|
| **Edge**   | Nginx, Traefik, Caddy             | Yes (ports 80/443)  |
| **App**    | Node.js API, Django, Rails, PHP   | Only via edge proxy  |
| **Data**   | PostgreSQL, MySQL, Redis, MongoDB | Never                |

The edge tier is the only one that publishes ports to the host. App services
communicate with edge via a shared `frontend` network. Data services live on an
isolated `backend` network that app services also join.

### Single-Tier Stacks (2–3 services)

When there is no reverse proxy and the app talks directly to a database:
- A single default network is sufficient — skip custom networks.
- Publish only the app port to the host.
- The database has no published ports (reachable only inside the Compose network).

### Multi-Tier Stacks (4+ services or reverse proxy present)

When a reverse proxy sits in front of the app, or when there are multiple app
services:
- Create a `frontend` network for edge ↔ app communication.
- Create a `backend` network for app ↔ data communication.
- Mark the `backend` network as `internal: true` to block outbound internet access
  from data services.
- The app tier joins **both** networks (it is the bridge between edge and data).

---

## Network Topology Rules

### When to Create Custom Networks

| Scenario | Recommendation |
|----------|---------------|
| App + single DB, no proxy | Default network is fine. No custom networks needed. |
| App + DB + cache | Default network is fine unless you want DB isolation. |
| Reverse proxy + app + DB | Create `frontend` + `backend` networks. |
| Multiple app services sharing a DB | Create `backend` network with `internal: true`. |
| Microservices with a gateway | Create `public` + `internal` networks. |

### Network Configuration Patterns

**Two-network isolation** (most common for production web apps):

```yaml
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true    # No outbound internet from data tier
```

**Service placement across networks:**

```yaml
services:
  proxy:
    networks: [frontend]              # Edge: only frontend
  api:
    networks: [frontend, backend]     # App: bridges both
  db:
    networks: [backend]              # Data: only backend (isolated)
  redis:
    networks: [backend]              # Data: only backend (isolated)
```

### Key Rules

1. **Never expose database ports to the host in production.** Use
   `127.0.0.1:5432:5432` only during development, or omit `ports` entirely.
2. **Use `internal: true`** on the data-tier network to prevent containers from
   reaching the internet (reduces attack surface).
3. **Services discover each other by service name** within a shared network.
   `DATABASE_URL=postgresql://db:5432/myapp` works because `db` is the service name.

---

## Service Wiring Patterns

### Environment Variable Conventions

Use well-known environment variable names for connection strings. This makes
services portable and self-documenting.

| Variable | Format | Example |
|----------|--------|---------|
| `DATABASE_URL` | `protocol://user:pass@host:port/dbname` | `postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/app` |
| `REDIS_URL` | `redis://host:port/db` | `redis://redis:6379/0` |
| `MONGODB_URI` | `mongodb://host:port/dbname` | `mongodb://mongo:27017/app` |
| `AMQP_URL` | `amqp://user:pass@host:port` | `amqp://guest:guest@rabbitmq:5672` |
| `SMTP_URL` | `smtp://host:port` | `smtp://mailpit:1025` |
| `API_URL` / `BACKEND_URL` | `http://service:port` | `http://api:4000` |

> **Important**: Never put passwords or tokens in the `environment` map. The Docker
> Agent CLI automatically handles secrets — it moves sensitive values to `.env` files
> or auto-generates them for known images (postgres, mysql, mongo). Just reference
> the variable name (e.g., `${POSTGRES_PASSWORD}`) and let the tool handle the rest.

### Dependency Ordering with Health Checks

Always use `depends_on` with `condition: service_healthy` for databases. This prevents
the app from crashing on startup because the database isn't ready.

```yaml
services:
  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started    # Redis starts fast, no health gate needed
```

**When to use each condition:**

| Condition | Use when |
|-----------|----------|
| `service_healthy` | Database, message queue — anything that takes time to initialize |
| `service_started` | Cache, mail catcher — services that are ready almost instantly |
| `service_completed_successfully` | Init containers (migration runners, seed scripts) |

### Port Mapping Strategy

- **Publish only what end-users need to reach.** Typically: the reverse proxy (80/443)
  or the app itself (3000, 8080).
- **Never publish database/cache ports** in production. They are reachable by service
  name within the Docker network.
- **For development**, you may publish DB ports bound to localhost only:
  `127.0.0.1:5432:5432`.
- **Debug ports** (9229 for Node.js, 5005 for Java) should only be in dev overrides.

---

## Common Stack Patterns

Below are the most frequently requested web app stacks. Each entry describes the
architecture and key decisions. For complete, production-ready YAML, see
[references/stack-patterns.md](references/stack-patterns.md).

### 1. React + Node.js API + PostgreSQL + Redis

**Architecture:** SPA frontend served by Nginx → Node.js REST/GraphQL API → PostgreSQL
for persistence, Redis for sessions/caching.

- **Networks:** `frontend` (nginx ↔ api) + `backend` with `internal: true` (api ↔ db, redis)
- **Key decisions:**
  - Nginx serves static build and reverse-proxies `/api` to the Node.js service
  - PostgreSQL with named volume for data persistence
  - Redis with append-only persistence (`--appendonly yes`)
  - API depends on db (healthy) and redis (started)
  - Only nginx port 80 is published to host

### 2. Django + Celery + PostgreSQL + Redis

**Architecture:** Django WSGI app (Gunicorn) + Celery workers + Celery Beat scheduler,
backed by PostgreSQL and Redis (as both cache and Celery broker).

- **Networks:** `frontend` + `backend` (internal)
- **Key decisions:**
  - Django and Celery share the same image (different commands)
  - Redis serves dual purpose: Django cache + Celery broker
  - Celery worker and beat both depend on redis (healthy) and db (healthy)
  - Use `scale: 2` on the celery-worker service for parallel task processing
  - Static files served by Nginx from a shared volume

### 3. LAMP Stack (Apache/PHP + MySQL)

**Architecture:** Apache with mod_php serving a PHP application, backed by MySQL.

- **Networks:** Default (simple 2-service stack, no proxy needed)
- **Key decisions:**
  - PHP source mounted as bind mount for development
  - MySQL data in a named volume
  - Only Apache port 80 published
  - phpMyAdmin as optional admin tool (dev only)

### 4. MERN Stack (MongoDB + Express + React + Node.js)

**Architecture:** React SPA → Express.js API → MongoDB.

- **Networks:** `frontend` + `backend` (internal)
- **Key decisions:**
  - Nginx serves React build and proxies `/api` to Express
  - MongoDB with named volume, `--auth` enabled in production
  - Express connects via `MONGODB_URI` environment variable
  - Mongo Express as optional admin UI (dev only, not exposed in production)

### 5. WordPress + MySQL + Nginx Reverse Proxy

**Architecture:** WordPress (PHP-FPM) behind Nginx, backed by MySQL.

- **Networks:** `frontend` + `backend` (internal)
- **Key decisions:**
  - Nginx handles TLS termination and static file serving
  - WordPress wp-content in a named volume for uploads persistence
  - MySQL data in a separate named volume
  - WordPress connects to MySQL via standard `WORDPRESS_DB_*` env vars

---

## Best Practices Checklist

### Restart Policies

- Use `restart: unless-stopped` for all services in production stacks.
- Use `restart: "no"` (the default) for one-shot init/migration containers.
- Use `restart: on-failure` for workers that should retry but not loop infinitely.

### Health Checks

Every long-running service should have a health check. Common patterns:

| Service Type | Health Check Command |
|-------------|---------------------|
| PostgreSQL | `["CMD-SHELL", "pg_isready -U postgres"]` |
| MySQL | `["CMD", "mysqladmin", "ping", "-h", "localhost"]` |
| MongoDB | `["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]` |
| Redis | `["CMD", "redis-cli", "ping"]` |
| HTTP API | `["CMD-SHELL", "curl -f http://localhost:PORT/health \|\| exit 1"]` |
| Nginx | `["CMD-SHELL", "curl -f http://localhost/ \|\| exit 1"]` |
| RabbitMQ | `["CMD", "rabbitmq-diagnostics", "ping"]` |

Standard health check timing:

```yaml
healthcheck:
  test: ...
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

### Named Volumes for Stateful Services

- **Always** use named volumes for database data directories.
- **Never** rely on container-local storage for persistent data.
- Define volumes at the top level of the compose file.

```yaml
volumes:
  postgres-data:
  redis-data:
  uploads:
```

### Scaling Strategy

- Use `scale: N` at the service level (not `deploy.replicas`).
- Only scale stateless services (API servers, workers). Never scale databases this way.
- When scaling web services, put a load-balancing reverse proxy in front.
- For Celery/Sidekiq workers, `scale: 2` or more for parallel processing.

### Image Tags

- **Always** use specific version tags: `postgres:16-alpine`, `redis:7-alpine`.
- **Never** use `:latest` — it breaks reproducibility.
- Prefer `-alpine` variants for smaller images when available.

### Config Files

- When a service bind-mounts a config file (e.g., `./nginx.conf:/etc/nginx/nginx.conf`),
  provide the file content in the `configFiles` map of `plan_stack`.
- Do NOT provide content for directory mounts — Docker creates those automatically.

---

## ServiceSpec Schema Reference

When calling `plan_stack`, each service accepts these fields:

```typescript
{
  image: string;              // Required. Use specific tags.
  command?: string | string[];
  ports?: string[];           // "host:container" format
  environment?: Record<string, string>;  // Non-secret config only
  env_file?: string[];
  volumes?: string[];
  depends_on?: string[] | Record<string, { condition: "service_started" | "service_healthy" | "service_completed_successfully" }>;
  healthcheck?: {
    test: string | string[];
    interval?: string;
    timeout?: string;
    retries?: number;
    start_period?: string;
  };
  restart?: "no" | "always" | "on-failure" | "unless-stopped";
  labels?: Record<string, string>;
  networks?: string[];
  scale?: number;             // Use this instead of deploy.replicas
}
```

Top-level `networks` and `volumes` are also supported in the `plan_stack` call.
