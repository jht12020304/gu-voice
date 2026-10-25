# =============================================================================
# 泌尿科 AI 語音問診助手 — 前端 Docker 映像檔
# =============================================================================

# ── 建置階段 ──────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_WS_BASE_URL=ws://localhost:8000/api/v1/ws
ARG VITE_ENABLE_MOCK=false

RUN npm run build


# ── 生產階段 ──────────────────────────────────────────
FROM nginx:alpine AS production

# 複製 Nginx 設定
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 複製建置產物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
