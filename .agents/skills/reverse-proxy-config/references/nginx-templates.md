# Nginx Configuration Templates for Docker Compose

Complete, production-ready nginx.conf templates designed for Docker Compose
stacks. Each template uses Docker Compose service names in upstream blocks
for automatic DNS-based service discovery.

All templates are intended to be provided as `configFiles` content in Docker
Agent CLI's `plan_stack` call.

---

## Template 1: Basic Single-Backend Reverse Proxy

Use when: a single application service sits behind nginx.

```nginx
# =============================================================================
# Basic Reverse Proxy — Single Backend
# =============================================================================
# Proxies all requests to a single upstream service.
# Docker Compose resolves "app" to the container IP automatically.
# =============================================================================

# Auto-detect CPU cores for worker processes
worker_processes auto;

# Error log to stderr so Docker can capture it
error_log /dev/stderr warn;

# PID file location
pid /tmp/nginx.pid;

events {
    # Max simultaneous connections per worker
    worker_connections 1024;

    # Use epoll on Linux for better performance
    # use epoll;
}

http {
    # Include MIME types for proper Content-Type headers
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Log to stdout for Docker log collection
    access_log /dev/stdout;

    # Performance: sendfile + tcp_nopush for static files
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Keep-alive settings
    keepalive_timeout 65;

    # Hide nginx version in response headers
    server_tokens off;

    # Upstream block — "app" is the Docker Compose service name.
    # Compose's embedded DNS resolves this to the container IP.
    upstream app_backend {
        server app:3000;
    }

    server {
        listen 80;
        server_name _;

        # Proxy all requests to the upstream
        location / {
            proxy_pass http://app_backend;

            # Forward original client information to the backend
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Timeouts — adjust based on your app's response time
            proxy_connect_timeout 10s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Health check endpoint for Docker healthcheck
        location /nginx-health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
}
```

**Docker Compose healthcheck for this template:**
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost/nginx-health || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
```

---

## Template 2: Multi-Service Routing (Frontend + API + WebSocket)

Use when: routing different URL paths to different backend services, including
WebSocket support for real-time features.

```nginx
# =============================================================================
# Multi-Service Routing — Frontend + API + WebSocket
# =============================================================================
# Routes requests by URL path:
#   /             → frontend (React, Vue, Next.js dev server)
#   /api/         → api service (REST API)
#   /ws/          → ws service (WebSocket server)
#   /static/      → served directly by nginx from mounted volume
# =============================================================================

worker_processes auto;
error_log /dev/stderr warn;
pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    access_log /dev/stdout;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    server_tokens off;

    # --- Upstream definitions ---
    # Each upstream name maps to a Docker Compose service name.

    # Frontend application (e.g., React dev server on port 3000)
    upstream frontend_backend {
        server frontend:3000;
    }

    # REST API service (e.g., Express/Fastify on port 4000)
    upstream api_backend {
        server api:4000;
    }

    # WebSocket service (e.g., Socket.io on port 5000)
    upstream ws_backend {
        server ws:5000;
    }

    # --- Request size limits ---
    # Increase if your API accepts file uploads
    client_max_body_size 10m;

    server {
        listen 80;
        server_name _;

        # -----------------------------------------------------------------
        # API routing — strip /api prefix before forwarding
        # -----------------------------------------------------------------
        # The trailing slash on proxy_pass strips the matched prefix:
        #   /api/users → http://api_backend/users
        location /api/ {
            proxy_pass http://api_backend/;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # API-specific timeouts (may need longer for complex queries)
            proxy_connect_timeout 10s;
            proxy_send_timeout 120s;
            proxy_read_timeout 120s;
        }

        # -----------------------------------------------------------------
        # WebSocket routing
        # -----------------------------------------------------------------
        # HTTP Upgrade mechanism converts the connection from HTTP to WS.
        # proxy_read_timeout keeps idle WS connections alive.
        location /ws/ {
            proxy_pass http://ws_backend/;

            # Required for WebSocket upgrade
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

            # Keep WS connections alive for 24 hours
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
        }

        # -----------------------------------------------------------------
        # Static file serving (optional — if you mount a static dir)
        # -----------------------------------------------------------------
        # Serves files directly from nginx, bypassing the app server.
        # Mount with: ./public:/usr/share/nginx/html/static:ro
        location /static/ {
            alias /usr/share/nginx/html/static/;

            # Cache static assets aggressively
            expires 30d;
            add_header Cache-Control "public, immutable";

            # Enable gzip for text-based assets
            gzip on;
            gzip_types text/css application/javascript application/json
                       image/svg+xml text/plain;
            gzip_min_length 256;
        }

        # -----------------------------------------------------------------
        # Frontend — catch-all (must be last)
        # -----------------------------------------------------------------
        # Everything not matched above goes to the frontend.
        # For SPA frameworks, the frontend dev server handles client-side routing.
        location / {
            proxy_pass http://frontend_backend;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Support hot module reload (HMR) for dev servers
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

        # Health check endpoint
        location /nginx-health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
}
```

**Corresponding Docker Compose services:**
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
      - ws

  frontend:
    image: node:22-alpine
    expose: ["3000"]
    networks: [internal]

  api:
    image: node:22-alpine
    expose: ["4000"]
    networks: [internal]

  ws:
    image: node:22-alpine
    expose: ["5000"]
    networks: [internal]

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```

---

## Template 3: Load-Balanced Backend with Resolver

Use when: a service is scaled to multiple replicas and you want nginx to
distribute traffic across all instances.

```nginx
# =============================================================================
# Load-Balanced Backend
# =============================================================================
# Distributes requests across scaled service replicas.
#
# Docker Compose DNS: when a service has scale > 1, its name resolves
# to multiple A records (one per replica). Nginx uses the Docker DNS
# resolver (127.0.0.11) to discover all instances at runtime.
#
# IMPORTANT: The "resolver" directive + variable-based proxy_pass is
# required for nginx to re-resolve DNS periodically. Without it, nginx
# caches the IP from startup and won't discover new replicas.
# =============================================================================

worker_processes auto;
error_log /dev/stderr warn;
pid /tmp/nginx.pid;

events {
    worker_connections 2048;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    access_log /dev/stdout;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    server_tokens off;

    # Docker's embedded DNS resolver.
    # "valid=10s" means nginx re-queries DNS every 10 seconds to pick up
    # new replicas or dropped containers.
    resolver 127.0.0.11 valid=10s ipv6=off;

    # Upstream for the scaled "api" service.
    # When using Docker Compose scale, a single "server api:3000" entry
    # resolves to all replica IPs via Docker DNS round-robin.
    upstream api_pool {
        server api:3000;
    }

    server {
        listen 80;
        server_name _;

        location / {
            proxy_pass http://api_pool;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;

            # If a replica is down, try the next one
            proxy_next_upstream error timeout http_502 http_503;
            proxy_next_upstream_tries 3;
        }

        # Health check endpoint
        location /nginx-health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
}
```

**Corresponding Docker Compose with scale:**
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

  api:
    image: node:22-alpine
    expose: ["3000"]
    scale: 3
    networks: [internal]

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```

---

## Template 4: HTTPS with Self-Signed Certificate

Use when: development or internal environments need HTTPS (e.g., testing OAuth
callbacks, secure cookies, or mixed-content restrictions).

```nginx
# =============================================================================
# HTTPS Reverse Proxy — Self-Signed Certificate (Development)
# =============================================================================
# Provides HTTPS on port 443 with automatic HTTP→HTTPS redirect.
# The certificate is generated by the Docker entrypoint command (see
# the Compose service definition below), not baked into the image.
# =============================================================================

worker_processes auto;
error_log /dev/stderr warn;
pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    access_log /dev/stdout;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    server_tokens off;

    upstream app_backend {
        server app:3000;
    }

    # -----------------------------------------------------------------
    # HTTP server — redirect everything to HTTPS
    # -----------------------------------------------------------------
    server {
        listen 80;
        server_name _;

        # Permanent redirect to HTTPS
        return 301 https://$host$request_uri;
    }

    # -----------------------------------------------------------------
    # HTTPS server
    # -----------------------------------------------------------------
    server {
        listen 443 ssl;
        server_name _;

        # Certificate paths — mounted from a named volume or bind mount
        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;

        # Modern TLS configuration
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
        ssl_prefer_server_ciphers on;

        # SSL session caching for performance
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 10m;

        # HSTS — tells browsers to always use HTTPS
        # (use with caution in dev; browsers remember this)
        # add_header Strict-Transport-Security "max-age=31536000" always;

        location / {
            proxy_pass http://app_backend;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Health check on HTTPS
        location /nginx-health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
}
```

**Corresponding Docker Compose service:**
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
    networks:
      - public
      - internal
    depends_on:
      - app
    restart: unless-stopped
    # Generate self-signed cert on first run, then start nginx
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
    healthcheck:
      test: ["CMD-SHELL", "curl -sf -k https://localhost/nginx-health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3

  app:
    image: node:22-alpine
    expose: ["3000"]
    networks: [internal]

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true

volumes:
  ssl-certs:
```

---

## Template 5: Production Hardened (Security Headers + Rate Limiting + Gzip)

Use when: the stack is intended for production or staging deployment with
full security headers, rate limiting, gzip compression, and logging.

```nginx
# =============================================================================
# Production-Hardened Reverse Proxy
# =============================================================================
# Includes:
#   - Security headers (X-Frame-Options, CSP, HSTS, etc.)
#   - Rate limiting per client IP
#   - Gzip compression for text-based responses
#   - Request size limits
#   - Optimized buffer sizes
#   - Graceful error pages
# =============================================================================

worker_processes auto;
error_log /dev/stderr warn;
pid /tmp/nginx.pid;

events {
    worker_connections 2048;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # ---- Logging ----
    # JSON-formatted access log for easier parsing by log aggregators
    log_format json_combined escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"method":"$request_method",'
            '"uri":"$request_uri",'
            '"status":$status,'
            '"body_bytes_sent":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_response_time":"$upstream_response_time",'
            '"user_agent":"$http_user_agent"'
        '}';
    access_log /dev/stdout json_combined;

    # ---- Performance ----
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 100;

    # Hide nginx version from response headers and error pages
    server_tokens off;

    # ---- Gzip Compression ----
    # Compress text-based responses to reduce bandwidth
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 4;
    gzip_min_length 256;
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/xml
        image/svg+xml
        application/wasm;

    # ---- Buffers ----
    # Tune buffer sizes to avoid disk I/O for typical responses
    proxy_buffer_size 16k;
    proxy_buffers 4 32k;
    proxy_busy_buffers_size 64k;

    # ---- Request limits ----
    # Max upload size — adjust for your application
    client_max_body_size 25m;
    client_body_buffer_size 128k;

    # ---- Rate Limiting ----
    # Zone "general": 10 requests/second per client IP
    # Zone "api": 20 requests/second per client IP (APIs typically need more)
    limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;

    # Return 429 (Too Many Requests) instead of default 503
    limit_req_status 429;

    # ---- Upstream definitions ----
    upstream frontend_backend {
        server frontend:3000;
    }

    upstream api_backend {
        server api:4000;
    }

    server {
        listen 80;
        server_name _;

        # ---- Security Headers ----
        # Applied to all responses from this server block.

        # Prevent clickjacking — only allow same-origin framing
        add_header X-Frame-Options "SAMEORIGIN" always;

        # Prevent MIME type sniffing
        add_header X-Content-Type-Options "nosniff" always;

        # XSS protection (legacy browsers; CSP is the modern approach)
        add_header X-XSS-Protection "1; mode=block" always;

        # Control referrer information sent with requests
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        # Content Security Policy — customize per application
        # This is a restrictive default; adjust 'script-src', 'style-src', etc.
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';" always;

        # Permissions Policy — disable unnecessary browser features
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

        # ---- API routes (rate-limited) ----
        location /api/ {
            limit_req zone=api burst=40 nodelay;

            proxy_pass http://api_backend/;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Request-ID $request_id;

            proxy_connect_timeout 10s;
            proxy_send_timeout 120s;
            proxy_read_timeout 120s;

            # Retry on upstream errors
            proxy_next_upstream error timeout http_502 http_503;
            proxy_next_upstream_tries 2;
        }

        # ---- Frontend (rate-limited, less strict) ----
        location / {
            limit_req zone=general burst=20 nodelay;

            proxy_pass http://frontend_backend;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Support HMR WebSocket for dev servers
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

        # ---- Health check ----
        location /nginx-health {
            access_log off;
            limit_req off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        # ---- Custom error pages ----
        error_page 502 503 504 /50x.html;
        location = /50x.html {
            default_type text/html;
            return 502 '<!DOCTYPE html><html><body><h1>Service Temporarily Unavailable</h1><p>Please try again later.</p></body></html>';
        }
    }
}
```

**Corresponding Docker Compose:**
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
      frontend:
        condition: service_started
      api:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost/nginx-health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  frontend:
    image: node:22-alpine
    expose: ["3000"]
    networks: [internal]
    restart: unless-stopped

  api:
    image: node:22-alpine
    expose: ["4000"]
    networks: [internal]
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:4000/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 5

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
```
