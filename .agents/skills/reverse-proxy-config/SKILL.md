---
name: reverse-proxy-config
description: >-
  Reference for configuring reverse proxies in Docker Compose stacks — nginx
  reverse proxy, Traefik auto-discovery, load balancing, SSL/TLS termination,
  multi-service routing, API gateway patterns, and WebSocket proxying. Use this
  skill whenever the user mentions reverse proxy, nginx proxy, load balancer,
  API gateway, SSL termination, HTTPS setup, Traefik routing, or multi-service
  routing in a Docker context — even if they only say "put nginx in front of my
  app" or "expose my services through one port."
---

# Reverse Proxy Configuration for Docker Compose

Specialized reference for configuring reverse proxies within Docker Agent CLI
stacks. Covers nginx and Traefik patterns, complete config templates, network
architecture, and SSL/TLS — all designed around the `configFiles` mechanism
that Docker Agent CLI uses to deliver bind-mounted configuration.

## When to Use This Skill

- User wants nginx or Traefik in front of one or more services
- Request involves path-based routing (`/api` → backend, `/` → frontend)
- Load balancing across scaled service replicas
- SSL/TLS termination or HTTPS redirect
- WebSocket proxying (chat apps, real-time dashboards)
- API gateway pattern (single entry point for microservices)
- Any mention of "reverse proxy", "load balancer", or "gateway" in Docker context

## Critical: Docker Agent CLI `configFiles` Pattern

Docker Agent CLI does **not** expect config files to pre-exist on disk. When a
service bind-mounts a config file (a path with a file extension), the agent
**must** provide its full content in the `configFiles` map of `plan_stack`.

### How It Works

1. Agent plans a service with a volume like `./nginx.conf:/etc/nginx/nginx.conf:ro`
2. `configFiles.ts` detects this is a file-like bind mount (has extension)
3. Agent **must** include the content:
   ```
   configFiles: {
     "./nginx.conf": "<full nginx.conf content here>"
   }
   ```
4. The CLI writes the file to disk before running `docker compose up`
5. If the content is omitted, the plan is **blocked** — compose will not start

### Key Constraints (from configFiles.ts)

- Single file max: **64 KiB**
- Total configFiles max: **256 KiB**
- Paths must be **relative** to project root (no absolute paths)
- Paths cannot escape the project directory or use `.docker-agent/`
- Only file-like paths (with extension) are validated; directory mounts are ignored

### What This Means for Nginx Config

When planning a stack with nginx, always:

1. Add the volume mount: `./nginx.conf:/etc/nginx/nginx.conf:ro`
2. Provide the **complete, valid** nginx.conf in `configFiles`
3. Keep configs concise — stay well under 64 KiB
4. Use a single `nginx.conf` rather than splitting into `conf.d/` fragments
   (conf.d requires directory mounts which bypass configFiles validation)

## Nginx Reverse Proxy Patterns

### Pattern 1: Single Backend

The simplest reverse proxy — one nginx in front of one app service.

```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - public
      - internal
    depends_on:
      - app
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost/ || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3

  app:
    image: node:22-alpine
    expose:
      - "3000"
    networks:
      - internal
    restart: unless-stopped

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```

Corresponding `configFiles`:
```
"./nginx.conf": "worker_processes auto;\nevents { worker_connections 1024; }\nhttp {\n  upstream app_backend {\n    server app:3000;\n  }\n  server {\n    listen 80;\n    location / {\n      proxy_pass http://app_backend;\n      proxy_set_header Host $host;\n      proxy_set_header X-Real-IP $remote_addr;\n      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n      proxy_set_header X-Forwarded-Proto $scheme;\n    }\n  }\n}"
```

### Pattern 2: Multi-Service Routing (Frontend + API)

Route by URL path — `/api/*` goes to the backend, everything else to frontend.

```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - public
      - internal
    depends_on:
      - frontend
      - api
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost/ || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3

  frontend:
    image: node:22-alpine
    expose:
      - "3000"
    networks:
      - internal

  api:
    image: node:22-alpine
    expose:
      - "4000"
    networks:
      - internal

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```

Key nginx.conf directives for path-based routing:
```nginx
location /api/ {
    proxy_pass http://api_backend/;   # trailing slash strips /api prefix
}
location / {
    proxy_pass http://frontend_backend;
}
```

### Pattern 3: Load Balancing

Scale a service and let nginx distribute requests across replicas. In Docker
Agent CLI, use `scale: N` on the service (not `deploy.replicas`).

```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - public
      - internal
    depends_on:
      - api
    restart: unless-stopped

  api:
    image: node:22-alpine
    expose:
      - "3000"
    scale: 3
    networks:
      - internal

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```

Docker Compose DNS resolves `api` to all 3 replicas. The upstream block uses
the service name — Compose's embedded DNS returns multiple A records:
```nginx
upstream api_pool {
    server api:3000;  # resolves to all scaled instances
}
```

> **Note:** For sticky sessions or fine-grained balancing (least_conn,
> ip_hash), you need individually named services or static IPs — Docker
> Compose round-robin DNS does not support these. For most use cases, the
> default DNS-based round-robin is sufficient.

### Pattern 4: WebSocket Support

Add upgrade headers for WebSocket connections:
```nginx
location /ws/ {
    proxy_pass http://ws_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400s;  # keep WS connections alive
}
```

### Pattern 5: Static File Serving with Caching

Serve static assets directly from nginx with caching headers:
```nginx
location /static/ {
    alias /usr/share/nginx/html/static/;
    expires 30d;
    add_header Cache-Control "public, immutable";
    gzip on;
    gzip_types text/css application/javascript image/svg+xml;
}
```

For this pattern, mount the static files directory alongside the config:
```yaml
volumes:
  - ./nginx.conf:/etc/nginx/nginx.conf:ro
  - ./static:/usr/share/nginx/html/static:ro
```

## Traefik Auto-Discovery

Traefik uses Docker labels for automatic routing — no config files needed.

### Basic Traefik Setup

```yaml
services:
  traefik:
    image: traefik:v3.2
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
    ports:
      - "80:80"
      - "8080:8080"  # Traefik dashboard
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - public

  api:
    image: node:22-alpine
    labels:
      traefik.enable: "true"
      traefik.http.routers.api.rule: "PathPrefix(`/api`)"
      traefik.http.routers.api.entrypoints: "web"
      traefik.http.services.api.loadbalancer.server.port: "3000"
    expose:
      - "3000"
    networks:
      - public

networks:
  public:
    driver: bridge
```

### When to Use Traefik vs Nginx

| Criteria | Nginx | Traefik |
|---|---|---|
| Static, known services | ✅ Preferred | Works |
| Dynamic service discovery | Manual reload | ✅ Auto-discovery |
| Config file approach | configFiles pattern | Docker labels |
| Performance (high traffic) | ✅ Superior | Good |
| SSL with Let's Encrypt | Manual setup | ✅ Built-in ACME |
| Learning curve | Lower | Moderate |
| Docker Agent CLI fit | ✅ configFiles native | Labels in service spec |

**Recommendation:** Default to nginx for Docker Agent CLI stacks — it works
naturally with the `configFiles` pattern. Use Traefik when the user explicitly
requests it or needs automatic service discovery with dynamic scaling.

## Network Architecture

Reverse proxy stacks must follow this network isolation pattern:

```
Internet → [proxy:80] → public network → [proxy] → internal network → [backends]
                                                                        ↓
                                                              [databases, caches]
```

### Rules

1. **Proxy** connects to both `public` and `internal` networks
2. **Backend services** connect only to `internal` network
3. **Only the proxy** exposes ports to the host (via `ports:`)
4. Backend services use `expose:` (container-to-container only)
5. Mark the internal network as `internal: true` to block external access

```yaml
networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true  # no internet access, no host access
```

### Service Connectivity Matrix

| Service | public | internal | Host Ports |
|---|---|---|---|
| proxy (nginx) | ✅ | ✅ | 80, 443 |
| frontend | ❌ | ✅ | none |
| api | ❌ | ✅ | none |
| database | ❌ | ✅ | none |

## SSL/TLS Configuration

### Self-Signed Certificate (Development)

Generate a self-signed cert as part of the nginx service command:
```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ssl-certs:/etc/nginx/ssl
    command: >
      sh -c "
        if [ ! -f /etc/nginx/ssl/cert.pem ]; then
          apk add --no-cache openssl &&
          openssl req -x509 -nodes -days 365
            -subj '/CN=localhost'
            -newkey rsa:2048
            -keyout /etc/nginx/ssl/key.pem
            -out /etc/nginx/ssl/cert.pem;
        fi &&
        nginx -g 'daemon off;'
      "

volumes:
  ssl-certs:
```

### Let's Encrypt (Production)

Use the `certbot` companion container:
```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - certbot-etc:/etc/letsencrypt:ro
      - certbot-var:/var/lib/letsencrypt
      - certbot-webroot:/var/www/certbot:ro

  certbot:
    image: certbot/certbot:v3.1.0
    volumes:
      - certbot-etc:/etc/letsencrypt
      - certbot-var:/var/lib/letsencrypt
      - certbot-webroot:/var/www/certbot
    command: certonly --webroot -w /var/www/certbot -d example.com --agree-tos --email admin@example.com --non-interactive

volumes:
  certbot-etc:
  certbot-var:
  certbot-webroot:
```

## Best Practices

### Healthcheck

Always add a healthcheck to the proxy service:
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost/ || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

### Security Headers

Include these in every nginx proxy config:
```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'" always;
```

### Logging

```nginx
access_log /var/log/nginx/access.log;
error_log /var/log/nginx/error.log warn;
```

For Docker, logs go to stdout/stderr by default (visible via `docker compose logs`).
Override only if you need persistent log files.

### Rate Limiting

```nginx
http {
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

    server {
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;
            proxy_pass http://api_backend;
        }
    }
}
```

### Timeouts

```nginx
proxy_connect_timeout 10s;
proxy_send_timeout 60s;
proxy_read_timeout 60s;
send_timeout 60s;
```

## Complete Config Templates

For production-ready, fully annotated nginx.conf templates, read:
`references/nginx-templates.md`

This reference file contains 5 complete templates:
1. Basic single-backend reverse proxy
2. Multi-service routing (frontend + API + WebSocket)
3. Load-balanced backend with health checks
4. HTTPS with self-signed certificate
5. Production hardened with security headers and rate limiting

Each template is a complete, copy-paste ready nginx.conf that works with
Docker Compose service discovery (upstream blocks use service names).
