# 泌尿科 AI 語音問診助手 -- 基礎架構與系統架構規格書

> **本文件的型別定義、Enum 值、資料模型以 shared_types.md 為準。**

**文件版本：** 1.1.0
**建立日期：** 2026-04-10
**文件狀態：** Draft
**機密等級：** Internal -- Confidential

---

## 目錄

1. [系統架構總覽圖 (System Architecture Overview)](#1-系統架構總覽圖)
2. [部署架構 (Deployment Architecture)](#2-部署架構)
3. [網路架構 (Network Architecture)](#3-網路架構)
4. [CI/CD Pipeline](#4-cicd-pipeline)
5. [監控與可觀測性 (Monitoring & Observability)](#5-監控與可觀測性)
6. [安全架構 (Security Architecture)](#6-安全架構)
7. [合規性設計 (Compliance Design)](#7-合規性設計)
8. [災難復原計畫 (Disaster Recovery Plan)](#8-災難復原計畫)
9. [擴展性規劃 (Scalability Planning)](#9-擴展性規劃)
10. [開發環境設定 (Development Environment)](#10-開發環境設定)
11. [環境配置清單 (Environment Configuration)](#11-環境配置清單)

---

## 1. 系統架構總覽圖

### 1.1 高階架構圖 (High-Level Architecture Diagram)

```
+========================================================================================+
|                              CLIENT LAYER                                              |
|                                                                                        |
|   +----------------+    +----------------+    +---------------------+                  |
|   |   iOS App      |    |  Android App   |    |   Web Dashboard     |                  |
|   | (React Native) |    | (React Native) |    |   (React SPA)       |                  |
|   +-------+--------+    +-------+--------+    +----------+----------+                  |
|           |                      |                        |                             |
+========================================================================================+
            |                      |                        |
            +----------------------+------------------------+
                                   |
                          HTTPS / WSS
                                   |
+========================================================================================+
|                              EDGE LAYER                                                |
|                                                                                        |
|   +------------------+     +------------------------------------------+                |
|   | CloudFlare CDN   |     |  AWS CloudFront / GCP Cloud CDN          |                |
|   | (Static Assets)  |     |  (API Cache + DDoS Protection)           |                |
|   +--------+---------+     +---------------------+--------------------+                |
|            |                                      |                                    |
|            +--------------------------------------+                                    |
|                              |                                                         |
|                    +---------+---------+                                                |
|                    |  TLS Termination  |                                                |
|                    |  (Let's Encrypt / |                                                |
|                    |   ACM Certs)      |                                                |
|                    +---------+---------+                                                |
|                              |                                                         |
+========================================================================================+
                               |
+========================================================================================+
|                          INGRESS / GATEWAY LAYER                                       |
|                                                                                        |
|              +-------------------------------+                                         |
|              |   Kubernetes Ingress (NGINX)  |                                         |
|              |   - Path-based routing        |                                         |
|              |   - Rate limiting             |                                         |
|              |   - Request logging           |                                         |
|              +------+---------------+--------+                                         |
|                     |               |                                                  |
|            +--------+--+      +-----+----------+                                       |
|            | REST API  |      | WebSocket      |                                       |
|            | Routes    |      | Upgrade Path   |                                       |
|            | /api/v1/* |      | /ws/*          |                                       |
|            +--------+--+      +-----+----------+                                       |
|                     |               |                                                  |
+========================================================================================+
                      |               |
+========================================================================================+
|                        APPLICATION LAYER                                               |
|                                                                                        |
|  +---------------------+   +----------------------+   +-------------------------+      |
|  | FastAPI Instance #1 |   | FastAPI Instance #2  |   | FastAPI Instance #N    |      |
|  | (REST API Server)   |   | (REST API Server)    |   | (REST API Server)      |      |
|  | - Auth endpoints    |   | - Patient endpoints  |   | - Doctor endpoints     |      |
|  | - Session mgmt      |   | - SOAP generation   |   | - Admin endpoints      |      |
|  | - Red flag detect   |   | - Report endpoints   |   | - Audit log endpoints  |      |
|  +----------+----------+   +----------+-----------+   +------------+-----------+      |
|             |                         |                             |                   |
|  +----------+-------------------------+-----------------------------+----------+        |
|  |                          Shared Application Services                       |        |
|  |  +------------------+ +-------------------+ +------------------------+     |        |
|  |  | AI Pipeline Svc  | | Notification Svc  | | File Management Svc    |     |        |
|  |  | - STT Orchestr.  | | - FCM Push        | | - Audio upload/download|     |        |
|  |  | - LLM Processing | | - In-app alerts   | | - Presigned URL gen    |     |        |
|  |  | - TTS Orchestr.  | | - Email (opt.)    | | - Retention policy     |     |        |
|  |  +------------------+ +-------------------+ +------------------------+     |        |
|  +----------------------------------------------------------------------------+        |
|                                                                                        |
|  +----------------------+   +----------------------+                                   |
|  | WebSocket Gateway    |   | Background Workers   |                                   |
|  | (FastAPI WebSocket)  |   | (Celery + Redis)     |                                   |
|  | - Real-time voice    |   | - SOAP report gen    |                                   |
|  |   streaming          |   | - Audio transcoding  |                                   |
|  | - Session state sync |   | - Batch analytics    |                                   |
|  | - Red flag push      |   | - Scheduled cleanup  |                                   |
|  | - Typing indicators  |   | - Notification queue |                                   |
|  +----------+-----------+   +----------+-----------+                                   |
|             |                          |                                                |
+========================================================================================+
              |                          |
+========================================================================================+
|                         DATA LAYER                                                     |
|                                                                                        |
|  +--------------------------+  +---------------------+  +-----------------------+      |
|  |  PostgreSQL 15+ Cluster  |  |  Redis 7+ Cluster   |  |  Object Storage       |      |
|  |                          |  |                     |  |  (S3 / GCS)           |      |
|  |  +--------------------+  |  |  +---------------+  |  |                       |      |
|  |  | PgBouncer          |  |  |  | Session Cache |  |  |  +------------------+ |      |
|  |  | (Connection Pool)  |  |  |  | (TTL: 30min)  |  |  |  | /audio-raw/      | |      |
|  |  | max_pool: 100      |  |  |  +---------------+  |  |  | /audio-processed/| |      |
|  |  +--------+-----------+  |  |  | JWT Blacklist |  |  |  | /soap-reports/   | |      |
|  |           |              |  |  | (TTL: 24hr)   |  |  |  | /exports/        | |      |
|  |  +--------v-----------+  |  |  +---------------+  |  |  +------------------+ |      |
|  |  | Primary (Writer)   |  |  |  | Celery Broker |  |  |                       |      |
|  |  | - WAL Streaming    |  |  |  | (Task Queue)  |  |  |  Lifecycle Rules:     |      |
|  |  | - pgcrypto ext.    |  |  |  +---------------+  |  |  - raw audio: 3 years |      |
|  |  +--------+-----------+  |  |  | Rate Limiter  |  |  |  - reports: 7 years   |      |
|  |           |              |  |  | (Sliding Win) |  |  |  - exports: 30 days   |      |
|  |  +--------v-----------+  |  |  +---------------+  |  +-----------------------+      |
|  |  | Read Replica #1    |  |  |                     |                                  |
|  |  | - Read-only queries|  |  |  Sentinel / Cluster |                                  |
|  |  | - Analytics queries|  |  |  Mode for HA        |                                  |
|  |  +--------------------+  |  +---------------------+                                  |
|  +--------------------------+                                                           |
|                                                                                        |
+========================================================================================+

+========================================================================================+
|                     EXTERNAL SERVICES LAYER                                            |
|                                                                                        |
|  +-----------------+  +------------------+  +------------------+  +----------------+   |
|  | Anthropic       |  | Google Cloud     |  | Google Cloud     |  | Firebase       |   |
|  | Claude API      |  | Speech-to-Text   |  | Text-to-Speech   |  | Cloud          |   |
|  |                 |  |                  |  |                  |  | Messaging      |   |
|  | - claude-sonnet |  | - zh-TW locale   |  | - cmn-TW-Wavenet |  |                |   |
|  | - Streaming API |  | - Medical vocab  |  | - SSML support   |  | - Push notif.  |   |
|  | - 200K context  |  | - Streaming      |  | - Audio format:  |  | - iOS + Android|   |
|  |                 |  |   recognition    |  |   LINEAR16/MP3   |  |                |   |
|  +-----------------+  +------------------+  +------------------+  +----------------+   |
|                                                                                        |
+========================================================================================+

+========================================================================================+
|                     MONITORING & OBSERVABILITY LAYER                                   |
|                                                                                        |
|  +--------------+  +---------------+  +-------------+  +--------------+                |
|  | Prometheus   |  | Grafana       |  | Loki /      |  | Jaeger /     |                |
|  | (Metrics)    |  | (Dashboards)  |  | ELK Stack   |  | OpenTelemetry|                |
|  |              |  |               |  | (Logs)      |  | (Tracing)    |                |
|  +--------------+  +---------------+  +-------------+  +--------------+                |
|                                                                                        |
|  +--------------+  +---------------+                                                   |
|  | AlertManager |  | PagerDuty /   |                                                   |
|  | (Alerts)     |  | Opsgenie      |                                                   |
|  +--------------+  +---------------+                                                   |
|                                                                                        |
+========================================================================================+
```

### 1.2 資料流程圖 (Data Flow -- Voice Consultation Session)

```
Patient App                   Backend                        External Services
    |                            |                                |
    |  1. Start Session (REST)   |                                |
    |--------------------------->|                                |
    |  2. WebSocket Established  |                                |
    |<=========================>|                                |
    |                            |                                |
    |  3. Audio Stream (binary)  |                                |
    |==========================>|  4. Forward to STT             |
    |                            |------------------------------->|
    |                            |  5. Transcript (streaming)     |  Google STT
    |                            |<-------------------------------|
    |                            |                                |
    |                            |  6. Send to Claude API         |
    |                            |------------------------------->|
    |                            |  7. AI Response (streaming)    |  Claude API
    |                            |<-------------------------------|
    |                            |                                |
    |                            |  8. Convert to Speech          |
    |                            |------------------------------->|
    |                            |  9. Audio response             |  Google TTS
    |                            |<-------------------------------|
    |                            |                                |
    | 10. AI Audio (binary)      |                                |
    |<==========================|                                |
    |                            |                                |
    | 11. [If Red Flag Detected] |                                |
    |                            |--- Push Notification --------->| FCM
    |                            |--- WebSocket Alert ----------->| Doctor Dashboard
    |                            |                                |
    | 12. End Session            |                                |
    |--------------------------->|                                |
    |                            | 13. Generate SOAP (async)      |
    |                            |------------------------------->| Claude API
    |  14. SOAP Report Ready     |<-------------------------------|
    |<---------------------------|                                |
```

### 1.3 元件責任矩陣 (Component Responsibility Matrix)

| 元件 (Component) | 主要職責 | 技術選型 | 備註 |
|---|---|---|---|
| API Gateway | 路由、限流、TLS 終結 | NGINX Ingress Controller | 支援 gRPC passthrough |
| REST API Server | 業務邏輯處理 | FastAPI (Python 3.12+) | 多實例水平擴展 |
| WebSocket Gateway | 即時語音串流 | FastAPI WebSocket | Sticky session 必要 |
| Background Worker | 非同步任務處理 | Celery 5.x + Redis Broker | 獨立擴展 |
| Connection Pooler | 資料庫連線池 | PgBouncer 1.21+ | Transaction mode |
| Cache Layer | 快取、Session、限流 | Redis 7+ Cluster | 3-node minimum |
| Object Storage | 音檔、報告儲存 | S3 / GCS | 加密 at rest |

---

## 2. 部署架構

### 2.1 Docker 容器化策略 (Containerization Strategy)

本系統採用微服務容器化架構，每個服務獨立建構 Docker image，並遵循以下原則：

- 基於最小化 base image (python:3.12-slim / node:20-alpine)
- Multi-stage build 減少最終 image 大小
- Non-root user 運行所有容器
- 健康檢查端點內建於每個服務

#### 容器清單 (Container Inventory)

| Container Name | Base Image | Purpose | Exposed Port |
|---|---|---|---|
| `gu-api` | python:3.12-slim | FastAPI REST API Server | 8000 |
| `gu-ws-gateway` | python:3.12-slim | WebSocket Gateway | 8001 |
| `gu-worker` | python:3.12-slim | Celery Background Worker | -- (no port) |
| `gu-worker-beat` | python:3.12-slim | Celery Beat Scheduler | -- (no port) |
| `gu-web` | node:20-alpine + nginx | React Web Dashboard (SPA) | 80 |
| `gu-migration` | python:3.12-slim | Alembic DB Migration Runner | -- (job) |
| `pgbouncer` | edoburu/pgbouncer:1.21 | Connection Pooler | 6432 |
| `redis` | redis:7-alpine | Cache / Broker | 6379 |
| `postgres` | postgres:15-alpine | Database (dev/staging only) | 5432 |

#### Dockerfile 範例 -- API Server

```dockerfile
# ---- Build Stage ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements/production.txt requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.12-slim AS runtime

# Security: non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# WeasyPrint / PDF 系統依賴 (pango, libffi, cairo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libffi-dev libcairo2 libgdk-pixbuf2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY ./app /app/app
COPY ./alembic /app/alembic
COPY ./alembic.ini /app/alembic.ini

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

#### gu-web 部署策略

Web Dashboard (React SPA) 支援兩種部署方式：

**方式 A -- CDN 靜態託管（建議 Production 使用）：**

- 使用 `npm run build` 產出靜態檔案
- 上傳至 S3/GCS bucket，透過 CloudFront / Cloud CDN 分發
- 搭配 Cloudflare 提供 DDoS 保護與邊緣快取
- 優點：全球低延遲、無需管理容器

**方式 B -- K8s Deployment（Staging / 需內部存取控制時使用）：**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gu-web
  namespace: gu-production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gu-web
  template:
    metadata:
      labels:
        app: gu-web
    spec:
      containers:
        - name: gu-web
          image: REGISTRY/gu-web:TAG
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "200m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /
              port: 80
            periodSeconds: 30
```

### 2.2 Docker Compose -- 本地開發與 Staging 環境

```yaml
# docker-compose.yml
version: "3.9"

x-common-env: &common-env
  DATABASE_URL: postgresql://gu_user:gu_password@postgres:5432/gu_voice_db
  REDIS_URL: redis://redis:6379/0
  APP_LOG_LEVEL: DEBUG
  APP_ENV: development

services:
  # ---- Database ----
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: gu_voice_db
      POSTGRES_USER: gu_user
      POSTGRES_PASSWORD: gu_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gu_user -d gu_voice_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  pgbouncer:
    image: edoburu/pgbouncer:1.21.0
    environment:
      DATABASE_URL: postgresql://gu_user:gu_password@postgres:5432/gu_voice_db
      POOL_MODE: transaction
      MAX_CLIENT_CONN: 200
      DEFAULT_POOL_SIZE: 25
    ports:
      - "6432:6432"
    depends_on:
      postgres:
        condition: service_healthy

  # ---- Cache / Broker ----
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # ---- API Server ----
  api:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
      target: runtime
    environment:
      <<: *common-env
      APP_PORT: "8000"
      PGBOUNCER_URL: postgresql://gu_user:gu_password@pgbouncer:6432/gu_voice_db
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app:ro
    depends_on:
      pgbouncer:
        condition: service_started
      redis:
        condition: service_healthy
    restart: unless-stopped

  # ---- WebSocket Gateway ----
  ws-gateway:
    build:
      context: .
      dockerfile: docker/Dockerfile.ws
    environment:
      <<: *common-env
      APP_PORT: "8001"
      WS_MAX_CONNECTIONS: "100"
    ports:
      - "8001:8001"
    depends_on:
      - redis
      - api
    restart: unless-stopped

  # ---- Background Worker ----
  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
      target: runtime
    command: celery -A app.worker.app worker --loglevel=info --concurrency=4
    environment:
      <<: *common-env
      CELERY_BROKER_URL: redis://redis:6379/1
      CELERY_RESULT_BACKEND: redis://redis:6379/2
    depends_on:
      - redis
      - pgbouncer
    restart: unless-stopped

  # ---- Celery Beat (Scheduler) ----
  worker-beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
      target: runtime
    command: celery -A app.worker.app beat --loglevel=info
    environment:
      <<: *common-env
      CELERY_BROKER_URL: redis://redis:6379/1
    depends_on:
      - redis
    restart: unless-stopped

  # ---- Web Dashboard ----
  web:
    build:
      context: ./web
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    environment:
      REACT_APP_API_URL: http://localhost:8000
      REACT_APP_WS_URL: ws://localhost:8001
    depends_on:
      - api

  # ---- Mock Services (dev only) ----
  mock-llm:
    build:
      context: ./mocks
      dockerfile: Dockerfile.mock-llm
    ports:
      - "9100:9100"

  mock-stt:
    build:
      context: ./mocks
      dockerfile: Dockerfile.mock-stt
    ports:
      - "9101:9101"

  mock-tts:
    build:
      context: ./mocks
      dockerfile: Dockerfile.mock-tts
    ports:
      - "9102:9102"

volumes:
  postgres_data:
  redis_data:
```

### 2.3 Kubernetes 生產環境部署

#### 2.3.1 Namespace 設計

```
Cluster
  |
  +-- namespace: gu-production       # 正式環境所有服務
  +-- namespace: gu-staging          # Staging 環境
  +-- namespace: gu-monitoring       # Prometheus, Grafana, Loki, Jaeger
  +-- namespace: gu-ingress          # NGINX Ingress Controller
  +-- namespace: cert-manager        # TLS 憑證自動化
  +-- namespace: gu-jobs             # CronJob, one-off migration jobs
```

#### 2.3.2 Pod 規格 (Pod Specifications)

**API Server Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gu-api
  namespace: gu-production
  labels:
    app: gu-api
    tier: application
    version: v1
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: gu-api
  template:
    metadata:
      labels:
        app: gu-api
        tier: application
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: gu-api-sa
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      terminationGracePeriodSeconds: 60
      containers:
        - name: gu-api
          image: REGISTRY/gu-api:TAG
          ports:
            - containerPort: 8000
              protocol: TCP
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          envFrom:
            - configMapRef:
                name: gu-app-config
            - secretRef:
                name: gu-app-secrets
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 20
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 12
          volumeMounts:
            - name: tmp-volume
              mountPath: /tmp
      volumes:
        - name: tmp-volume
          emptyDir:
            sizeLimit: 100Mi
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - gu-api
                topologyKey: kubernetes.io/hostname
```

**WebSocket Gateway Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gu-ws-gateway
  namespace: gu-production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gu-ws-gateway
  template:
    metadata:
      labels:
        app: gu-ws-gateway
    spec:
      containers:
        - name: gu-ws-gateway
          image: REGISTRY/gu-ws-gateway:TAG
          ports:
            - containerPort: 8001
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1500m"
              memory: "1Gi"
          env:
            - name: WS_MAX_CONNECTIONS
              value: "500"
            - name: WS_HEARTBEAT_INTERVAL
              value: "30"
            - name: WS_MESSAGE_MAX_SIZE
              value: "1048576"
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            periodSeconds: 10
```

**Celery Worker Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gu-worker
  namespace: gu-production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gu-worker
  template:
    metadata:
      labels:
        app: gu-worker
    spec:
      containers:
        - name: gu-worker
          image: REGISTRY/gu-api:TAG
          command: ["celery", "-A", "app.worker.app", "worker",
                    "--loglevel=info", "--concurrency=4",
                    "--queues=default,soap_generation,audio_processing,notifications"]
          resources:
            requests:
              cpu: "500m"
              memory: "768Mi"
            limits:
              cpu: "2000m"
              memory: "2Gi"
          envFrom:
            - configMapRef:
                name: gu-app-config
            - secretRef:
                name: gu-app-secrets
          livenessProbe:
            exec:
              command:
                - celery
                - -A
                - app.worker.app
                - inspect
                - ping
                - --timeout=10
            periodSeconds: 60
            timeoutSeconds: 15
```

**Celery Beat Scheduler Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gu-worker-beat
  namespace: gu-production
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gu-worker-beat
  template:
    metadata:
      labels:
        app: gu-worker-beat
    spec:
      containers:
        - name: gu-worker-beat
          image: REGISTRY/gu-api:TAG
          command: ["celery", "-A", "app.worker.app", "beat",
                    "--loglevel=info",
                    "--schedule=/tmp/celerybeat-schedule"]
          resources:
            requests:
              cpu: "100m"
              memory: "256Mi"
            limits:
              cpu: "200m"
              memory: "512Mi"
          envFrom:
            - configMapRef:
                name: gu-app-config
            - secretRef:
                name: gu-app-secrets
          volumeMounts:
            - name: beat-schedule
              mountPath: /tmp
      volumes:
        - name: beat-schedule
          emptyDir:
            sizeLimit: 10Mi
```

> **注意：** Celery Beat 僅能運行 1 個 replica，以避免排程任務重複執行。

#### 2.3.3 Services 與 Ingress

```yaml
# ---- API Service ----
apiVersion: v1
kind: Service
metadata:
  name: gu-api-svc
  namespace: gu-production
spec:
  selector:
    app: gu-api
  ports:
    - port: 80
      targetPort: 8000
      protocol: TCP
  type: ClusterIP

---
# ---- WebSocket Service ----
apiVersion: v1
kind: Service
metadata:
  name: gu-ws-svc
  namespace: gu-production
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
spec:
  selector:
    app: gu-ws-gateway
  ports:
    - port: 80
      targetPort: 8001
      protocol: TCP
  type: ClusterIP
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 3600

---
# ---- Ingress ----
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: gu-ingress
  namespace: gu-production
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    nginx.ingress.kubernetes.io/websocket-services: "gu-ws-svc"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
    nginx.ingress.kubernetes.io/limit-rps: "50"
    nginx.ingress.kubernetes.io/limit-connections: "20"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.gu-voice.example.com
        - ws.gu-voice.example.com
      secretName: gu-tls-cert
  rules:
    - host: api.gu-voice.example.com
      http:
        paths:
          - path: /api/v1
            pathType: Prefix
            backend:
              service:
                name: gu-api-svc
                port:
                  number: 80
          - path: /health
            pathType: Exact
            backend:
              service:
                name: gu-api-svc
                port:
                  number: 80
    - host: ws.gu-voice.example.com
      http:
        paths:
          - path: /ws
            pathType: Prefix
            backend:
              service:
                name: gu-ws-svc
                port:
                  number: 80
```

#### 2.3.4 ConfigMaps 與 Secrets

```yaml
# ---- ConfigMap ----
apiVersion: v1
kind: ConfigMap
metadata:
  name: gu-app-config
  namespace: gu-production
data:
  APP_ENV: "production"
  APP_LOG_LEVEL: "WARNING"
  APP_PORT: "8000"
  APP_WORKERS: "4"
  WS_PORT: "8001"
  DB_POOL_SIZE: "20"
  DB_MAX_OVERFLOW: "20"
  REDIS_TTL_DEFAULT: "1800"
  CLAUDE_MODEL_CONVERSATION: "claude-sonnet-4-20250514"
  CLAUDE_MODEL_SOAP: "claude-sonnet-4-20250514"
  CLAUDE_MODEL_RED_FLAG: "claude-haiku-4-5-20251001"
  CLAUDE_TEMPERATURE_CONVERSATION: "0.7"
  CLAUDE_TEMPERATURE_SOAP: "0.3"
  CLAUDE_TEMPERATURE_RED_FLAG: "0.2"
  CLAUDE_MAX_TOKENS_CONVERSATION: "512"
  CLAUDE_MAX_TOKENS_SOAP: "4096"
  GOOGLE_STT_LANGUAGE_CODE: "zh-TW"
  GOOGLE_TTS_VOICE_NAME: "cmn-TW-Wavenet-A"
  GOOGLE_TTS_SPEAKING_RATE: "0.9"
  GOOGLE_TTS_SAMPLE_RATE: "24000"
  ACCESS_TOKEN_EXPIRE_MINUTES: "15"
  REFRESH_TOKEN_EXPIRE_DAYS: "7"
  CORS_ORIGINS: "https://dashboard.gu-voice.example.com"
  PROMETHEUS_PORT: "9090"

---
# ---- Secrets (透過 Sealed Secrets 或 External Secrets Operator 管理) ----
apiVersion: v1
kind: Secret
metadata:
  name: gu-app-secrets
  namespace: gu-production
type: Opaque
stringData:
  DATABASE_URL: "ENC[AES256_GCM,data:...,type:str]"          # Sealed
  REDIS_URL: "ENC[AES256_GCM,data:...,type:str]"             # Sealed
  JWT_PRIVATE_KEY_PATH: "ENC[AES256_GCM,data:...,type:str]"  # Sealed
  JWT_PUBLIC_KEY_PATH: "ENC[AES256_GCM,data:...,type:str]"   # Sealed
  ANTHROPIC_API_KEY: "ENC[AES256_GCM,data:...,type:str]"     # Sealed
  GOOGLE_APPLICATION_CREDENTIALS_JSON: "ENC[...]"            # Sealed
  AWS_ACCESS_KEY_ID: "ENC[AES256_GCM,data:...,type:str]"     # Sealed
  AWS_SECRET_ACCESS_KEY: "ENC[AES256_GCM,data:...,type:str]" # Sealed
  FCM_CREDENTIALS_PATH: "ENC[AES256_GCM,data:...,type:str]"  # Sealed
  SENTRY_DSN: "ENC[AES256_GCM,data:...,type:str]"            # Sealed
  ENCRYPTION_KEY: "ENC[AES256_GCM,data:...,type:str]"        # For PII field encryption
```

#### 2.3.5 Horizontal Pod Autoscaler (HPA)

```yaml
# ---- API Server HPA ----
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gu-api-hpa
  namespace: gu-production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gu-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120

---
# ---- WebSocket Gateway HPA ----
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gu-ws-hpa
  namespace: gu-production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gu-ws-gateway
  minReplicas: 2
  maxReplicas: 6
  metrics:
    - type: Pods
      pods:
        metric:
          name: ws_active_connections
        target:
          type: AverageValue
          averageValue: "200"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 600

---
# ---- Worker HPA ----
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gu-worker-hpa
  namespace: gu-production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gu-worker
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Pods
      pods:
        metric:
          name: celery_queue_depth
        target:
          type: AverageValue
          averageValue: "10"
```

### 2.4 Container Registry 策略

| 環境 | Registry | 說明 |
|---|---|---|
| Development | Local Docker | 本地開發使用 |
| Staging | ghcr.io (GitHub Container Registry) | PR build 自動推送 |
| Production | AWS ECR / GCP Artifact Registry | 正式環境使用私有 registry |

**Image Tagging 策略：**

- `latest` -- 不使用於生產環境，僅 dev 使用
- `<git-sha>` -- 每次 build 產出（如 `gu-api:a1b2c3d`）
- `<semver>` -- Release tag（如 `gu-api:1.2.3`）
- `<branch>-<timestamp>` -- Staging 部署（如 `gu-api:main-20260410-1430`）

**Image 掃描策略：**

- 每次 push 至 registry 自動執行 Trivy 掃描
- Critical / High 漏洞阻擋部署
- 每週排程掃描所有 production images

---

## 3. 網路架構

### 3.1 VPC 設計

```
+====================================================================+
|                    VPC: gu-voice-vpc                                |
|                    CIDR: 10.0.0.0/16                               |
|                                                                    |
|  +------------------------------+  +-----------------------------+ |
|  | Availability Zone A          |  | Availability Zone B         | |
|  |                              |  |                             | |
|  | +-------------------------+  |  | +--------------------------+| |
|  | | Public Subnet           |  |  | | Public Subnet            || |
|  | | 10.0.1.0/24             |  |  | | 10.0.2.0/24              || |
|  | | - NAT Gateway           |  |  | | - NAT Gateway            || |
|  | | - Load Balancer          |  |  | | - Load Balancer          || |
|  | | - Bastion Host (opt.)   |  |  | |                          || |
|  | +-------------------------+  |  | +--------------------------+| |
|  |                              |  |                             | |
|  | +-------------------------+  |  | +--------------------------+| |
|  | | Private Subnet (App)    |  |  | | Private Subnet (App)     || |
|  | | 10.0.10.0/24            |  |  | | 10.0.20.0/24             || |
|  | | - K8s Worker Nodes      |  |  | | - K8s Worker Nodes       || |
|  | | - API Pods              |  |  | | - API Pods               || |
|  | | - Worker Pods           |  |  | | - Worker Pods            || |
|  | +-------------------------+  |  | +--------------------------+| |
|  |                              |  |                             | |
|  | +-------------------------+  |  | +--------------------------+| |
|  | | Private Subnet (Data)   |  |  | | Private Subnet (Data)    || |
|  | | 10.0.100.0/24           |  |  | | 10.0.200.0/24            || |
|  | | - PostgreSQL Primary    |  |  | | - PostgreSQL Replica     || |
|  | | - Redis Primary         |  |  | | - Redis Replica          || |
|  | | - PgBouncer             |  |  | | - PgBouncer              || |
|  | +-------------------------+  |  | +--------------------------+| |
|  +------------------------------+  +-----------------------------+ |
|                                                                    |
+====================================================================+
```

### 3.2 Subnet 配置

| Subnet 名稱 | CIDR | 類型 | AZ | 用途 |
|---|---|---|---|---|
| public-a | 10.0.1.0/24 | Public | AZ-A | NAT Gateway, ALB, Bastion |
| public-b | 10.0.2.0/24 | Public | AZ-B | NAT Gateway, ALB |
| app-a | 10.0.10.0/24 | Private | AZ-A | K8s worker nodes, app pods |
| app-b | 10.0.20.0/24 | Private | AZ-B | K8s worker nodes, app pods |
| data-a | 10.0.100.0/24 | Private | AZ-A | PostgreSQL Primary, Redis |
| data-b | 10.0.200.0/24 | Private | AZ-B | PostgreSQL Replica, Redis Replica |

### 3.3 Security Groups / 防火牆規則

**SG-ALB (Application Load Balancer):**

| 方向 | Protocol | Port | Source/Dest | 說明 |
|---|---|---|---|---|
| Inbound | TCP | 443 | 0.0.0.0/0 | HTTPS from internet |
| Inbound | TCP | 80 | 0.0.0.0/0 | HTTP (redirect to 443) |
| Outbound | TCP | 8000 | SG-App | Forward to API pods |
| Outbound | TCP | 8001 | SG-App | Forward to WS pods |

**SG-App (Application Layer):**

| 方向 | Protocol | Port | Source/Dest | 說明 |
|---|---|---|---|---|
| Inbound | TCP | 8000 | SG-ALB | From load balancer |
| Inbound | TCP | 8001 | SG-ALB | WebSocket from LB |
| Inbound | TCP | 9090 | SG-Monitoring | Prometheus scrape |
| Outbound | TCP | 6432 | SG-Data | To PgBouncer |
| Outbound | TCP | 6379 | SG-Data | To Redis |
| Outbound | TCP | 443 | 0.0.0.0/0 | External APIs (Claude, Google, FCM) |

**SG-Data (Database Layer):**

| 方向 | Protocol | Port | Source/Dest | 說明 |
|---|---|---|---|---|
| Inbound | TCP | 6432 | SG-App | PgBouncer from app |
| Inbound | TCP | 5432 | SG-Data | PostgreSQL replication |
| Inbound | TCP | 6379 | SG-App | Redis from app |
| Inbound | TCP | 6379 | SG-Data | Redis replication |
| Outbound | TCP | 5432 | SG-Data | Replication traffic |

**SG-Monitoring:**

| 方向 | Protocol | Port | Source/Dest | 說明 |
|---|---|---|---|---|
| Inbound | TCP | 3000 | VPN/Bastion | Grafana UI |
| Inbound | TCP | 9090 | VPN/Bastion | Prometheus UI |
| Outbound | TCP | 9090 | SG-App | Scrape app metrics |
| Outbound | TCP | 9100 | SG-App, SG-Data | Node exporter |

### 3.4 TLS 終結

- **外部 TLS：** 於 ALB / Ingress Controller 終結，使用 ACM (AWS) 或 cert-manager (K8s) 管理憑證
- **內部 TLS：** 使用 mTLS (Mutual TLS) 透過 service mesh (Istio/Linkerd) 實現 pod 間加密通訊
- **最低版本：** TLS 1.3 (僅允許 TLS_AES_256_GCM_SHA384, TLS_CHACHA20_POLY1305_SHA256)
- **HSTS：** max-age=31536000; includeSubDomains; preload
- **憑證輪換：** Let's Encrypt 憑證每 60 天自動輪換（有效期 90 天）

### 3.5 Domain 與 DNS 設定

| Domain | 指向 | 用途 |
|---|---|---|
| `api.gu-voice.example.com` | ALB/Ingress (CNAME) | REST API 端點 |
| `ws.gu-voice.example.com` | ALB/Ingress (CNAME) | WebSocket 端點 |
| `dashboard.gu-voice.example.com` | CDN (CNAME) | 醫師 Web Dashboard |
| `admin.gu-voice.example.com` | ALB/Ingress (CNAME) | 管理後台 |
| `monitoring.gu-voice.example.com` | Internal LB (CNAME) | Grafana (VPN only) |

DNS 提供商：Cloudflare DNS（支援 DNSSEC、DDoS 保護、WAF）

### 3.6 內部服務發現 (Internal Service Discovery)

Kubernetes 內建 DNS (CoreDNS) 用於 Pod 間通訊：

- API Server: `gu-api-svc.gu-production.svc.cluster.local`
- WebSocket: `gu-ws-svc.gu-production.svc.cluster.local`
- PgBouncer: `pgbouncer-svc.gu-production.svc.cluster.local:6432`
- Redis: `redis-svc.gu-production.svc.cluster.local:6379`
- Prometheus: `prometheus-svc.gu-monitoring.svc.cluster.local:9090`

---

## 4. CI/CD Pipeline

### 4.1 Pipeline 總覽

```
[Developer Push/PR]
       |
       v
+------------------+     +-------------------+     +------------------+
| lint-and-test.yml| --> | build-and-push.yml| --> | deploy-staging   |
| (On PR)          |     | (On merge main)   |     | (Auto on main)   |
+------------------+     +-------------------+     +------------------+
                                                          |
                                                          v
                                                   +------------------+
                                                   | test-e2e         |
                                                   | (After staging)  |
                                                   +------------------+
                                                          |
                                                          v
                                                   +------------------+
                                                   | deploy-production|
                                                   | (Manual approval)|
                                                   +------------------+
```

### 4.2 Workflow 詳細說明

#### 4.2.1 lint-and-test.yml (PR 觸發)

觸發條件：所有 Pull Request（針對 main 分支）
目的：確保程式碼品質與測試通過

```yaml
name: Lint & Test

on:
  pull_request:
    branches: [main]
    paths-ignore:
      - "docs/**"
      - "*.md"

concurrency:
  group: test-${{ github.head_ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
      - name: Install dependencies
        run: pip install -r requirements/dev.txt
      - name: Ruff lint
        run: ruff check app/ tests/
      - name: Ruff format check
        run: ruff format --check app/ tests/
      - name: MyPy type checking
        run: mypy app/ --strict
      - name: Security lint (Bandit)
        run: bandit -r app/ -c pyproject.toml

  test-unit:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
      - name: Install dependencies
        run: pip install -r requirements/test.txt
      - name: Run unit tests
        run: pytest tests/unit/ -v --cov=app --cov-report=xml --cov-fail-under=80
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  test-integration:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
        ports:
          - 5432:5432
        options: >-
          --health-cmd="pg_isready"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd="redis-cli ping"
          --health-interval=10s
    env:
      DATABASE_URL: postgresql://test_user:test_pass@localhost:5432/test_db
      REDIS_URL: redis://localhost:6379/0
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements/test.txt
      - name: Run migrations
        run: alembic upgrade head
      - name: Run integration tests
        run: pytest tests/integration/ -v --timeout=120

  test-web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm test -- --coverage --watchAll=false

  test-mobile:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./mobile
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: mobile/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm test -- --coverage --watchAll=false

  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Snyk Python scan
        uses: snyk/actions/python-3.10@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high
      - name: Snyk Node scan
        uses: snyk/actions/node@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high
          working-directory: ./web
```

#### 4.2.2 build-and-push.yml (合併至 main 觸發)

觸發條件：Push to main (merge commit)
目的：建構 Docker images 並推送至 Container Registry

```yaml
name: Build & Push

on:
  push:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_PREFIX: ${{ github.repository }}

jobs:
  build-api:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
      digest: ${{ steps.build.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api
          tags: |
            type=sha,prefix=
            type=raw,value=main-{{date 'YYYYMMDDHHmm'}}
      - id: build
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.api
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: Trivy vulnerability scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api@${{ steps.build.outputs.digest }}
          format: table
          exit-code: 1
          severity: CRITICAL,HIGH

  build-ws:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-ws-gateway
          tags: type=sha,prefix=
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.ws
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  build-web:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-web
          tags: type=sha,prefix=
      - uses: docker/build-push-action@v5
        with:
          context: ./web
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

#### 4.2.3 deploy-staging.yml (自動部署至 Staging)

觸發條件：build-and-push workflow 成功完成
目的：自動將新 build 部署至 staging 環境

```yaml
name: Deploy to Staging

on:
  workflow_run:
    workflows: ["Build & Push"]
    types: [completed]
    branches: [main]

jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          method: kubeconfig
          kubeconfig: ${{ secrets.KUBE_CONFIG_STAGING }}
      - name: Get image tag
        id: tag
        run: echo "TAG=$(git rev-parse --short HEAD)" >> $GITHUB_OUTPUT
      - name: Run database migrations
        run: |
          kubectl -n gu-staging create job --from=cronjob/db-migration \
            db-migration-${{ steps.tag.outputs.TAG }} || true
          kubectl -n gu-staging wait --for=condition=complete \
            job/db-migration-${{ steps.tag.outputs.TAG }} --timeout=300s
      - name: Deploy API
        run: |
          kubectl -n gu-staging set image deployment/gu-api \
            gu-api=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ steps.tag.outputs.TAG }}
          kubectl -n gu-staging rollout status deployment/gu-api --timeout=300s
      - name: Deploy WebSocket Gateway
        run: |
          kubectl -n gu-staging set image deployment/gu-ws-gateway \
            gu-ws-gateway=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-ws-gateway:${{ steps.tag.outputs.TAG }}
          kubectl -n gu-staging rollout status deployment/gu-ws-gateway --timeout=300s
      - name: Deploy Workers
        run: |
          kubectl -n gu-staging set image deployment/gu-worker \
            gu-worker=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ steps.tag.outputs.TAG }}
          kubectl -n gu-staging rollout status deployment/gu-worker --timeout=300s
      - name: Deploy Beat Scheduler
        run: |
          kubectl -n gu-staging set image deployment/gu-worker-beat \
            gu-worker-beat=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ steps.tag.outputs.TAG }}
          kubectl -n gu-staging rollout status deployment/gu-worker-beat --timeout=300s
      - name: Smoke tests
        run: |
          STAGING_URL="https://api-staging.gu-voice.example.com"
          curl -sf "${STAGING_URL}/health" || exit 1
          curl -sf "${STAGING_URL}/health/ready" || exit 1
      - name: Notify on failure
        if: failure()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {"text": "[STAGING] Deployment failed for commit ${{ steps.tag.outputs.TAG }}"}
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}

  test-e2e:
    needs: deploy
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements/test.txt
      - name: Run E2E tests against staging
        env:
          E2E_BASE_URL: https://api-staging.gu-voice.example.com
          E2E_WS_URL: wss://ws-staging.gu-voice.example.com
        run: pytest tests/e2e/ -v --timeout=300
```

#### 4.2.4 deploy-production.yml (手動核准部署至 Production)

觸發條件：手動觸發，需經過核准
目的：將經過 staging 驗證的版本部署至生產環境

```yaml
name: Deploy to Production

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag to deploy (git short SHA)"
        required: true
        type: string
      confirm_rollback_plan:
        description: "I have reviewed the rollback plan"
        required: true
        type: boolean
        default: false

jobs:
  pre-deploy-checks:
    runs-on: ubuntu-latest
    steps:
      - name: Validate inputs
        run: |
          if [ "${{ inputs.confirm_rollback_plan }}" != "true" ]; then
            echo "ERROR: You must confirm the rollback plan before deploying."
            exit 1
          fi
      - name: Verify image exists in staging
        run: |
          docker manifest inspect ${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ inputs.image_tag }}

  deploy:
    needs: pre-deploy-checks
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://api.gu-voice.example.com
    steps:
      - uses: actions/checkout@v4
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          method: kubeconfig
          kubeconfig: ${{ secrets.KUBE_CONFIG_PRODUCTION }}
      - name: Record pre-deployment state
        id: pre-state
        run: |
          echo "API_IMAGE=$(kubectl -n gu-production get deployment gu-api -o jsonpath='{.spec.template.spec.containers[0].image}')" >> $GITHUB_OUTPUT
          echo "WS_IMAGE=$(kubectl -n gu-production get deployment gu-ws-gateway -o jsonpath='{.spec.template.spec.containers[0].image}')" >> $GITHUB_OUTPUT
      - name: Run database migrations
        run: |
          kubectl -n gu-production create job --from=cronjob/db-migration \
            db-migration-${{ inputs.image_tag }} || true
          kubectl -n gu-production wait --for=condition=complete \
            job/db-migration-${{ inputs.image_tag }} --timeout=600s
      - name: Canary deploy (10%)
        run: |
          kubectl -n gu-production set image deployment/gu-api-canary \
            gu-api=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ inputs.image_tag }}
          kubectl -n gu-production rollout status deployment/gu-api-canary --timeout=300s
          echo "Waiting 5 minutes for canary validation..."
          sleep 300
      - name: Check canary health
        run: |
          ERROR_RATE=$(curl -s "http://prometheus.gu-monitoring:9090/api/v1/query?query=rate(http_requests_total{deployment='gu-api-canary',status=~'5..'}[5m])/rate(http_requests_total{deployment='gu-api-canary'}[5m])" | jq -r '.data.result[0].value[1] // "0"')
          if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
            echo "Canary error rate too high: ${ERROR_RATE}"
            exit 1
          fi
      - name: Full rollout
        run: |
          kubectl -n gu-production set image deployment/gu-api \
            gu-api=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ inputs.image_tag }}
          kubectl -n gu-production rollout status deployment/gu-api --timeout=600s

          kubectl -n gu-production set image deployment/gu-ws-gateway \
            gu-ws-gateway=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-ws-gateway:${{ inputs.image_tag }}
          kubectl -n gu-production rollout status deployment/gu-ws-gateway --timeout=300s

          kubectl -n gu-production set image deployment/gu-worker \
            gu-worker=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ inputs.image_tag }}
          kubectl -n gu-production rollout status deployment/gu-worker --timeout=300s

          kubectl -n gu-production set image deployment/gu-worker-beat \
            gu-worker-beat=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:${{ inputs.image_tag }}
          kubectl -n gu-production rollout status deployment/gu-worker-beat --timeout=300s
      - name: Post-deploy verification
        run: |
          curl -sf "https://api.gu-voice.example.com/health" || exit 1
          curl -sf "https://api.gu-voice.example.com/health/ready" || exit 1
      - name: Create GitHub release
        uses: ncipollo/release-action@v1
        with:
          tag: deploy-${{ inputs.image_tag }}
          name: "Production Deploy ${{ inputs.image_tag }}"
          body: |
            Deployed to production at $(date -u +%Y-%m-%dT%H:%M:%SZ)
            Previous API image: ${{ steps.pre-state.outputs.API_IMAGE }}
      - name: Rollback on failure
        if: failure()
        run: |
          echo "Rolling back to previous version..."
          kubectl -n gu-production rollout undo deployment/gu-api
          kubectl -n gu-production rollout undo deployment/gu-ws-gateway
          kubectl -n gu-production rollout undo deployment/gu-worker
          kubectl -n gu-production rollout undo deployment/gu-worker-beat
          kubectl -n gu-production rollout status deployment/gu-api --timeout=300s
```

#### 4.2.5 database-migration.yml

觸發條件：手動或自動（deploy workflow 中呼叫）
目的：安全執行資料庫遷移

```yaml
name: Database Migration

on:
  workflow_dispatch:
    inputs:
      environment:
        description: "Target environment"
        required: true
        type: choice
        options:
          - staging
          - production
      migration_command:
        description: "Alembic command (default: upgrade head)"
        required: false
        default: "upgrade head"

jobs:
  migrate:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v4
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          method: kubeconfig
          kubeconfig: ${{ secrets[format('KUBE_CONFIG_{0}', inputs.environment)] }}
      - name: Create backup before migration
        if: inputs.environment == 'production'
        run: |
          kubectl -n gu-${{ inputs.environment }} create job --from=cronjob/db-backup \
            db-backup-pre-migration-$(date +%s) || true
      - name: Run migration
        run: |
          kubectl -n gu-${{ inputs.environment }} run db-migration-$(date +%s) \
            --image=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:latest \
            --restart=Never \
            --env="DATABASE_URL=${{ secrets.DATABASE_URL }}" \
            --command -- alembic ${{ inputs.migration_command }}
      - name: Verify migration
        run: |
          kubectl -n gu-${{ inputs.environment }} run db-check-$(date +%s) \
            --image=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}/gu-api:latest \
            --restart=Never \
            --env="DATABASE_URL=${{ secrets.DATABASE_URL }}" \
            --command -- alembic current
```

### 4.3 Build 階段流程

```
+--------+    +--------+    +--------+    +--------+    +--------+
|  Lint  | -> |  Test  | -> | Build  | -> |  Push  | -> | Deploy |
+--------+    +--------+    +--------+    +--------+    +--------+
| Ruff     |  | pytest   |  | Docker   |  | ghcr.io  |  | kubectl |
| MyPy     |  | unit     |  | multi-   |  | ECR/GAR  |  | rollout |
| Bandit   |  | integr.  |  | stage    |  | Trivy    |  | canary  |
| ESLint   |  | e2e      |  | build    |  | scan     |  | verify  |
+----------+  +----------+  +----------+  +----------+  +---------+
```

### 4.4 環境晉升 (Environment Promotion)

```
Development (Local)  -->  Staging  -->  Production
      |                      |                |
  docker-compose        K8s cluster       K8s cluster
  mock services         real APIs         real APIs
  seed data             staging data      production data
  auto deploy           auto on main      manual approval
      |                      |                |
  Feature branch         main branch      Tagged release
```

晉升條件：

| 階段 | 觸發 | 前提條件 |
|---|---|---|
| Dev -> Staging | Merge PR to main | Lint + Test 通過, Code review 核准 |
| Staging -> Prod | 手動觸發 | Staging smoke test 通過, E2E test 通過, QA sign-off, 回滾計畫確認 |

### 4.5 回滾程序 (Rollback Procedures)

**自動回滾觸發條件：**

- 部署後健康檢查失敗
- Canary 階段錯誤率超過 5%
- Pod 持續 CrashLoopBackOff

**手動回滾步驟：**

```bash
# 1. 確認當前狀態
kubectl -n gu-production rollout history deployment/gu-api

# 2. 回滾至前一版本
kubectl -n gu-production rollout undo deployment/gu-api
kubectl -n gu-production rollout undo deployment/gu-ws-gateway
kubectl -n gu-production rollout undo deployment/gu-worker
kubectl -n gu-production rollout undo deployment/gu-worker-beat

# 3. 監控回滾狀態
kubectl -n gu-production rollout status deployment/gu-api

# 4. 若需回滾資料庫遷移 (謹慎操作)
kubectl -n gu-production run db-rollback-$(date +%s) \
  --image=REGISTRY/gu-api:PREVIOUS_TAG \
  --restart=Never \
  --command -- alembic downgrade -1

# 5. 驗證服務正常
curl -sf https://api.gu-voice.example.com/health
```

**回滾 SLA：** 從決定回滾到服務恢復不超過 10 分鐘。

---

## 5. 監控與可觀測性

### 5.1 Metrics 收集 (Prometheus)

#### 5.1.1 應用程式指標 (Application Metrics)

```python
# app/middleware/metrics.py -- Prometheus metrics definition

from prometheus_client import Counter, Histogram, Gauge, Info

# ---- Request Metrics ----
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ---- WebSocket Metrics ----
WS_ACTIVE_CONNECTIONS = Gauge(
    "ws_active_connections",
    "Number of active WebSocket connections"
)

WS_MESSAGES_TOTAL = Counter(
    "ws_messages_total",
    "Total WebSocket messages",
    ["direction", "type"]  # direction: inbound/outbound, type: audio/text/control
)

# ---- AI Pipeline Metrics ----
STT_LATENCY = Histogram(
    "stt_processing_duration_seconds",
    "Speech-to-Text processing latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

LLM_LATENCY = Histogram(
    "llm_processing_duration_seconds",
    "Claude LLM response latency",
    ["model", "task_type"],  # task_type: conversation/soap_generation/red_flag_check
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0]
)

TTS_LATENCY = Histogram(
    "tts_processing_duration_seconds",
    "Text-to-Speech processing latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

LLM_TOKEN_USAGE = Counter(
    "llm_token_usage_total",
    "Total LLM tokens consumed",
    ["model", "token_type"]  # token_type: input/output
)

# ---- Session Metrics ----
ACTIVE_SESSIONS = Gauge(
    "consultation_active_sessions",
    "Number of active consultation sessions"
)

SESSION_DURATION = Histogram(
    "consultation_session_duration_seconds",
    "Consultation session duration",
    buckets=[60, 120, 300, 600, 900, 1200, 1800]
)

SESSION_TIMEOUT_TOTAL = Counter(
    "session_timeout_total",
    "Total number of session timeouts"
)

# ---- Notification Metrics ----
NOTIFICATION_DELIVERY_FAILURES = Counter(
    "notification_delivery_failures_total",
    "Total notification delivery failures",
    ["type"]  # type: fcm/websocket/email
)
```

#### 5.1.2 業務指標 (Business Metrics)

| 指標名稱 | 類型 | Labels | 說明 |
|---|---|---|---|
| `consultation_sessions_total` | Counter | `doctor_id`, `status` | 問診總場次 |
| `red_flags_triggered_total` | Counter | `flag_type`, `severity` | 紅旗警示觸發次數 |
| `soap_generation_total` | Counter | `status` | SOAP 報告產生次數 |
| `soap_generation_duration_seconds` | Histogram | -- | SOAP 報告產生耗時 |
| `patient_satisfaction_score` | Histogram | -- | 病患滿意度評分分佈 |
| `doctor_review_time_seconds` | Histogram | -- | 醫師審閱 SOAP 報告耗時 |
| `audio_recording_size_bytes` | Histogram | -- | 錄音檔案大小分佈 |
| `session_timeout_total` | Counter | -- | 場次逾時中斷次數 |
| `notification_delivery_failures_total` | Counter | `type` | 通知發送失敗次數 |

#### 5.1.3 基礎設施指標 (Infrastructure Metrics)

透過以下 Exporter 自動收集：

- **Node Exporter：** CPU, memory, disk I/O, network I/O (per node)
- **kube-state-metrics：** Pod status, deployment replicas, HPA state
- **PgBouncer Exporter：** Active connections, waiting connections, pool utilization
- **Redis Exporter：** Memory usage, connected clients, commands/sec, keyspace hits/misses
- **PostgreSQL Exporter：** Connections, transactions/sec, replication lag, table/index stats

Prometheus 抓取設定 (scrape config)：

```yaml
scrape_configs:
  - job_name: "gu-api"
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names: ["gu-production"]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:$1
    scrape_interval: 15s

  - job_name: "pgbouncer"
    static_configs:
      - targets: ["pgbouncer-exporter:9127"]
    scrape_interval: 30s

  - job_name: "redis"
    static_configs:
      - targets: ["redis-exporter:9121"]
    scrape_interval: 30s

  - job_name: "postgres"
    static_configs:
      - targets: ["postgres-exporter:9187"]
    scrape_interval: 30s
```

### 5.2 日誌系統 (Logging)

#### 5.2.1 日誌層級與格式 (Log Levels & Format)

所有服務採用結構化 JSON 日誌格式：

```json
{
  "timestamp": "2026-04-10T14:30:00.123Z",
  "level": "INFO",
  "logger": "gu_api.services.consultation",
  "message": "Consultation session started",
  "trace_id": "abc123def456",
  "span_id": "span789",
  "request_id": "req-uuid-001",
  "user_id": "usr-uuid-hash",
  "session_id": "sess-uuid-002",
  "doctor_id": "doc-uuid-hash",
  "environment": "production",
  "service": "gu-api",
  "version": "1.2.3",
  "extra": {
    "session_type": "initial_consultation",
    "department": "urology"
  }
}
```

日誌層級使用規範：

| Level | 用途 | 範例 |
|---|---|---|
| CRITICAL | 系統無法運作 | 資料庫連線完全中斷 |
| ERROR | 請求失敗但系統仍運作 | Claude API 回傳 500, STT 辨識失敗 |
| WARNING | 潛在問題但未影響功能 | API 回應超過 3 秒, 連線池使用率 > 80% |
| INFO | 重要業務事件 | 問診開始/結束, SOAP 報告產生, Red flag 觸發 |
| DEBUG | 除錯用詳細資訊 | 生產環境預設關閉 |

#### 5.2.2 結構化日誌欄位 (Structured Logging Fields)

| 欄位 | 必填 | 說明 |
|---|---|---|
| `timestamp` | 是 | ISO 8601 格式，UTC 時區 |
| `level` | 是 | 日誌層級 |
| `logger` | 是 | Logger 名稱（模組路徑） |
| `message` | 是 | 人類可讀訊息 |
| `trace_id` | 是 | OpenTelemetry trace ID |
| `span_id` | 是 | OpenTelemetry span ID |
| `request_id` | 是 | 唯一請求識別碼 |
| `user_id` | 視情況 | 使用者識別碼（已雜湊） |
| `session_id` | 視情況 | 問診 session 識別碼 |
| `service` | 是 | 服務名稱 |
| `version` | 是 | 應用程式版本 |
| `environment` | 是 | 環境名稱 |
| `error.type` | 視情況 | 例外類型 |
| `error.stack` | 視情況 | Stack trace（PII 已過濾） |
| `http.method` | 視情況 | HTTP 方法 |
| `http.status_code` | 視情況 | HTTP 狀態碼 |
| `http.url` | 視情況 | 請求 URL（參數已遮罩） |
| `duration_ms` | 視情況 | 處理時間（毫秒） |

#### 5.2.3 日誌保留策略 (Log Retention Policy)

| 環境 | 保留時間 | 儲存位置 |
|---|---|---|
| Production | Hot: 30 天, Warm: 90 天, Cold: 1 年 | Loki + S3 archival |
| Staging | 14 天 | Loki |
| Development | 3 天 | Local / stdout |

稽核日誌 (Audit Logs) 保留 7 年（符合醫療法規要求）。

#### 5.2.4 PII 遮罩 (PII Masking in Logs)

```python
# app/logging/pii_filter.py

import re
from typing import Any

PII_PATTERNS = {
    "taiwan_id": r"[A-Z][12]\d{8}",                      # 身分證字號
    "phone": r"09\d{8}",                                  # 手機號碼
    "email": r"[\w.-]+@[\w.-]+\.\w+",                     # Email
    "credit_card": r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}",
    "name_chinese": None,  # 透過 NER 模型處理
}

MASK_FIELDS = [
    "patient_name", "patient_id_number", "phone_number",
    "email", "address", "date_of_birth", "medical_record_number",
]

def mask_pii(log_record: dict[str, Any]) -> dict[str, Any]:
    """遮罩日誌記錄中的 PII 資料。"""
    masked = log_record.copy()
    for field in MASK_FIELDS:
        if field in masked:
            masked[field] = "***REDACTED***"
    if "message" in masked:
        for pattern_name, pattern in PII_PATTERNS.items():
            if pattern:
                masked["message"] = re.sub(pattern, f"[{pattern_name}:REDACTED]", masked["message"])
    return masked
```

### 5.3 分散式追蹤 (Distributed Tracing)

#### 5.3.1 追蹤傳播 (Trace Propagation)

使用 OpenTelemetry SDK 搭配 W3C TraceContext 標準，實現跨服務追蹤傳播：

```python
# app/tracing/setup.py

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor

def setup_tracing(service_name: str, environment: str) -> None:
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("APP_VERSION", "unknown"),
        "deployment.environment": environment,
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint="http://jaeger-collector:4317")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument frameworks
    FastAPIInstrumentor.instrument()
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
    CeleryInstrumentor().instrument()
```

#### 5.3.2 關鍵 Span 定義 -- STT -> LLM -> TTS Pipeline

```
Trace: consultation_turn (1 round of conversation)
  |
  +-- Span: audio_receive (WebSocket binary frame reception)
  |     Duration: ~50ms
  |     Attributes: audio_size_bytes, audio_format, sample_rate
  |
  +-- Span: stt_processing (Google Cloud STT)
  |     Duration: ~500ms - 3s
  |     Attributes: language_code, audio_duration_ms, confidence_score
  |     |
  |     +-- Span: stt_api_call (actual gRPC call)
  |     +-- Span: transcript_post_processing
  |
  +-- Span: llm_processing (Claude API)
  |     Duration: ~1s - 10s
  |     Attributes: model, input_tokens, output_tokens, task_type
  |     |
  |     +-- Span: prompt_construction
  |     +-- Span: claude_api_call (HTTP request to Anthropic)
  |     +-- Span: response_parsing
  |     +-- Span: red_flag_evaluation
  |
  +-- Span: tts_processing (Google Cloud TTS)
  |     Duration: ~200ms - 1s
  |     Attributes: voice_name, text_length, audio_format, speaking_rate
  |     |
  |     +-- Span: ssml_generation
  |     +-- Span: tts_api_call
  |     +-- Span: audio_encoding
  |
  +-- Span: audio_send (WebSocket binary frame transmission)
  |     Duration: ~50ms
  |     Attributes: audio_size_bytes
  |
  +-- Span: state_persistence (save turn to DB + cache)
        Duration: ~10ms
        Attributes: session_id, turn_number
```

### 5.4 告警規則 (Alerting Rules)

#### P1 -- 嚴重 (Critical) -- 立即回應，目標 15 分鐘內處理

```yaml
# prometheus/alerts/p1-critical.yml
groups:
  - name: p1_critical
    rules:
      - alert: RedFlagSystemDown
        expr: up{job="gu-api"} == 0
        for: 2m
        labels:
          severity: critical
          priority: P1
        annotations:
          summary: "Red Flag 系統服務中斷"
          description: "API 服務 {{ $labels.instance }} 已停機超過 2 分鐘。紅旗警示系統可能無法運作。"
          runbook_url: "https://wiki.internal/runbooks/api-down"

      - alert: DatabaseDown
        expr: pg_up == 0
        for: 1m
        labels:
          severity: critical
          priority: P1
        annotations:
          summary: "PostgreSQL 資料庫無法連線"
          description: "Primary 資料庫已中斷 {{ $value }} 分鐘。所有寫入操作受影響。"

      - alert: HighAPIErrorRate
        expr: |
          sum(rate(http_requests_total{status_code=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m])) > 0.05
        for: 3m
        labels:
          severity: critical
          priority: P1
        annotations:
          summary: "API 5xx 錯誤率超過 5%"
          description: "過去 5 分鐘的 5xx 錯誤率為 {{ $value | humanizePercentage }}。"

      - alert: RedFlagNotificationFailure
        expr: |
          rate(red_flag_notification_failures_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
          priority: P1
        annotations:
          summary: "Red Flag 通知發送失敗"
          description: "紅旗警示推播通知發送失敗，醫師可能無法收到緊急通知。"

      - alert: AllWebSocketGatewaysDown
        expr: |
          count(up{job="gu-ws-gateway"} == 1) == 0
        for: 1m
        labels:
          severity: critical
          priority: P1
        annotations:
          summary: "所有 WebSocket Gateway 均已停機"
```

#### P2 -- 警告 (Warning) -- 30 分鐘內回應

```yaml
# prometheus/alerts/p2-warning.yml
groups:
  - name: p2_warning
    rules:
      - alert: HighLLMLatency
        expr: |
          histogram_quantile(0.95, rate(llm_processing_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
          priority: P2
        annotations:
          summary: "Claude LLM P95 延遲超過 5 秒"
          description: "LLM 處理延遲 P95 = {{ $value | humanizeDuration }}。可能影響使用體驗。"

      - alert: HighSTTFailureRate
        expr: |
          rate(stt_failures_total[10m]) / rate(stt_requests_total[10m]) > 0.10
        for: 5m
        labels:
          severity: warning
          priority: P2
        annotations:
          summary: "STT 辨識失敗率超過 10%"
          description: "語音辨識失敗率 {{ $value | humanizePercentage }}。"

      - alert: DatabaseReplicationLag
        expr: pg_replication_lag_seconds > 30
        for: 5m
        labels:
          severity: warning
          priority: P2
        annotations:
          summary: "資料庫複寫延遲超過 30 秒"

      - alert: HighPgBouncerWaitingClients
        expr: pgbouncer_pools_client_waiting > 10
        for: 5m
        labels:
          severity: warning
          priority: P2
        annotations:
          summary: "PgBouncer 等待連線數過高"

      - alert: RedisHighMemoryUsage
        expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.85
        for: 5m
        labels:
          severity: warning
          priority: P2
        annotations:
          summary: "Redis 記憶體使用率超過 85%"
```

#### P3 -- 通知 (Info) -- 下一個工作日處理

```yaml
# prometheus/alerts/p3-info.yml
groups:
  - name: p3_info
    rules:
      - alert: CeleryQueueDepthGrowing
        expr: |
          celery_queue_length > 50
          and delta(celery_queue_length[15m]) > 20
        for: 15m
        labels:
          severity: info
          priority: P3
        annotations:
          summary: "Celery 任務佇列持續增長"
          description: "佇列深度 {{ $value }}，過去 15 分鐘增長 > 20。"

      - alert: DiskUsageHigh
        expr: |
          (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.20
        for: 30m
        labels:
          severity: info
          priority: P3
        annotations:
          summary: "磁碟使用率超過 80%"

      - alert: CertificateExpiringSoon
        expr: certmanager_certificate_expiration_timestamp_seconds - time() < 14*24*3600
        labels:
          severity: info
          priority: P3
        annotations:
          summary: "TLS 憑證將於 14 天內到期"

      - alert: HighAudioStorageGrowth
        expr: |
          predict_linear(s3_bucket_size_bytes{bucket="gu-audio"}[7d], 30*24*3600)
          > 500 * 1024 * 1024 * 1024
        labels:
          severity: info
          priority: P3
        annotations:
          summary: "音檔儲存預計 30 天後超過 500 GB"
```

### 5.5 Dashboards (Grafana)

#### 5.5.1 Operations Dashboard

面板配置：

| 面板名稱 | 視覺化類型 | 查詢 |
|---|---|---|
| API Request Rate | Time series | `sum(rate(http_requests_total[5m])) by (status_code)` |
| API Latency (P50/P95/P99) | Time series | `histogram_quantile(0.95, ...)` |
| Error Rate | Stat + threshold | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` |
| Active WebSocket Connections | Gauge | `sum(ws_active_connections)` |
| Pod Status | Table | `kube_pod_status_phase{namespace="gu-production"}` |
| CPU Usage by Pod | Time series | `rate(container_cpu_usage_seconds_total[5m])` |
| Memory Usage by Pod | Time series | `container_memory_working_set_bytes` |
| PgBouncer Pool Utilization | Bar gauge | `pgbouncer_pools_server_active / pgbouncer_pools_server_maxconn` |
| Redis Memory | Gauge | `redis_memory_used_bytes` |
| DB Replication Lag | Stat | `pg_replication_lag_seconds` |

#### 5.5.2 AI Pipeline Performance Dashboard

| 面板名稱 | 視覺化類型 | 說明 |
|---|---|---|
| End-to-End Pipeline Latency | Heatmap | STT + LLM + TTS 總延遲分佈 |
| STT Latency Distribution | Histogram | 語音辨識延遲分佈 |
| LLM Response Time by Task | Time series | 按任務類型分組的 LLM 延遲 |
| TTS Generation Time | Histogram | 語音合成延遲 |
| LLM Token Consumption | Bar chart | 每小時 token 消耗量 |
| STT Confidence Scores | Time series | 語音辨識信心度分佈 |
| Pipeline Error Breakdown | Pie chart | 各階段錯誤佔比 |
| Concurrent AI Processing | Gauge | 同時處理中的 AI pipeline 數量 |

#### 5.5.3 Business Metrics Dashboard

| 面板名稱 | 視覺化類型 | 說明 |
|---|---|---|
| Daily Active Sessions | Bar chart | 每日問診場次（按醫師分組） |
| Red Flags Triggered | Stat + table | 當日紅旗警示次數與清單 |
| Average Session Duration | Stat | 平均問診時長 |
| SOAP Reports Generated | Counter | 已產生的 SOAP 報告數 |
| SOAP Generation Avg Time | Stat | SOAP 報告平均產生時間 |
| Patient Completion Rate | Gauge | 完成問診的比率 |
| Peak Usage Hours | Heatmap | 依時段統計的使用熱度 |
| Storage Usage Trend | Time series | 音檔儲存成長趨勢 |
| Cost Estimation | Table | 預估 API 費用 (Claude + Google) |

### 5.6 健康檢查端點 (Health Check Endpoint)

```json
// GET /health
{
  "status": "healthy",
  "version": "1.2.3",
  "timestamp": "2026-04-10T14:30:00Z",
  "checks": {
    "database": {
      "status": "healthy",
      "latency_ms": 2
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 1
    },
    "claude_api": {
      "status": "healthy",
      "latency_ms": 150
    },
    "google_cloud_stt": {
      "status": "healthy",
      "latency_ms": 80
    },
    "google_cloud_tts": {
      "status": "healthy",
      "latency_ms": 60
    },
    "object_storage": {
      "status": "healthy",
      "latency_ms": 30
    }
  }
}
```

---

## 6. 安全架構

### 6.1 認證流程 (Authentication Flow -- JWT with RS256)

```
+-----------+                  +-----------+              +-----------+
|  Client   |                  |  API GW   |              |  Auth Svc |
+-----------+                  +-----------+              +-----------+
      |                              |                          |
      |  1. POST /auth/login         |                          |
      |  {email, password}           |                          |
      |----------------------------->|                          |
      |                              |  2. Forward              |
      |                              |------------------------->|
      |                              |                          |
      |                              |  3. Verify credentials   |
      |                              |     (bcrypt hash check)  |
      |                              |                          |
      |                              |  4. Generate tokens      |
      |                              |     - Access (15min)     |
      |                              |     - Refresh (7d)       |
      |                              |     Signed with RS256    |
      |                              |<-------------------------|
      |  5. Response                 |                          |
      |  {access_token, refresh_token, expires_in}              |
      |<-----------------------------|                          |
      |                              |                          |
      |  6. API Request              |                          |
      |  Authorization: Bearer <jwt> |                          |
      |----------------------------->|                          |
      |                              |  7. Verify JWT signature |
      |                              |     (RS256 public key)   |
      |                              |  8. Check blacklist      |
      |                              |     (Redis)              |
      |                              |  9. Extract claims       |
      |                              |                          |
      |  10. Response                |                          |
      |<-----------------------------|                          |
```

**JWT 結構：**

```json
{
  "header": {
    "alg": "RS256",
    "typ": "JWT",
    "kid": "key-2026-04"
  },
  "payload": {
    "sub": "user-uuid",
    "iss": "gu-voice-api",
    "aud": "gu-voice-client",
    "iat": 1712764800,
    "exp": 1712765700,
    "jti": "unique-token-id",
    "role": "doctor",
    "permissions": ["read:patients", "write:sessions", "read:reports"],
    "session_fingerprint": "device-hash"
  }
}
```

> **注意：** JWT payload 中不包含 `clinic_id`，角色僅限 `patient`、`doctor`、`admin` 三種（依 shared_types.md 定義）。

**Token 生命週期管理：**

| Token 類型 | 有效期 | 儲存位置 | 更新方式 |
|---|---|---|---|
| Access Token | 15 分鐘 | 記憶體 (Mobile), httpOnly cookie (Web) | 使用 Refresh Token |
| Refresh Token | 7 天 | Secure storage (Mobile), httpOnly cookie (Web) | 重新登入 |
| WebSocket Token | 與 Access Token 相同 | Query parameter (WSS 連線時) | 連線期間自動更新 |

**RSA Key 管理：**

- 使用 RSA-2048 密鑰對
- Private key 儲存於 Vault / KMS
- Public key 透過 JWKS endpoint 公開 (`/.well-known/jwks.json`)
- 每 90 天輪換一次密鑰，支援多 key 同時驗證（透過 `kid`）

### 6.2 授權 (Authorization -- RBAC with Row-Level Security)

#### 角色定義

> **依 shared_types.md 統一為 3 種角色：`patient`、`doctor`、`admin`。**

| 角色 | 權限 | 說明 |
|---|---|---|
| `admin` | 全部權限：管理使用者、系統設定、檢視所有資料 | 系統管理員 |
| `doctor` | 建立問診、檢視自己的病患、審閱 SOAP、管理紅旗規則 | 醫師 |
| `patient` | 進行問診、檢視自己的報告與紀錄 | 病患 |

#### PostgreSQL Row-Level Security (RLS)

```sql
-- 啟用 RLS
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE soap_reports ENABLE ROW LEVEL SECURITY;

-- Admin 可存取所有資料
CREATE POLICY admin_full_access ON patients
    FOR ALL
    TO admin_role
    USING (true);

CREATE POLICY admin_sessions_access ON sessions
    FOR ALL
    TO admin_role
    USING (true);

-- 醫師只能看到自己的問診記錄
CREATE POLICY doctor_sessions_policy ON sessions
    FOR ALL
    TO doctor_role
    USING (doctor_id = current_setting('app.current_user_id')::uuid);

-- 醫師可透過問診記錄檢視關聯病患資料
CREATE POLICY doctor_patients_policy ON patients
    FOR SELECT
    TO doctor_role
    USING (id IN (
        SELECT patient_id FROM sessions
        WHERE doctor_id = current_setting('app.current_user_id')::uuid
    ));

-- 病患只能看到自己的資料
CREATE POLICY patient_own_data_policy ON patients
    FOR SELECT
    TO patient_role
    USING (user_id = current_setting('app.current_user_id')::uuid);

-- 病患只能看到自己的問診紀錄
CREATE POLICY patient_sessions_policy ON sessions
    FOR SELECT
    TO patient_role
    USING (patient_id IN (
        SELECT id FROM patients
        WHERE user_id = current_setting('app.current_user_id')::uuid
    ));

-- 稽核日誌不可刪除
CREATE POLICY audit_no_delete ON audit_logs
    FOR DELETE
    TO PUBLIC
    USING (false);
```

### 6.3 加密 (Encryption)

#### 6.3.1 傳輸中加密 (In Transit)

- **外部通訊：** TLS 1.3 (ALB/Ingress 終結)
- **內部通訊：** mTLS via service mesh (Istio/Linkerd)
- **WebSocket：** WSS (TLS-encrypted WebSocket)
- **資料庫連線：** SSL mode = `verify-full`
- **Redis 連線：** TLS enabled

#### 6.3.2 靜態加密 (At Rest)

| 資料類型 | 加密方式 | 密鑰管理 |
|---|---|---|
| PostgreSQL 資料 | AES-256 (volume encryption) | Cloud KMS |
| S3/GCS 物件 | AES-256 (SSE-S3 / CMEK) | Cloud KMS |
| Redis 資料 | AES-256 (volume encryption) | Cloud KMS |
| EBS/PD Volumes | AES-256 | Cloud KMS |
| 備份檔案 | AES-256 | Cloud KMS |

#### 6.3.3 應用程式層級加密 (Application-Level Encryption for PII)

> **依 shared_types.md，PII 欄位使用 pgcrypto 進行欄位級加密，database_spec 中的表定義使用加密 BYTEA 欄位儲存 PII。**

```sql
-- 使用 pgcrypto 對 PII 欄位進行欄位級加密
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 加密儲存敏感欄位
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 明文欄位（非 PII）
    user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 加密欄位（PII）-- BYTEA 型別
    name_encrypted BYTEA NOT NULL,           -- pgp_sym_encrypt(name, key)
    id_number_encrypted BYTEA NOT NULL,      -- pgp_sym_encrypt(id_number, key)
    phone_encrypted BYTEA,                   -- pgp_sym_encrypt(phone, key)
    email_encrypted BYTEA,                   -- pgp_sym_encrypt(email, key)
    date_of_birth_encrypted BYTEA,           -- pgp_sym_encrypt(dob, key)
    address_encrypted BYTEA,                 -- pgp_sym_encrypt(address, key)

    -- 雜湊索引欄位（用於查詢）
    id_number_hash TEXT NOT NULL UNIQUE,      -- SHA-256 hash for lookup
    phone_hash TEXT UNIQUE                    -- SHA-256 hash for lookup
);

-- 加密寫入範例
INSERT INTO patients (name_encrypted, id_number_encrypted, id_number_hash)
VALUES (
    pgp_sym_encrypt('王小明', current_setting('app.encryption_key')),
    pgp_sym_encrypt('A123456789', current_setting('app.encryption_key')),
    encode(digest('A123456789', 'sha256'), 'hex')
);

-- 解密讀取範例
SELECT
    pgp_sym_decrypt(name_encrypted, current_setting('app.encryption_key')) AS name,
    pgp_sym_decrypt(id_number_encrypted, current_setting('app.encryption_key')) AS id_number
FROM patients
WHERE id_number_hash = encode(digest('A123456789', 'sha256'), 'hex');
```

### 6.4 API 安全

#### 6.4.1 Rate Limiting (依角色)

> **依 shared_types.md，角色僅有 `patient`、`doctor`、`admin` 三種。**

| 角色 | 全域限制 | 認證端點 | AI 端點 | 說明 |
|---|---|---|---|---|
| 未認證 | 30 req/min | 5 req/min | 不可用 | 防止暴力破解 |
| `patient` | 60 req/min | -- | 10 req/min | 一般使用 |
| `doctor` | 120 req/min | -- | 30 req/min | 較高限額 |
| `admin` | 500 req/min | -- | 60 req/min | 系統管理 |

實作方式：Redis sliding window counter + NGINX Ingress rate limiting annotation

```python
# app/middleware/rate_limit.py

from fastapi import Request
from redis.asyncio import Redis

async def rate_limit_middleware(request: Request, call_next):
    user_role = request.state.user.role if hasattr(request.state, "user") else "anonymous"
    client_ip = request.client.host
    key = f"rate_limit:{user_role}:{client_ip}"

    redis: Redis = request.app.state.redis
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)

    limits = {"anonymous": 30, "patient": 60, "doctor": 120, "admin": 500}
    limit = limits.get(user_role, 30)

    if current > limit:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
    return response
```

#### 6.4.2 Input Validation

- 所有 API 端點使用 Pydantic v2 models 進行嚴格型別驗證
- SQL injection 防護：使用 SQLAlchemy ORM (parameterized queries)
- XSS 防護：輸出時自動 HTML escape
- 檔案上傳驗證：MIME type check, 大小限制 (50MB), 病毒掃描

#### 6.4.3 CORS 設定

```python
# app/main.py

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.gu-voice.example.com",
        "https://admin.gu-voice.example.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"],
    max_age=600,
)
```

#### 6.4.4 CSRF 防護

- Web Dashboard：使用 Double Submit Cookie pattern
- Mobile App：不需 CSRF（使用 Bearer token，非 cookie-based auth）
- API：`SameSite=Strict` cookie attribute + `X-CSRF-Token` header

### 6.5 Secret 管理

**方案選擇：** HashiCorp Vault 或 Cloud-native KMS (AWS Secrets Manager / GCP Secret Manager)

| Secret 類型 | 儲存位置 | 輪換頻率 | 說明 |
|---|---|---|---|
| JWT RSA Private Key | Vault / KMS | 90 天 | Token 簽章密鑰 |
| Database Password | Vault / KMS | 30 天 | 自動輪換 |
| Anthropic API Key | Vault / KMS | 依需要 | Claude API 密鑰 |
| Google Service Account | Vault / KMS | 90 天 | STT/TTS 服務帳號 |
| PII Encryption Key | Vault / KMS | 年度 | 欄位加密密鑰 (支援 key versioning) |
| S3/GCS Credentials | Vault / KMS (or IAM role) | 90 天 | 物件儲存存取 |
| FCM Credentials | Vault / KMS | 依需要 | 推播通知 |

**Kubernetes 整合：**

- 使用 External Secrets Operator (ESO) 從 Vault/KMS 同步 secrets 至 K8s Secrets
- 或使用 Vault Agent Injector 直接注入 Pod

### 6.6 漏洞掃描

| 掃描類型 | 工具 | 頻率 | 觸發方式 |
|---|---|---|---|
| Container Image Scan | Trivy | 每次 build + 每週 | CI/CD + CronJob |
| Dependency Scan (Python) | Snyk / pip-audit | 每次 PR + 每週 | CI/CD + CronJob |
| Dependency Scan (Node.js) | Snyk / npm audit | 每次 PR + 每週 | CI/CD + CronJob |
| SAST (Static Analysis) | Bandit (Python), ESLint security plugin | 每次 PR | CI/CD |
| DAST (Dynamic Analysis) | OWASP ZAP | 每月 | 排程 |
| Infrastructure Scan | Checkov / tfsec | 每次 IaC 變更 | CI/CD |

### 6.7 滲透測試排程 (Penetration Testing Schedule)

| 測試類型 | 頻率 | 執行方 | 範圍 |
|---|---|---|---|
| 自動化 DAST | 每月 | 內部 (OWASP ZAP) | API endpoints, Web Dashboard |
| 內部滲透測試 | 每季 | 資安團隊 | 完整應用程式 + 基礎設施 |
| 外部滲透測試 | 每年 | 第三方資安公司 | 完整系統（含 social engineering） |
| Red team 演練 | 每年 | 第三方資安公司 | 完整攻擊模擬 |

---

## 7. 合規性設計

### 7.1 HIPAA 合規檢查清單 (Technical Safeguards)

雖然 HIPAA 為美國法規，本系統以 HIPAA 為最高標準設計，以確保未來若有海外業務需求時可直接合規。

| 控制項 | 要求 | 實作方式 | 狀態 |
|---|---|---|---|
| Access Control (164.312(a)) | 唯一使用者識別 | UUID-based user ID, JWT auth | 規劃中 |
| | 緊急存取程序 | Break-glass admin access with audit | 規劃中 |
| | 自動登出 | Token expiry (15min), session timeout | 規劃中 |
| | 加密與解密 | AES-256 at rest, TLS 1.3 in transit | 規劃中 |
| Audit Controls (164.312(b)) | 記錄所有存取活動 | Audit log table + immutable storage | 規劃中 |
| Integrity Controls (164.312(c)) | 資料完整性保護 | DB constraints, checksums, WAL | 規劃中 |
| Transmission Security (164.312(e)) | 加密傳輸 | TLS 1.3, mTLS, WSS | 規劃中 |
| Person Authentication (164.312(d)) | 身份驗證 | MFA support, RS256 JWT | 規劃中 |

### 7.2 台灣個人資料保護法 (PDPA) 考量

#### 7.2.1 適用條文與對應措施

| 條文 | 要求 | 實作方式 |
|---|---|---|
| 第 5 條 | 蒐集個資應遵守比例原則 | 僅蒐集問診必要資訊，定期審查欄位必要性 |
| 第 7 條 | 書面同意 | 電子同意書簽署流程，含明確告知事項 |
| 第 8 條 | 告知義務 | App 首次使用時明確告知蒐集目的、利用範圍 |
| 第 11 條 | 個資正確性維護 | 病患可修改個人資料、醫師可更正醫療紀錄 |
| 第 11 條第 3 項 | 個資刪除 | 資料刪除流程 (Right to Erasure) |
| 第 12 條 | 個資利用限制 | RBAC + RLS 限制存取範圍 |
| 第 18 條 | 安全維護措施 | 加密、存取控制、稽核日誌、定期資安評估 |
| 第 27 條 | 損害賠償 | 資安事件應變計畫 (Incident Response Plan) |

#### 7.2.2 醫療資料特殊考量

- 依據《醫療法》第 70 條，病歷保存期限至少 7 年
- 依據《個資法》第 6 條，醫療資料屬特種個資，需特別保護
- AI 生成的 SOAP 報告視為輔助文件，需由醫師確認後方具效力

### 7.3 資料駐留要求 (Data Residency)

| 資料類型 | 儲存地區 | 說明 |
|---|---|---|
| 病患個人資料 | 台灣 (asia-east1) | 不得跨境傳輸 |
| 問診錄音檔 | 台灣 (asia-east1) | 不得跨境傳輸 |
| SOAP 報告 | 台灣 (asia-east1) | 不得跨境傳輸 |
| 系統日誌 (含 PII) | 台灣 (asia-east1) | PII 已遮罩之日誌可複製至其他區域 |
| 匿名化統計資料 | 無限制 | 去識別化後的統計數據 |

**Claude API 資料處理注意事項：**

- 傳送至 Claude API 的資料經由 HTTPS 加密傳輸
- 確認 Anthropic API 不會將輸入資料用於模型訓練（需簽訂 DPA）
- 傳送前移除非必要 PII，僅傳送症狀描述與問診上下文
- 保留 API 呼叫紀錄但不記錄完整 prompt 內容

### 7.4 Business Associate Agreements (BAA)

| 供應商 | BAA 類型 | 涵蓋服務 | 狀態 |
|---|---|---|---|
| AWS / GCP | Cloud BAA | 運算、儲存、資料庫 | 待簽署 |
| Anthropic | Data Processing Agreement | Claude API | 待簽署 |
| Google Cloud | Data Processing Agreement | STT, TTS | 待簽署 |
| Firebase (Google) | Data Processing Agreement | FCM | 待簽署 |
| Cloudflare | Data Processing Agreement | CDN, DNS | 待簽署 |

### 7.5 病患同意書管理 (Patient Consent Management)

```
+------------------+     +-----------------+     +------------------+
| 病患首次使用 App  | --> | 顯示同意書      | --> | 記錄同意狀態      |
|                  |     |                 |     |                  |
| - 下載/安裝       |     | - 資料蒐集告知   |     | - audit_logs     |
| - 註冊帳號       |     | - AI 使用告知    |     |   table 記錄     |
|                  |     | - 錄音告知       |     | - 版本化管理     |
|                  |     | - 隱私權政策     |     | - 不可刪除       |
+------------------+     +-----------------+     +------------------+
```

> **注意：** `consent_records` 資料表不在目前 MVP 範圍內。MVP 階段的同意紀錄透過 `audit_logs` 記錄。若未來需要更精細的同意書版本控制與撤回管理，將在後續階段新增獨立的 `consent_records` 資料表。

### 7.6 資料刪除流程 (Right to Deletion / Data Erasure)

```
病患提出刪除請求
        |
        v
+------------------+
| 驗證身份         |  <-- 雙因素驗證
+------------------+
        |
        v
+------------------+
| 記錄刪除請求     |  <-- audit_log (不可刪除)
+------------------+
        |
        v
+------------------+
| 等待冷靜期       |  <-- 7 天冷靜期，可撤回
+------------------+
        |
        v
+------------------+       +------------------+
| 法規保留檢查     | ----> | 標記法規保留資料  |
| (病歷 7 年)      |  yes  | (不刪除，僅去識別) |
+------------------+       +------------------+
        | no
        v
+------------------+
| 執行資料刪除     |
| 1. PII 欄位清除  |
| 2. 音檔刪除      |
| 3. Cache 清除    |
| 4. 搜尋索引移除  |
| 5. 備份標記      |
+------------------+
        |
        v
+------------------+
| 確認刪除完成     |  <-- 寄送確認通知給病患
+------------------+
```

### 7.7 稽核追蹤要求 (Audit Trail Requirements)

```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type VARCHAR(50) NOT NULL,           -- 'LOGIN', 'DATA_ACCESS', 'DATA_MODIFY', 'DATA_DELETE'
    actor_id UUID,                              -- 操作者 ID
    actor_role VARCHAR(30),                     -- 操作者角色 (patient/doctor/admin)
    actor_ip INET,                              -- 操作者 IP
    resource_type VARCHAR(50) NOT NULL,         -- 'patient', 'session', 'soap_report'
    resource_id UUID,                           -- 被操作資源 ID
    action VARCHAR(30) NOT NULL,                -- 'CREATE', 'READ', 'UPDATE', 'DELETE'
    changes JSONB,                              -- 變更前後值（PII 已遮罩）
    request_id VARCHAR(64),                     -- 關聯請求 ID
    user_agent TEXT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    failure_reason TEXT
);

-- 分區策略：按月分區
CREATE TABLE audit_logs_2026_04 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- 防止刪除
REVOKE DELETE ON audit_logs FROM PUBLIC;

-- 稽核日誌保留 7 年
-- 透過 pg_partman 自動管理分區生命週期
```

稽核事件類型：

| 事件類型 | 觸發條件 | 記錄內容 |
|---|---|---|
| `AUTH_LOGIN` | 使用者登入成功 | user_id, ip, user_agent |
| `AUTH_LOGIN_FAILED` | 登入失敗 | email_hash, ip, failure_reason |
| `AUTH_LOGOUT` | 使用者登出 | user_id |
| `AUTH_TOKEN_REFRESH` | Token 更新 | user_id |
| `DATA_ACCESS` | 讀取病患資料 | accessor_id, patient_id |
| `DATA_MODIFY` | 修改病患資料 | actor_id, changes (diff) |
| `DATA_DELETE` | 刪除資料 | actor_id, resource details |
| `SESSION_START` | 問診開始 | doctor_id, patient_id |
| `SESSION_END` | 問診結束 | session_id, duration |
| `RED_FLAG_TRIGGERED` | 紅旗警示 | session_id, flag_type, severity |
| `SOAP_GENERATED` | SOAP 報告產生 | session_id, report_id |
| `SOAP_REVIEWED` | 醫師審閱 SOAP | doctor_id, report_id, approval_status |
| `EXPORT_DATA` | 資料匯出 | actor_id, export_type, record_count |
| `ADMIN_ACTION` | 管理操作 | admin_id, action_detail |

### 7.8 AI 免責聲明要求 (AI Disclaimer Requirements)

系統必須在以下環節明確告知 AI 使用情境：

1. **病患端 (Patient-facing):**
   - App 首次使用：「本系統使用人工智慧技術協助問診，AI 產生之內容僅供參考，不構成醫療診斷或建議。最終醫療決定由您的主治醫師做出。」
   - 每次問診開始：語音提示 AI 輔助性質
   - 問診報告頁尾：AI 產生內容標記

2. **醫師端 (Doctor-facing):**
   - SOAP 報告頁首：「本報告由 AI 系統輔助產生，請醫師審閱並確認內容正確性後方可作為醫療紀錄。」
   - Red flag 通知：「此為 AI 系統偵測之潛在緊急狀況，請醫師依臨床判斷決定處置方式。」

3. **法律文件:**
   - 使用條款中明確載明 AI 技術使用範圍與限制
   - 隱私權政策中說明 AI 處理資料的方式

---

## 8. 災難復原計畫

### 8.1 復原目標

| 指標 | 目標值 | 說明 |
|---|---|---|
| RTO (Recovery Time Objective) | 1 小時 | 從災難發生到服務恢復的最大容許時間 |
| RPO (Recovery Point Objective) | 近零 (streaming replica failover) / 5 分鐘 (S3 WAL archive recovery) | 依故障類型不同 |
| MTTR (Mean Time to Recovery) | 30 分鐘 | 平均復原時間目標 |

**RPO 說明：**

- **Streaming replica failover（主要場景）：** 透過 WAL streaming 同步複寫至 Read Replica，failover 時 RPO 趨近零。
- **S3 WAL archive recovery（災難場景）：** WAL archive 每 5 分鐘上傳至 S3，從 S3 復原時 RPO 最多 5 分鐘。

### 8.2 備份策略

#### 8.2.1 資料庫備份 (PostgreSQL)

```
+------------------+     +------------------+     +------------------+
| PostgreSQL       | --> | WAL Archiving    | --> | S3/GCS           |
| Primary          |     | (Continuous)     |     | (WAL Archive)    |
|                  |     |                  |     |                  |
| WAL Streaming ---|---> | Read Replica     |     | Base Backup      |
| (Sync/Async)    |     | (Standby)        |     | (Daily, 02:00)   |
+------------------+     +------------------+     +------------------+
```

| 備份類型 | 頻率 | 保留期間 | 工具 | 儲存位置 |
|---|---|---|---|---|
| Continuous WAL Archiving | 持續 (每 5 分鐘 / 每 WAL segment) | 30 天 | pgBackRest / WAL-G | S3/GCS (跨區域) |
| Base Backup (Full) | 每日 02:00 UTC (離峰) | 30 天 | pgBackRest | S3/GCS |
| Weekly Full Backup | 每週日 02:00 UTC | 1 年 | pgBackRest | S3/GCS (跨區域) |
| Monthly Archive | 每月 1 日 | 7 年 | pgBackRest | S3 Glacier / GCS Coldline |

**pgBackRest 設定範例：**

```ini
[gu-voice-db]
pg1-path=/var/lib/postgresql/15/main

[global]
repo1-type=s3
repo1-s3-bucket=gu-voice-db-backups
repo1-s3-region=ap-northeast-1
repo1-s3-endpoint=s3.ap-northeast-1.amazonaws.com
repo1-path=/backups
repo1-retention-full=4
repo1-retention-diff=7
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=ENCRYPTED_PASSPHRASE

repo2-type=s3
repo2-s3-bucket=gu-voice-db-backups-dr
repo2-s3-region=ap-southeast-1
repo2-path=/backups-dr
repo2-retention-full=4
```

**PITR (Point-in-Time Recovery) 測試：**

```bash
# 還原至特定時間點
pgbackrest restore \
  --stanza=gu-voice-db \
  --type=time \
  --target="2026-04-10 14:30:00+08" \
  --target-action=promote \
  --set=20260410-020000F
```

#### 8.2.2 Redis 備份

| 備份類型 | 頻率 | 設定 |
|---|---|---|
| RDB Snapshot | 每 15 分鐘 | `save 900 1` / `save 300 100` / `save 60 10000` |
| AOF (Append Only File) | 持續 (每秒 fsync) | `appendonly yes`, `appendfsync everysec` |
| RDB to S3 | 每小時 | CronJob 上傳 RDB 至 S3 |

**Redis 資料復原優先順序：**

1. 從 AOF 檔案復原（最新資料）
2. 從 RDB snapshot 復原
3. 從 S3 備份復原
4. 冷啟動（cache miss 可由應用程式自動重建）

#### 8.2.3 物件儲存備份 (S3/GCS)

| 策略 | 設定 | 說明 |
|---|---|---|
| Cross-Region Replication | asia-east1 -> asia-northeast1 | 自動跨區域複寫 |
| Versioning | 啟用 | 支援意外刪除復原 |
| Object Lock | 啟用 (Compliance mode) | SOAP 報告不可刪除 (7 年) |
| Lifecycle Rules | 音訊保留 3 年 (1095 天, `AUDIO_RETENTION_DAYS`) | 依 shared_types.md 定義 |

> **音訊保留期限：** 依 shared_types.md section 7.8，`AUDIO_RETENTION_DAYS` 預設值為 `1095`（3 年 / 1095 天），到期後安全銷毀。

#### 8.2.4 組態備份 (Configuration)

| 項目 | 備份方式 | 說明 |
|---|---|---|
| Terraform State | S3 backend + state locking (DynamoDB) | 版本控制 + 鎖定 |
| K8s Manifests | Git repository | 所有 YAML 版控 |
| Helm Values | Git repository | 環境設定版控 |
| Vault Config | Vault snapshot + S3 | 定期快照 |

### 8.3 故障轉移程序 (Failover Procedures)

#### 8.3.1 資料庫故障轉移 (Database Failover)

```
正常狀態:
  Primary (AZ-A) <--WAL Streaming--> Read Replica (AZ-B)
                                          |
故障偵測:                                 |
  Patroni / RDS Multi-AZ                 |
  自動偵測 Primary 故障                    |
  (Health check 失敗 3 次, ~30 秒)        |
                                          |
自動故障轉移:                              |
  1. Read Replica promote to Primary      v
  2. PgBouncer 更新後端指向    <---- New Primary (AZ-B)
  3. DNS 更新 (如使用 managed DB)
  4. 應用程式自動重連
  5. 告警通知 On-call 工程師

預估故障轉移時間: 30 秒 - 2 分鐘
```

手動故障轉移步驟：

```bash
# 1. 確認 Primary 確實無法恢復
pg_isready -h primary-host -p 5432

# 2. 提升 Read Replica
# 使用 Patroni
patronictl failover gu-voice-cluster --candidate replica-1

# 或使用原生 PostgreSQL
psql -h replica-host -c "SELECT pg_promote();"

# 3. 更新 PgBouncer 設定
# 修改 pgbouncer.ini 中的 host 指向新 Primary
pgbouncer -R  # reload config

# 4. 驗證
psql -h pgbouncer-host -p 6432 -c "SELECT pg_is_in_recovery();"
# 預期結果: false (表示已是 Primary)
```

#### 8.3.2 應用程式故障轉移 (Application Failover)

```
Multi-AZ Deployment:

AZ-A:                          AZ-B:
+----------+                   +----------+
| API Pod  |                   | API Pod  |
| API Pod  |                   | API Pod  |
| WS Pod   |                   | WS Pod   |
| Worker   |                   | Worker   |
+----------+                   +----------+
      |                              |
      +--------- ALB/NLB -----------+
                   |
              Health Check
              (每 10 秒)
```

- Kubernetes 自動排程 Pod 至健康的 Node
- Pod Anti-affinity 確保同一 Deployment 的 Pod 分散至不同 AZ
- HPA 自動增加 replica 以彌補失效的 Pod
- PodDisruptionBudget 確保維護時至少 N-1 個 Pod 運行

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: gu-api-pdb
  namespace: gu-production
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: gu-api
```

#### 8.3.3 DNS 故障轉移

使用 Cloudflare 或 Route53 Health Check + Failover routing：

```
Primary Region (asia-east1)
    |
    +-- Health Check: https://api.gu-voice.example.com/health
    |   Interval: 30s, Threshold: 3 failures
    |
    +-- [Healthy] --> Route traffic here
    |
    +-- [Unhealthy] --> Failover to DR Region
                            |
                            v
                DR Region (asia-northeast1)
                    |
                    +-- Read-only mode (限制功能)
                    +-- 通知團隊啟動完整 DR 程序
```

### 8.4 災難復原演練排程 (DR Drills Schedule)

| 演練類型 | 頻率 | 範圍 | 預計時間 |
|---|---|---|---|
| Database Failover Drill | 每季 | 模擬 Primary 故障，驗證自動切換 | 2 小時 |
| Full DR Drill | 每半年 | 模擬完整 AZ 故障，切換至 DR region | 4 小時 |
| Backup Restore Test | 每月 | 從備份還原資料庫並驗證資料完整性 | 2 小時 |
| Chaos Engineering | 每月 | 隨機注入故障 (pod kill, network partition) | 持續 |
| Tabletop Exercise | 每季 | 桌面推演各種災難場景 | 2 小時 |

每次演練後必須記錄：

1. 演練日期與參與人員
2. 場景描述
3. 實際 RTO/RPO 與目標對比
4. 發現的問題
5. 改進行動項目

---

## 9. 擴展性規劃

### 9.1 容量目標

| 指標 | 初期目標 (Phase 1) | 成長目標 (Phase 2) | 大規模 (Phase 3) |
|---|---|---|---|
| 醫師數量 | 20 | 100 | 500 |
| 每日病患數 | 200 | 1,000 | 5,000 |
| 同時問診數 | 50 | 200 | 1,000 |
| API RPS (peak) | 100 | 500 | 2,500 |
| WebSocket 連線數 | 50 | 200 | 1,000 |
| 每日音檔量 | ~10 GB | ~50 GB | ~250 GB |
| 資料庫大小 (年) | ~50 GB | ~250 GB | ~1.2 TB |

### 9.2 瓶頸分析

#### 9.2.1 LLM API Rate Limits 與排隊機制

**瓶頸描述：** Claude API 有 rate limit (RPM/TPM)，50 個同時問診可能超過限制。

**解決方案：**

```
+------------------+     +------------------+     +------------------+
| WebSocket        | --> | LLM Request      | --> | Claude API       |
| Gateway          |     | Queue (Redis)    |     | (Rate Limited)   |
|                  |     |                  |     |                  |
| 50 concurrent    |     | Priority Queue:  |     | Tier 1: 60 RPM   |
| sessions         |     | - P1: Red Flag   |     | Tier 2: 300 RPM  |
|                  |     | - P2: Dialogue   |     | Tier 3: 1000 RPM |
|                  |     | - P3: SOAP Gen   |     |                  |
+------------------+     +------------------+     +------------------+
```

```python
# app/services/llm_queue.py

class LLMRequestQueue:
    PRIORITY_RED_FLAG = 1      # 紅旗檢測 -- 最高優先
    PRIORITY_DIALOGUE = 2      # 即時對話
    PRIORITY_SOAP = 3          # SOAP 報告產生 (可延後)
    PRIORITY_ANALYTICS = 4     # 統計分析 (最低)

    def __init__(self, redis: Redis, rate_limit_rpm: int = 60):
        self.redis = redis
        self.rate_limit = rate_limit_rpm
        self.semaphore = asyncio.Semaphore(rate_limit_rpm)

    async def enqueue(self, request: LLMRequest, priority: int) -> str:
        """將 LLM 請求加入優先佇列。"""
        task_id = str(uuid4())
        await self.redis.zadd(
            "llm_queue",
            {json.dumps({"task_id": task_id, "request": request.dict()}): priority}
        )
        return task_id

    async def process_queue(self):
        """依優先順序處理佇列中的請求。"""
        while True:
            # 取出最高優先的請求
            items = await self.redis.zpopmin("llm_queue", count=1)
            if not items:
                await asyncio.sleep(0.1)
                continue

            async with self.semaphore:
                await self._call_claude_api(items[0])
                # Rate limit: 確保不超過 RPM
                await asyncio.sleep(60 / self.rate_limit)
```

成長策略：

- Phase 1: Anthropic Tier 1 (60 RPM) -- 使用佇列控制
- Phase 2: 申請 Tier 2 (300 RPM) + 多 API key 輪替
- Phase 3: Tier 3 (1000 RPM) + 請求批次處理

#### 9.2.2 WebSocket 連線限制

**瓶頸描述：** 單一 Pod 的 WebSocket 連線數受限於記憶體與檔案描述符。

**解決方案：**

| 面向 | Phase 1 (50 conn) | Phase 2 (200 conn) | Phase 3 (1000 conn) |
|---|---|---|---|
| Pod 數量 | 2 | 4 | 8+ |
| 每 Pod 上限 | 50 | 100 | 200 |
| Session Affinity | ClientIP | ClientIP + Redis pub/sub | Redis pub/sub + 獨立 state store |
| 記憶體/Pod | 512MB | 1GB | 2GB |

跨 Pod 訊息分發 (Redis Pub/Sub)：

```python
# 當 WebSocket 需要跨 Pod 通訊時
# 例：醫師在 Pod-A，但 Red Flag 在 Pod-B 偵測到

async def publish_red_flag(session_id: str, flag_data: dict):
    channel = f"red_flag:{session_id}"
    await redis.publish(channel, json.dumps(flag_data))

async def subscribe_red_flag(doctor_id: str):
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"doctor_alerts:{doctor_id}")
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield json.loads(message["data"])
```

#### 9.2.3 資料庫連線池 (PgBouncer 設定)

```ini
; pgbouncer.ini

[databases]
gu_voice_db = host=postgres-primary port=5432 dbname=gu_voice_db
gu_voice_db_readonly = host=postgres-replica port=5432 dbname=gu_voice_db

[pgbouncer]
; Phase 1 設定
pool_mode = transaction
max_client_conn = 200
default_pool_size = 25
min_pool_size = 5
reserve_pool_size = 5
reserve_pool_timeout = 3

; Phase 2 設定 (成長期)
; max_client_conn = 500
; default_pool_size = 50
; min_pool_size = 10

; Phase 3 設定 (大規模)
; max_client_conn = 1000
; default_pool_size = 100
; min_pool_size = 20

; 連線生命週期
server_lifetime = 3600
server_idle_timeout = 600
client_idle_timeout = 300

; 查詢限制
query_timeout = 30
query_wait_timeout = 120

; 日誌
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
stats_period = 60
```

#### 9.2.4 Redis 連線池建議

| 階段 | `REDIS_MAX_CONNECTIONS` | 說明 |
|---|---|---|
| Phase 1 | 50 | 初期負載 |
| Phase 2 | 100+ | 成長期，WebSocket pub/sub + 快取 + Celery broker |
| Phase 3 | 200+ | 大規模，建議使用 Redis Cluster |

#### 9.2.5 音檔儲存成長預估

假設：每次問診平均 10 分鐘錄音，16kHz mono LINEAR16 格式

| 階段 | 每日問診數 | 每日新增 | 每月累積 | 每年累積 |
|---|---|---|---|---|
| Phase 1 | 200 | ~10 GB | ~300 GB | ~3.6 TB |
| Phase 2 | 1,000 | ~50 GB | ~1.5 TB | ~18 TB |
| Phase 3 | 5,000 | ~250 GB | ~7.5 TB | ~90 TB |

儲存成本最佳化策略：

1. 音訊保留 3 年（`AUDIO_RETENTION_DAYS=1095`），超過後安全銷毀
2. 保留壓縮版本 (Opus/AAC) 供回放，原始檔僅供法律用途
3. 每年審查保留政策，超過法定保留期限的檔案進行安全銷毀

### 9.3 水平擴展策略 (Horizontal Scaling)

```
                     目前架構 (Phase 1)
                     
API: 3 pods -----> HPA trigger (CPU>70% or RPS>100) -----> Max 10 pods
WS:  2 pods -----> HPA trigger (connections>200/pod) ----> Max 6 pods
Worker: 2 pods --> HPA trigger (queue>10/worker) ---------> Max 8 pods

                     成長架構 (Phase 2)
                     
API: 5 pods -----> HPA + VPA -----> Max 20 pods
WS:  4 pods -----> 按連線數 ------> Max 12 pods
Worker: 4 pods --> 按佇列深度 -----> Max 16 pods
DB: 1 Primary + 2 Read Replicas
Redis: 3-node cluster -> 6-node cluster
```

可水平擴展的元件：

| 元件 | 擴展方式 | 瓶頸點 | 擴展限制 |
|---|---|---|---|
| API Server | 增加 Pod replica | 無狀態，自由擴展 | DB connection pool |
| WS Gateway | 增加 Pod replica | Session affinity 需 Redis | Redis pub/sub throughput |
| Background Worker | 增加 Pod replica | 無狀態，自由擴展 | LLM API rate limit |
| PgBouncer | 增加實例 | 無狀態 | DB max_connections |
| Redis | 增加 cluster node | 自動 resharding | 記憶體成本 |

不可水平擴展的元件（需垂直擴展）：

| 元件 | 擴展方式 | 觸發閾值 |
|---|---|---|
| PostgreSQL Primary | 升級 instance type | CPU>70%, IOPS 飽和 |
| PostgreSQL (儲存) | 增加磁碟大小 | 使用率 >70% |

### 9.4 垂直擴展閾值 (Vertical Scaling Thresholds)

| 元件 | 初始規格 | 觸發升級的條件 | 升級至 |
|---|---|---|---|
| PostgreSQL Primary | db.r6g.large (2 vCPU, 16GB) | CPU >70% 持續 1 小時 | db.r6g.xlarge (4 vCPU, 32GB) |
| PostgreSQL Primary | db.r6g.xlarge | 連線數 >500, IOPS >10K | db.r6g.2xlarge (8 vCPU, 64GB) |
| Redis | cache.r6g.large (2 vCPU, 13GB) | Memory >85%, CPU >60% | cache.r6g.xlarge |
| K8s Worker Node | m6i.xlarge (4 vCPU, 16GB) | Pod scheduling 失敗 | m6i.2xlarge 或增加 node |

---

## 10. 開發環境設定

### 10.1 本地開發環境搭建 (Docker Compose)

**系統需求：**

| 項目 | 最低需求 | 建議配置 |
|---|---|---|
| Docker Desktop | v24+ | 最新穩定版 |
| Docker Compose | v2.20+ | 最新穩定版 |
| Docker Memory | 4 GB | 8 GB |
| Python | 3.12+ | 3.12.x |
| Node.js | 20 LTS | 20.x LTS |
| 磁碟空間 | 10 GB | 20 GB |

**初始化步驟：**

```bash
# 1. Clone repository
git clone git@github.com:org/gu-voice-assistant.git
cd gu-voice-assistant

# 2. 複製環境設定
cp .env.example .env.development

# 3. 啟動基礎服務 (DB, Redis, Mock services)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis mock-llm mock-stt mock-tts

# 4. 等待服務就緒
docker compose exec postgres pg_isready -U gu_user -d gu_voice_db

# 5. 建立 Python 虛擬環境
python -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt

# 6. 執行資料庫遷移
alembic upgrade head

# 7. 載入測試資料
python scripts/seed_data.py

# 8. 啟動 API server (hot reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 9. (另一個終端) 啟動 WebSocket gateway
uvicorn app.ws_gateway:app --host 0.0.0.0 --port 8001 --reload

# 10. (另一個終端) 啟動 Celery worker
celery -A app.worker.app worker --loglevel=debug --concurrency=2

# 11. (可選) 啟動 Web Dashboard
cd web && npm install && npm start
```

或使用一鍵啟動：

```bash
make dev-up    # 啟動所有服務
make dev-down  # 停止所有服務
make dev-reset # 重置資料庫與快取
make dev-logs  # 查看即時日誌
```

### 10.2 環境變數管理 (.env files)

```
.env.example          <-- 模板，提交至版控（不含實際值）
.env.development      <-- 本地開發（.gitignore 忽略）
.env.test             <-- 測試環境（CI/CD 使用）
.env.staging          <-- Staging 環境（透過 Secret Manager）
.env.production       <-- Production 環境（透過 Secret Manager）
```

**.env.example 內容：**

```bash
# ---- Application ----
APP_ENV=development
DEBUG=true
APP_PORT=8000
APP_HOST=0.0.0.0
APP_LOG_LEVEL=DEBUG
APP_VERSION=local
APP_WORKERS=1

# ---- Database ----
DATABASE_URL=postgresql://gu_user:gu_password@localhost:5432/gu_voice_db
PGBOUNCER_URL=postgresql://gu_user:gu_password@localhost:6432/gu_voice_db
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_ECHO=false

# ---- Redis ----
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
REDIS_TTL_DEFAULT=1800

# ---- Auth ----
JWT_ALGORITHM=RS256
JWT_PRIVATE_KEY_PATH=./keys/dev-private.pem
JWT_PUBLIC_KEY_PATH=./keys/dev-public.pem
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ---- Claude API ----
ANTHROPIC_API_KEY=sk-ant-dev-xxxx
CLAUDE_MODEL_CONVERSATION=claude-sonnet-4-20250514
CLAUDE_MODEL_SOAP=claude-sonnet-4-20250514
CLAUDE_MODEL_RED_FLAG=claude-haiku-4-5-20251001
CLAUDE_TEMPERATURE_CONVERSATION=0.7
CLAUDE_TEMPERATURE_SOAP=0.3
CLAUDE_TEMPERATURE_RED_FLAG=0.2
CLAUDE_MAX_TOKENS_CONVERSATION=512
CLAUDE_MAX_TOKENS_SOAP=4096

# ---- Google STT ----
GOOGLE_APPLICATION_CREDENTIALS=./keys/google-service-account.json
GOOGLE_CLOUD_PROJECT_ID=gu-voice-dev
GOOGLE_STT_LANGUAGE_CODE=zh-TW
GOOGLE_STT_MODEL=chirp_2
GOOGLE_STT_SAMPLE_RATE=16000

# ---- Google TTS ----
GOOGLE_TTS_VOICE_NAME=cmn-TW-Wavenet-A
GOOGLE_TTS_SPEAKING_RATE=0.9
GOOGLE_TTS_PITCH=0.0
GOOGLE_TTS_SAMPLE_RATE=24000
GOOGLE_TTS_AUDIO_ENCODING=MP3

# ---- Object Storage ----
S3_BUCKET=gu-voice-dev-audio
S3_REGION=ap-northeast-1
AWS_ACCESS_KEY_ID=dev-access-key
AWS_SECRET_ACCESS_KEY=dev-secret-key
S3_ENDPOINT_URL=http://localhost:9000  # MinIO for local dev
AUDIO_RETENTION_DAYS=1095

# ---- Firebase Cloud Messaging ----
FCM_CREDENTIALS_PATH=./keys/firebase-service-account.json
FCM_PROJECT_ID=gu-voice-dev

# ---- Monitoring ----
SENTRY_DSN=
PROMETHEUS_PORT=9090
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=gu-api

# ---- CORS ----
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# ---- Mock Services (dev only) ----
USE_MOCK_LLM=true
USE_MOCK_STT=true
USE_MOCK_TTS=true
MOCK_LLM_URL=http://localhost:9100
MOCK_STT_URL=http://localhost:9101
MOCK_TTS_URL=http://localhost:9102

# ---- PII Encryption ----
ENCRYPTION_KEY=dev-encryption-key-32-chars-long!
```

### 10.3 資料庫初始化與測試資料 (Database Seeding)

```python
# scripts/seed_data.py

"""
開發環境測試資料初始化腳本。
執行方式: python scripts/seed_data.py
"""

import asyncio
from app.database import get_session
from app.models import User, Patient, Session as ConsultationSession

async def seed():
    async with get_session() as session:
        # ---- 建立測試管理員 ----
        admin = User(
            name="系統管理員",
            email="admin@test.com",
            role="admin",
        )
        admin.set_password("Test1234!")
        session.add(admin)
        await session.flush()

        # ---- 建立測試醫師 (5 位) ----
        doctors = []
        doctor_data = [
            {"name": "張醫師", "email": "dr.chang@test.com", "department": "一般泌尿科"},
            {"name": "李醫師", "email": "dr.lee@test.com", "department": "泌尿腫瘤"},
            {"name": "王醫師", "email": "dr.wang@test.com", "department": "小兒泌尿"},
            {"name": "陳醫師", "email": "dr.chen@test.com", "department": "婦女泌尿"},
            {"name": "林醫師", "email": "dr.lin@test.com", "department": "男性學"},
        ]
        for d in doctor_data:
            doctor = User(role="doctor", **d)
            doctor.set_password("Test1234!")  # bcrypt hashed
            session.add(doctor)
            doctors.append(doctor)
        await session.flush()

        # ---- 建立測試病患 (20 位) ----
        patients = []
        for i in range(20):
            user = User(
                name=f"測試病患{i+1}",
                email=f"patient{i+1}@test.com",
                role="patient",
            )
            user.set_password("Test1234!")
            session.add(user)
            await session.flush()

            patient = Patient(
                user_id=user.id,
                name_encrypted=encrypt(f"測試病患{i+1}"),
                phone_encrypted=encrypt(f"09{10000000+i}"),
                id_number_hash=hash_id(f"A{100000000+i}"),
                date_of_birth_encrypted=encrypt("1980-01-01"),
                gender="male" if i % 2 == 0 else "female",
                medical_record_number=f"MRN{100000+i}",
            )
            session.add(patient)
            patients.append(patient)
        await session.flush()

        # ---- 建立範例問診紀錄 ----
        sample_session = ConsultationSession(
            doctor_id=doctors[0].id,
            patient_id=patients[0].id,
            status="completed",
            chief_complaint_text="頻尿、夜尿",
            duration_seconds=600,
        )
        session.add(sample_session)

        await session.commit()
        print(f"Seed 完成: 1 位管理員, {len(doctors)} 位醫師, {len(patients)} 位病患")

if __name__ == "__main__":
    asyncio.run(seed())
```

### 10.4 Mock 外部服務 (Mock Services)

#### Mock LLM Service (模擬 Claude API)

```python
# mocks/mock_llm_server.py

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI(title="Mock Claude API")

MOCK_RESPONSES = {
    "greeting": "您好，我是泌尿科 AI 問診助手。請問您今天有什麼不適的地方嗎？",
    "follow_up": "了解。請問這個症狀大約持續多久了？有沒有其他伴隨的症狀？",
    "red_flag": "[RED_FLAG:HEMATURIA] 您提到了血尿的情況，這需要進一步的檢查。我會通知您的主治醫師。",
    "soap": """S: 病患主訴頻尿、夜尿約2週，每晚起床3-4次。否認血尿、排尿疼痛。
O: 待醫師診察。
A: 疑似良性前列腺肥大 (BPH)，需進一步檢查排除其他診斷。
P: 建議安排 PSA 檢查、尿液分析、腎臟超音波。"""
}

@app.post("/v1/messages")
async def create_message(request: dict):
    """模擬 Claude API /v1/messages 端點。"""
    prompt = request.get("messages", [{}])[-1].get("content", "")

    # 簡單關鍵字匹配選擇回應
    if "血尿" in prompt or "hematuria" in prompt:
        response_text = MOCK_RESPONSES["red_flag"]
    elif "SOAP" in prompt:
        response_text = MOCK_RESPONSES["soap"]
    elif any(kw in prompt for kw in ["你好", "開始", "初次"]):
        response_text = MOCK_RESPONSES["greeting"]
    else:
        response_text = MOCK_RESPONSES["follow_up"]

    if request.get("stream", False):
        return StreamingResponse(
            _stream_response(response_text),
            media_type="text/event-stream"
        )
    else:
        return {
            "id": "mock-msg-001",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 100, "output_tokens": len(response_text)}
        }

async def _stream_response(text: str):
    """模擬 Claude API streaming 回應。"""
    words = text.split()
    for i, word in enumerate(words):
        chunk = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": word + " "}
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.05)  # 模擬延遲
    yield f"data: {json.dumps({'type': 'message_stop'})}\n\n"
```

#### Mock STT Service

```python
# mocks/mock_stt_server.py

from fastapi import FastAPI, UploadFile

app = FastAPI(title="Mock Google STT")

MOCK_TRANSCRIPTS = [
    "我最近一直頻尿，晚上要起來好幾次",
    "大概有兩個禮拜了",
    "沒有血尿，但是尿流比較弱",
    "之前沒有看過泌尿科",
]

_counter = 0

@app.post("/v1/speech:recognize")
async def recognize(audio: UploadFile):
    global _counter
    transcript = MOCK_TRANSCRIPTS[_counter % len(MOCK_TRANSCRIPTS)]
    _counter += 1
    return {
        "results": [{
            "alternatives": [{
                "transcript": transcript,
                "confidence": 0.95
            }]
        }]
    }
```

#### Mock TTS Service

```python
# mocks/mock_tts_server.py

from fastapi import FastAPI
from fastapi.responses import Response
import struct
import math

app = FastAPI(title="Mock Google TTS")

@app.post("/v1/text:synthesize")
async def synthesize(request: dict):
    """回傳一段靜音 WAV 作為模擬音檔。"""
    text = request.get("input", {}).get("text", "")
    duration_seconds = max(1, len(text) * 0.08)  # 粗略估計語音長度
    sample_rate = 24000
    num_samples = int(sample_rate * duration_seconds)

    # 產生簡單正弦波 (440Hz) 作為測試音
    audio_data = bytes()
    for i in range(num_samples):
        value = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
        audio_data += struct.pack("<h", value)

    return {
        "audioContent": __import__("base64").b64encode(audio_data).decode()
    }
```

### 10.5 Hot Reload 設定

**Python (FastAPI + Uvicorn):**

```bash
# Hot reload 已內建於 uvicorn --reload
uvicorn app.main:app --reload --reload-dir app --reload-include "*.py"
```

**React Web Dashboard:**

```bash
# Create React App / Vite 已內建 HMR
npm start  # CRA: webpack-dev-server with HMR
# 或
npm run dev  # Vite: native ESM + HMR
```

**React Native (Mobile):**

```bash
# Metro bundler with Fast Refresh
npx react-native start  # iOS/Android hot reload
```

**Celery Worker (使用 watchdog):**

```bash
# 安裝 watchdog 後支援 auto-reload
pip install watchdog
celery -A app.worker.app worker --loglevel=debug --autoreload
```

---

## 11. 環境配置清單

### 11.1 完整環境變數清單 (依服務分組)

> **所有環境變數命名以 shared_types.md section 7 為準。**

#### Application Config (應用程式設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `APP_ENV` | string | `development` | 是 | 環境名稱: development / staging / production |
| `DEBUG` | bool | `false` | 否 | 除錯模式（生產環境必須為 false） |
| `APP_PORT` | int | `8000` | 否 | API server 監聽埠 |
| `APP_HOST` | string | `0.0.0.0` | 否 | API server 監聽地址 |
| `APP_LOG_LEVEL` | string | `info` | 否 | 日誌層級: DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `APP_VERSION` | string | `0.0.0` | 否 | 應用程式版本號（CI/CD 自動設定） |
| `APP_WORKERS` | int | `4` | 否 | Uvicorn worker 數量 |
| `APP_SECRET_KEY` | string | -- | 是 | 應用程式主密鑰 |
| `WS_PORT` | int | `8001` | 否 | WebSocket gateway 監聽埠 |
| `WS_MAX_CONNECTIONS` | int | `500` | 否 | 單一 gateway 最大 WebSocket 連線數 |
| `WS_HEARTBEAT_INTERVAL` | int | `30` | 否 | WebSocket heartbeat 間隔（秒） |
| `WS_MESSAGE_MAX_SIZE` | int | `1048576` | 否 | WebSocket 單一訊息最大大小（bytes, 預設 1MB） |
| `CORS_ORIGINS` | string | `*` | 是 (prod) | 允許的 CORS origins，逗號分隔 |
| `TRUSTED_HOSTS` | string | `*` | 是 (prod) | 信任的 hosts，逗號分隔 |

#### Database Config (資料庫設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `DATABASE_URL` | string | -- | 是 | PostgreSQL 連線字串 (direct) |
| `PGBOUNCER_URL` | string | -- | 是 (prod) | PgBouncer 連線字串 (application 使用) |
| `DATABASE_URL_READ` | string | -- | 否 | Read replica 連線字串 |
| `DB_POOL_SIZE` | int | `10` | 否 | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | int | `20` | 否 | 超過 pool size 的額外連線數 |
| `DB_POOL_TIMEOUT` | int | `30` | 否 | 等待可用連線的逾時（秒） |
| `DB_POOL_RECYCLE` | int | `3600` | 否 | 連線回收間隔（秒） |
| `DB_ECHO` | bool | `false` | 否 | 是否印出 SQL 語句 |
| `DB_SSL_MODE` | string | `prefer` | 否 | SSL 模式: disable / prefer / require / verify-full |

#### Redis Config (快取設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `REDIS_URL` | string | `redis://localhost:6379/0` | 是 | Redis 連線字串 (cache) |
| `REDIS_TTL_DEFAULT` | int | `1800` | 否 | 預設快取 TTL（秒, 30 分鐘） |
| `REDIS_TTL_SESSION` | int | `3600` | 否 | 問診 session 快取 TTL（秒） |
| `REDIS_TTL_JWT_BLACKLIST` | int | `86400` | 否 | JWT blacklist TTL（秒, 24 小時） |
| `REDIS_MAX_CONNECTIONS` | int | `50` | 否 | Redis 連線池大小 |
| `REDIS_SSL` | bool | `false` | 否 | 是否啟用 Redis TLS |
| `CELERY_BROKER_URL` | string | `redis://localhost:6379/1` | 是 | Celery broker 連線字串 |
| `CELERY_RESULT_BACKEND` | string | `redis://localhost:6379/2` | 是 | Celery result backend 連線字串 |
| `CELERY_TASK_SOFT_TIME_LIMIT` | int | `300` | 否 | Celery task soft timeout（秒） |
| `CELERY_TASK_TIME_LIMIT` | int | `600` | 否 | Celery task hard timeout（秒） |

#### Auth Config (認證設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `JWT_ALGORITHM` | string | `RS256` | 否 | JWT 簽章演算法 |
| `JWT_PRIVATE_KEY_PATH` | string | -- | 是 | RSA private key 檔案路徑 |
| `JWT_PUBLIC_KEY_PATH` | string | -- | 是 | RSA public key 檔案路徑 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `15` | 否 | Access token 有效期（分鐘） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | int | `7` | 否 | Refresh token 有效期（天） |
| `PASSWORD_MIN_LENGTH` | int | `8` | 否 | 密碼最低長度 |
| `MAX_LOGIN_ATTEMPTS` | int | `5` | 否 | 最大登入嘗試次數 |
| `LOGIN_LOCKOUT_MINUTES` | int | `30` | 否 | 鎖定時間（分鐘） |
| `MFA_ENABLED` | bool | `false` | 否 | 是否啟用多因素認證 |

#### Claude API Config (LLM 設定)

> **依 shared_types.md section 7.5，Claude 設定拆分為 per-task 變數。**

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | string | -- | 是 | Anthropic API 密鑰 |
| `ANTHROPIC_API_BASE_URL` | string | `https://api.anthropic.com` | 否 | API base URL（可用於 proxy） |
| `CLAUDE_MODEL_CONVERSATION` | string | `claude-sonnet-4-20250514` | 否 | 對話用模型 |
| `CLAUDE_MODEL_SOAP` | string | `claude-sonnet-4-20250514` | 否 | SOAP 生成用模型 |
| `CLAUDE_MODEL_RED_FLAG` | string | `claude-haiku-4-5-20251001` | 否 | 紅旗偵測用模型 |
| `CLAUDE_TEMPERATURE_CONVERSATION` | float | `0.7` | 否 | 對話 temperature |
| `CLAUDE_TEMPERATURE_SOAP` | float | `0.3` | 否 | SOAP temperature |
| `CLAUDE_TEMPERATURE_RED_FLAG` | float | `0.2` | 否 | 紅旗 temperature |
| `CLAUDE_MAX_TOKENS_CONVERSATION` | int | `512` | 否 | 對話 max tokens |
| `CLAUDE_MAX_TOKENS_SOAP` | int | `4096` | 否 | SOAP max tokens |
| `CLAUDE_TIMEOUT` | int | `60` | 否 | API 呼叫逾時（秒） |
| `CLAUDE_MAX_RETRIES` | int | `3` | 否 | API 呼叫重試次數 |
| `CLAUDE_RATE_LIMIT_RPM` | int | `60` | 否 | 每分鐘最大請求數 |
| `CLAUDE_STREAMING_ENABLED` | bool | `true` | 否 | 是否啟用 streaming 回應 |
| `USE_MOCK_LLM` | bool | `false` | 否 | 是否使用 Mock LLM（開發用） |
| `MOCK_LLM_URL` | string | `http://localhost:9100` | 否 | Mock LLM 服務 URL |

#### Google STT Config (語音辨識設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | string | -- | 是 | GCP service account JSON 路徑 |
| `GOOGLE_CLOUD_PROJECT_ID` | string | -- | 是 | GCP 專案 ID |
| `GOOGLE_STT_LANGUAGE_CODE` | string | `zh-TW` | 否 | 語音辨識語言代碼 |
| `GOOGLE_STT_SAMPLE_RATE` | int | `16000` | 否 | 音訊取樣率 (Hz) |
| `GOOGLE_STT_ENCODING` | string | `LINEAR16` | 否 | 音訊編碼格式 |
| `GOOGLE_STT_MAX_ALTERNATIVES` | int | `1` | 否 | 最大替代結果數 |
| `GOOGLE_STT_ENABLE_AUTOMATIC_PUNCTUATION` | bool | `true` | 否 | 自動標點符號 |
| `GOOGLE_STT_MODEL` | string | `chirp_2` | 否 | STT 模型選擇 |
| `GOOGLE_STT_USE_ENHANCED` | bool | `true` | 否 | 使用增強模型 |
| `GOOGLE_STT_MEDICAL_VOCAB_ENABLED` | bool | `true` | 否 | 啟用醫療詞彙增強 |
| `USE_MOCK_STT` | bool | `false` | 否 | 是否使用 Mock STT（開發用） |
| `MOCK_STT_URL` | string | `http://localhost:9101` | 否 | Mock STT 服務 URL |

#### Google TTS Config (語音合成設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `GOOGLE_TTS_VOICE_NAME` | string | `cmn-TW-Wavenet-A` | 否 | TTS 語音名稱 |
| `GOOGLE_TTS_SPEAKING_RATE` | float | `0.9` | 否 | 語速 (0.25 - 4.0) |
| `GOOGLE_TTS_PITCH` | float | `0.0` | 否 | 音調 (-20.0 - 20.0) |
| `GOOGLE_TTS_VOLUME_GAIN_DB` | float | `0.0` | 否 | 音量增益 (dB) |
| `GOOGLE_TTS_AUDIO_ENCODING` | string | `MP3` | 否 | 輸出音訊格式: LINEAR16 / MP3 / OGG_OPUS |
| `GOOGLE_TTS_SAMPLE_RATE` | int | `24000` | 否 | 輸出取樣率 (Hz) |
| `GOOGLE_TTS_SSML_ENABLED` | bool | `true` | 否 | 是否使用 SSML 標記 |
| `USE_MOCK_TTS` | bool | `false` | 否 | 是否使用 Mock TTS（開發用） |
| `MOCK_TTS_URL` | string | `http://localhost:9102` | 否 | Mock TTS 服務 URL |

#### S3 / Object Storage Config (物件儲存設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `S3_BUCKET` | string | -- | 是 | S3 bucket 名稱 |
| `S3_REGION` | string | `ap-northeast-1` | 否 | S3 區域 |
| `S3_ENDPOINT_URL` | string | -- | 否 | 自訂 S3 endpoint（MinIO 用） |
| `AWS_ACCESS_KEY_ID` | string | -- | 是 | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | string | -- | 是 | AWS secret key |
| `S3_PRESIGNED_URL_EXPIRY` | int | `3600` | 否 | Presigned URL 有效期（秒） |
| `S3_UPLOAD_MAX_SIZE_MB` | int | `50` | 否 | 上傳檔案大小上限 (MB) |
| `S3_AUDIO_PREFIX` | string | `audio/` | 否 | 音檔儲存路徑前綴 |
| `S3_REPORTS_PREFIX` | string | `reports/` | 否 | 報告儲存路徑前綴 |
| `AUDIO_RETENTION_DAYS` | int | `1095` | 否 | 音訊保留天數（3 年） |
| `STORAGE_PROVIDER` | string | `s3` | 否 | 儲存提供商: s3 / gcs / local |

#### Firebase Cloud Messaging Config (推播通知設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `FCM_CREDENTIALS_PATH` | string | -- | 是 | Firebase service account JSON 路徑 |
| `FCM_PROJECT_ID` | string | -- | 是 | Firebase 專案 ID |
| `FCM_DRY_RUN` | bool | `false` | 否 | FCM dry run 模式（測試用） |
| `FCM_DEFAULT_SOUND` | string | `default` | 否 | 預設通知聲音 |
| `FCM_RED_FLAG_SOUND` | string | `alert_critical.wav` | 否 | 紅旗通知聲音 |
| `FCM_RED_FLAG_PRIORITY` | string | `high` | 否 | 紅旗通知優先級 |

#### Monitoring Config (監控設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `SENTRY_DSN` | string | -- | 否 | Sentry DSN (錯誤追蹤) |
| `SENTRY_TRACES_SAMPLE_RATE` | float | `0.1` | 否 | Sentry 效能追蹤取樣率 |
| `SENTRY_ENVIRONMENT` | string | -- | 否 | Sentry 環境名稱 |
| `PROMETHEUS_PORT` | int | `9090` | 否 | Prometheus metrics endpoint port |
| `PROMETHEUS_METRICS_PATH` | string | `/metrics` | 否 | Metrics endpoint 路徑 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | string | `http://jaeger:4317` | 否 | OpenTelemetry OTLP endpoint |
| `OTEL_SERVICE_NAME` | string | `gu-api` | 否 | OpenTelemetry 服務名稱 |
| `OTEL_TRACES_SAMPLER` | string | `parentbased_traceidratio` | 否 | Trace 取樣策略 |
| `OTEL_TRACES_SAMPLER_ARG` | float | `0.1` | 否 | Trace 取樣率 (production: 0.1) |
| `HEALTH_CHECK_TIMEOUT` | int | `5` | 否 | 健康檢查逾時（秒） |

#### PII Encryption Config (個資加密設定)

| 變數名稱 | 型別 | 預設值 | 必填 | 說明 |
|---|---|---|---|---|
| `ENCRYPTION_KEY` | string | -- | 是 | PII 欄位加密密鑰 (AES-256, 32 bytes) |
| `ENCRYPTION_KEY_VERSION` | int | `1` | 否 | 加密密鑰版本（支援 key rotation） |
| `ENCRYPTION_ALGORITHM` | string | `aes-256-cbc` | 否 | 加密演算法 |
| `PII_HASH_SALT` | string | -- | 是 | PII 雜湊用的 salt |

### 11.2 各環境設定對照表

| 變數 | Development | Staging | Production |
|---|---|---|---|
| `APP_ENV` | development | staging | production |
| `DEBUG` | true | false | false |
| `APP_LOG_LEVEL` | DEBUG | INFO | WARNING |
| `APP_WORKERS` | 1 | 2 | 4 |
| `DB_POOL_SIZE` | 10 | 10 | 20 |
| `DB_MAX_OVERFLOW` | 20 | 20 | 20 |
| `REDIS_MAX_CONNECTIONS` | 10 | 30 | 50 |
| `WS_MAX_CONNECTIONS` | 10 | 100 | 500 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | 15 | 15 |
| `CLAUDE_RATE_LIMIT_RPM` | 10 | 30 | 60 |
| `GOOGLE_TTS_VOICE_NAME` | `cmn-TW-Wavenet-A` | `cmn-TW-Wavenet-A` | `cmn-TW-Wavenet-A` |
| `GOOGLE_TTS_SAMPLE_RATE` | 24000 | 24000 | 24000 |
| `CORS_ORIGINS` | `*` | staging domain | production domain |
| `USE_MOCK_LLM` | true | false | false |
| `USE_MOCK_STT` | true | false | false |
| `USE_MOCK_TTS` | true | false | false |
| `SENTRY_TRACES_SAMPLE_RATE` | 1.0 | 0.5 | 0.1 |
| `OTEL_TRACES_SAMPLER_ARG` | 1.0 | 0.5 | 0.1 |
| `DB_SSL_MODE` | disable | require | verify-full |
| `REDIS_SSL` | false | true | true |
| `FCM_DRY_RUN` | true | true | false |

---

## 附錄

### A. Terraform 模組結構

```
terraform/
  |-- modules/
  |     |-- vpc/                 # VPC, Subnets, NAT Gateway
  |     |-- eks/                 # Kubernetes cluster (EKS/GKE)
  |     |-- rds/                 # PostgreSQL (RDS/Cloud SQL)
  |     |-- elasticache/         # Redis (ElastiCache/Memorystore)
  |     |-- s3/                  # Object storage buckets
  |     |-- iam/                 # IAM roles and policies
  |     |-- monitoring/          # Prometheus, Grafana, Loki
  |     |-- dns/                 # Route53/Cloud DNS
  |     |-- certificates/        # ACM/cert-manager
  |     |-- secrets/             # Secrets Manager/Vault
  |-- environments/
  |     |-- staging/
  |     |     |-- main.tf
  |     |     |-- variables.tf
  |     |     |-- terraform.tfvars
  |     |     |-- backend.tf
  |     |-- production/
  |           |-- main.tf
  |           |-- variables.tf
  |           |-- terraform.tfvars
  |           |-- backend.tf
  |-- versions.tf
  |-- providers.tf
```

### B. 聯絡與值班資訊

| 角色 | 職責 | 告警通知管道 |
|---|---|---|
| On-call SRE | P1/P2 告警處理 | PagerDuty (電話 + SMS) |
| Backend Lead | P1 升級處理 | PagerDuty + Slack |
| Security Officer | 資安事件處理 | PagerDuty + Email |
| Product Owner | 業務影響評估 | Slack + Email |

值班時間表：每週輪替，覆蓋 24/7 (P1) 與工作日 08:00-22:00 (P2/P3)

### C. 文件變更紀錄

| 版本 | 日期 | 變更內容 | 作者 |
|---|---|---|---|
| 1.0.0 | 2026-04-10 | 初始版本建立 | Infrastructure Team |
| 1.1.0 | 2026-04-10 | 對齊 shared_types.md：統一角色為 3 種 (patient/doctor/admin)、修正環境變數命名、修正專案目錄結構 (app/)、修正 TTS/Claude 設定、新增 Celery Beat K8s Deployment、新增 E2E/Mobile 測試 job、修正備份策略與 RPO 定義 | Infrastructure Team |

---

*本文件為機密文件，未經授權不得複製或散佈。*
*This document is confidential. Unauthorized reproduction or distribution is prohibited.*
