# =============================================================================
# 泌尿科 AI 語音問診助手 — 後端 Docker 映像檔（多階段建置）
# 適用於 Railway 部署
# =============================================================================

# ---------------------------------------------------------------------------
# 階段一：建置階段 — 安裝 Python 套件
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# 安裝編譯所需的系統套件（部分 Python 套件需要 C 編譯）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 將套件安裝到 /build/deps，方便後續複製到生產階段
RUN pip install --no-cache-dir --prefix=/build/deps -r requirements.txt


# ---------------------------------------------------------------------------
# 階段二：生產階段 — 精簡映像檔
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS production

LABEL maintainer="GU Urology AI Team"
LABEL description="泌尿科 AI 語音問診助手 — FastAPI 後端服務"

# WeasyPrint 及 PDF 產生所需的系統依賴套件
# libpango、libcairo、libgdk-pixbuf 為 WeasyPrint 核心依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libcairo-gobject2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libxml2 \
    libxslt1.1 \
    shared-mime-info \
    fonts-noto-cjk \
    libpq5 \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# 從建置階段複製已安裝的 Python 套件
COPY --from=builder /build/deps /usr/local

WORKDIR /app

# 建立非 root 使用者（安全性最佳實踐）
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

# 複製啟動腳本並賦予執行權限
COPY scripts/start.sh /app/scripts/start.sh
RUN chmod +x /app/scripts/start.sh

# 複製應用程式原始碼
COPY . /app

# 確保 appuser 擁有應用程式目錄的權限
RUN chown -R appuser:appuser /app

# 切換至非 root 使用者
USER appuser

# 暴露服務埠
EXPOSE 8000

# 健康檢查 — 每 30 秒確認服務是否正常運作
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 使用 tini 作為 init 程序，確保信號正確傳遞（優雅關閉）
ENTRYPOINT ["tini", "--"]

# 啟動服務
CMD ["/app/scripts/start.sh"]
