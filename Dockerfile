FROM ubuntu:24.04

# 安装基础工具 + Node.js（Claude Code 依赖）+ uv
RUN apt-get update && apt-get install -y \
    curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# 任意 UID 均可写入的 home（运行时通过 --user 指定 UID）
RUN mkdir -p /home/user && chmod 777 /home/user
ENV HOME=/home/user
ENV PATH="/usr/local/bin:/root/.local/bin:$PATH"

WORKDIR /workspace
