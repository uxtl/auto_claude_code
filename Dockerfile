FROM ubuntu:24.04

# ── Layer 1: OS packages + JDK 17 ──────────────────────────
# JDK 17 is required for AGP 8.x / Android API 34 builds.
# unzip + wget are needed for Android SDK cmdline-tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    unzip \
    wget \
    openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# ── Layer 2: Android SDK ────────────────────────────────────
# Install command-line tools, then use sdkmanager for the rest.
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=${ANDROID_HOME}

RUN mkdir -p ${ANDROID_HOME}/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
         -O /tmp/cmdline-tools.zip && \
    unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-unzip && \
    mv /tmp/cmdline-tools-unzip/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest && \
    rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-unzip

ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"

# Accept licenses and install SDK components (no NDK, no emulator, no system images)
RUN yes | sdkmanager --licenses > /dev/null 2>&1 && \
    sdkmanager --install \
        "platform-tools" \
        "build-tools;34.0.0" \
        "platforms;android-34" && \
    rm -rf ${ANDROID_HOME}/.temp

# ── Layer 3: Node.js + Claude Code CLI ──────────────────────
RUN apt-get update && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# ── Layer 4: uv (Python package manager) ────────────────────
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# ── Runtime setup ───────────────────────────────────────────
# Any UID can write to /home/user (runtime --user override)
RUN mkdir -p /home/user && chmod 777 /home/user
ENV HOME=/home/user
ENV PATH="/usr/local/bin:/root/.local/bin:${PATH}"

# Gradle defaults: disable daemon (ephemeral container) and limit workers
ENV GRADLE_OPTS="-Dorg.gradle.daemon=false -Dorg.gradle.workers.max=2"
ENV GRADLE_USER_HOME=/home/user/.gradle

WORKDIR /workspace
