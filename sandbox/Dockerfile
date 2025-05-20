# -------------------------------------------------------------
# Manus‑Like Agent 用 Docker イメージ（強化版）
# -------------------------------------------------------------
    FROM ubuntu:22.04

    ENV DEBIAN_FRONTEND=noninteractive
    
    # 必要パッケージのインストール
    RUN apt-get update && \
        apt-get install -y --no-install-recommends \
            python3 python3-pip python3-venv \
            nodejs npm git curl wget ca-certificates \
            # Playwright が要求するライブラリ
            libnss3 libatk1.0-0 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 \
            libxcb1 libxrandr2 libgbm1 libasound2 libxext6 libgtk-3-0 \
            fonts-liberation \
        && rm -rf /var/lib/apt/lists/*
    
    # 非特権ユーザー作成
    RUN useradd -m -s /bin/bash ubuntu && \
        echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu
    
    USER ubuntu
    WORKDIR /home/ubuntu
    
    # Playwright のブラウザバイナリをインストール（必要な場合のみ）
    # ここでは起動時に python -m playwright install chromium を呼び出す想定
    
    # ワークスペースディレクトリ
    RUN mkdir -p /home/ubuntu/workspace
    WORKDIR /home/ubuntu/workspace
    
    CMD ["bash", "-c", "sleep infinity"]
    
