FROM ubuntu:24.04

# 安装基础工具 + Node.js（Claude Code 依赖）+ uv
RUN apt-get update && apt-get install -y \
    curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户（Claude CLI 拒绝 root + --dangerously-skip-permissions）
RUN useradd -m -s /bin/bash vibe
ENV PATH="/home/vibe/.local/bin:/root/.local/bin:$PATH"

USER vibe
WORKDIR /workspace
