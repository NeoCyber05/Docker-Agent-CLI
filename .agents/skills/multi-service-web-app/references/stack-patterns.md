# Stack Patterns — Production-Ready YAML Templates

Complete `plan_stack` input examples for common web application architectures.
Each pattern uses the ServiceSpec schema and follows Docker Agent CLI conventions:
- Specific image tags (no `:latest`)
- `scale: N` instead of `deploy.replicas`
- No hardcoded passwords in `environment` (the agent handles secrets automatically)
- Health checks on every long-running service
- Named volumes for all stateful data

---

## Table of Contents

1. [React + Node.js API + PostgreSQL + Redis](#1-react--nodejs-api--postgresql--redis)
2. [Django + Celery + PostgreSQL + Redis](#2-django--celery--postgresql--redis)
3. [LAMP Stack (Apache/PHP + MySQL)](#3-lamp-stack-apachephp--mysql)
4. [MERN Stack (MongoDB + Express + React + Node.js)](#4-mern-stack-mongodb--express--react--nodejs)
5. [WordPress + MySQL + Nginx](#5-wordpress--mysql--nginx)

---

## 1. React + Node.js API + PostgreSQL + Redis

A classic full-stack JavaScript application with Nginx serving the frontend build
and reverse-proxying API requests.

### Architecture

```
  Internet
     │
  [nginx:80] ── frontend network ──┐
     │                              │
  [api:4000] ─── frontend + backend networks
     │
  [db:5432]  ── backend network (internal)
  [redis:6379] ── backend network (internal)
```

### plan_stack Input

```yaml
stackName: fullstack-react
intent: "Full-stack React + Node.js API with PostgreSQL and Redis"

services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - frontend
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  api:
    image: node:22-alpine
    command: ["node", "dist/server.js"]
    environment:
      NODE_ENV: production
      DATABASE_URL: "postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/app"
      REDIS_URL: "redis://redis:6379/0"
      PORT: "4000"
    volumes:
      - ./api:/app
    networks:
      - frontend
      - backend
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:4000/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: app
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
    networks:
      - backend
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true

volumes:
  postgres-data: {}
  redis-data: {}

configFiles:
  "./nginx.conf": |
    events { worker_connections 1024; }
    http {
      upstream api_backend {
        server api:4000;
      }
      server {
        listen 80;
        location /api/ {
          proxy_pass http://api_backend/;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
        }
        location / {
          root /usr/share/nginx/html;
          try_files $uri $uri/ /index.html;
        }
      }
    }
```

### Key Decisions

- **Nginx is the only service with a published port.** The API is reachable only
  through the reverse proxy.
- **PostgreSQL password** is omitted from `environment` — the agent auto-generates it
  and stores it in a `.env` file.
- **Redis** uses append-only file for persistence across restarts.
- **Backend network is internal** — db and redis cannot reach the internet.

---

## 2. Django + Celery + PostgreSQL + Redis

A Python web application with async task processing via Celery.

### Architecture

```
  Internet
     │
  [nginx:80] ── frontend network
     │
  [django:8000] ── frontend + backend networks
     │
  [celery-worker] ── backend network (same image as django)
  [celery-beat]   ── backend network (same image as django)
     │
  [db:5432]    ── backend network (internal)
  [redis:6379] ── backend network (internal)
```

### plan_stack Input

```yaml
stackName: django-celery
intent: "Django web app with Celery task queue, PostgreSQL, and Redis"

services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - static-files:/app/static:ro
    networks:
      - frontend
    depends_on:
      django:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  django:
    image: python:3.12-slim
    command: ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.production
      DATABASE_URL: "postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/django_app"
      REDIS_URL: "redis://redis:6379/0"
      CELERY_BROKER_URL: "redis://redis:6379/1"
    volumes:
      - ./app:/app
      - static-files:/app/static
    networks:
      - frontend
      - backend
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
    restart: unless-stopped

  celery-worker:
    image: python:3.12-slim
    command: ["celery", "-A", "config", "worker", "--loglevel=info", "--concurrency=4"]
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.production
      DATABASE_URL: "postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/django_app"
      CELERY_BROKER_URL: "redis://redis:6379/1"
      REDIS_URL: "redis://redis:6379/0"
    volumes:
      - ./app:/app
    networks:
      - backend
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "celery -A config inspect ping --timeout 10 || exit 1"]
      interval: 30s
      timeout: 15s
      retries: 3
      start_period: 30s
    restart: unless-stopped
    scale: 2

  celery-beat:
    image: python:3.12-slim
    command: ["celery", "-A", "config", "beat", "--loglevel=info", "--scheduler", "django_celery_beat.schedulers:DatabaseScheduler"]
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.production
      DATABASE_URL: "postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/django_app"
      CELERY_BROKER_URL: "redis://redis:6379/1"
    volumes:
      - ./app:/app
    networks:
      - backend
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: django_app
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
    volumes:
      - redis-data:/data
    networks:
      - backend
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true

volumes:
  postgres-data: {}
  redis-data: {}
  static-files: {}

configFiles:
  "./nginx.conf": |
    events { worker_connections 1024; }
    http {
      upstream django {
        server django:8000;
      }
      server {
        listen 80;
        location /static/ {
          alias /app/static/;
          expires 30d;
          add_header Cache-Control "public, immutable";
        }
        location / {
          proxy_pass http://django;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
        }
      }
    }
```

### Key Decisions

- **Django, celery-worker, and celery-beat share the same base image** but run
  different commands.
- **Celery workers are scaled to 2** via `scale: 2` for parallel task processing.
  Never scale celery-beat (only one scheduler should run).
- **Redis uses separate databases** — db 0 for Django cache, db 1 for Celery broker.
- **Static files** are shared between Django and Nginx via a named volume.

---

## 3. LAMP Stack (Apache/PHP + MySQL)

A traditional PHP application stack.

### Architecture

```
  Internet
     │
  [apache:80] ── default network
     │
  [mysql:3306] ── default network
  [phpmyadmin:8080] ── default network (dev only)
```

### plan_stack Input

```yaml
stackName: lamp-app
intent: "LAMP stack with Apache/PHP and MySQL"

services:
  apache:
    image: php:8.3-apache
    ports:
      - "80:80"
    environment:
      DATABASE_HOST: mysql
      DATABASE_PORT: "3306"
      DATABASE_NAME: app
      DATABASE_USER: app_user
    volumes:
      - ./src:/var/www/html
      - ./apache.conf:/etc/apache2/sites-available/000-default.conf:ro
    depends_on:
      mysql:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 15s
    restart: unless-stopped

  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: app
      MYSQL_USER: app_user
    volumes:
      - mysql-data:/var/lib/mysql
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  phpmyadmin:
    image: phpmyadmin:5.2
    ports:
      - "8080:80"
    environment:
      PMA_HOST: mysql
      PMA_PORT: "3306"
    depends_on:
      mysql:
        condition: service_healthy
    restart: unless-stopped
    labels:
      com.docker-agent.dev-only: "true"

volumes:
  mysql-data: {}

configFiles:
  "./apache.conf": |
    <VirtualHost *:80>
      DocumentRoot /var/www/html
      <Directory /var/www/html>
        AllowOverride All
        Require all granted
      </Directory>
      ErrorLog ${APACHE_LOG_DIR}/error.log
      CustomLog ${APACHE_LOG_DIR}/access.log combined
    </VirtualHost>
```

### Key Decisions

- **No custom networks needed** — this is a simple 2-service stack (phpmyadmin is
  optional for development).
- **MySQL passwords** are not in the environment map. The agent auto-generates
  `MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD`.
- **phpMyAdmin is labeled as dev-only** — remove it in production.
- **PHP source is bind-mounted** for development hot-reloading.

---

## 4. MERN Stack (MongoDB + Express + React + Node.js)

A JavaScript full-stack application with MongoDB.

### Architecture

```
  Internet
     │
  [nginx:80] ── frontend network
     │
  [express:4000] ── frontend + backend networks
     │
  [mongo:27017] ── backend network (internal)
  [mongo-express:8081] ── frontend network (dev only)
```

### plan_stack Input

```yaml
stackName: mern-app
intent: "MERN stack with MongoDB, Express API, React frontend via Nginx"

services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/build:/usr/share/nginx/html:ro
    networks:
      - frontend
    depends_on:
      express:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  express:
    image: node:22-alpine
    command: ["node", "dist/index.js"]
    environment:
      NODE_ENV: production
      MONGODB_URI: "mongodb://mongo:27017/mern_app"
      PORT: "4000"
    volumes:
      - ./backend:/app
    networks:
      - frontend
      - backend
    depends_on:
      mongo:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:4000/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped

  mongo:
    image: mongo:7
    command: ["mongod", "--auth"]
    volumes:
      - mongo-data:/data/db
    networks:
      - backend
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  mongo-express:
    image: mongo-express:1.0
    ports:
      - "8081:8081"
    environment:
      ME_CONFIG_MONGODB_SERVER: mongo
      ME_CONFIG_BASICAUTH: "false"
    networks:
      - frontend
      - backend
    depends_on:
      mongo:
        condition: service_healthy
    restart: unless-stopped
    labels:
      com.docker-agent.dev-only: "true"

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true

volumes:
  mongo-data: {}

configFiles:
  "./nginx.conf": |
    events { worker_connections 1024; }
    http {
      include /etc/nginx/mime.types;
      upstream express_backend {
        server express:4000;
      }
      server {
        listen 80;
        root /usr/share/nginx/html;
        location /api/ {
          proxy_pass http://express_backend/;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
        location / {
          try_files $uri $uri/ /index.html;
        }
      }
    }
```

### Key Decisions

- **MongoDB runs with `--auth`** in production for security.
- **Mongo Express is labeled dev-only** and should be removed in production.
- **React build output** is served as static files by Nginx.
- **Express API** is proxied through Nginx at `/api/`.

---

## 5. WordPress + MySQL + Nginx

A WordPress deployment with Nginx reverse proxy for TLS termination and caching.

### Architecture

```
  Internet
     │
  [nginx:80,443] ── frontend network
     │
  [wordpress:9000] ── frontend + backend networks (PHP-FPM)
     │
  [mysql:3306] ── backend network (internal)
```

### plan_stack Input

```yaml
stackName: wordpress-site
intent: "WordPress with Nginx reverse proxy and MySQL"

services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - wp-content:/var/www/html:ro
    networks:
      - frontend
    depends_on:
      wordpress:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  wordpress:
    image: wordpress:6.7-php8.3-fpm-alpine
    environment:
      WORDPRESS_DB_HOST: mysql
      WORDPRESS_DB_NAME: wordpress
      WORDPRESS_DB_USER: wp_user
    volumes:
      - wp-content:/var/www/html
    networks:
      - frontend
      - backend
    depends_on:
      mysql:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "php-fpm-healthcheck || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
    restart: unless-stopped

  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wp_user
    volumes:
      - mysql-data:/var/lib/mysql
    networks:
      - backend
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true

volumes:
  wp-content: {}
  mysql-data: {}

configFiles:
  "./nginx.conf": |
    events { worker_connections 1024; }
    http {
      include /etc/nginx/mime.types;
      upstream php_fpm {
        server wordpress:9000;
      }
      server {
        listen 80;
        root /var/www/html;
        index index.php index.html;

        location / {
          try_files $uri $uri/ /index.php?$args;
        }

        location ~ \.php$ {
          fastcgi_pass php_fpm;
          fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
          include fastcgi_params;
        }

        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
          expires 30d;
          add_header Cache-Control "public, immutable";
        }
      }
    }
```

### Key Decisions

- **WordPress uses PHP-FPM variant** (`fpm-alpine`) for better performance with Nginx.
- **Nginx handles static file caching** with 30-day expiry headers.
- **MySQL passwords** are auto-generated by the agent (MYSQL_ROOT_PASSWORD,
  WORDPRESS_DB_PASSWORD, MYSQL_PASSWORD).
- **wp-content volume** is shared between WordPress and Nginx for serving uploads.
- **Backend network is internal** — MySQL has no internet access.
