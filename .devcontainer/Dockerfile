FROM node:20

# 기본 패키지 + Docker CLI
RUN apt-get update && apt-get install -y \
    git curl bash sudo \
    python3 python3-pip \
    ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI 설치 (공식 repo)
RUN install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null \
 && apt-get update \
 && apt-get install -y docker-ce-cli \
 && rm -rf /var/lib/apt/lists/*

# non-root user (VSCode 권장)
RUN useradd -ms /bin/bash vscode

# docker 그룹 권한 추가
RUN groupadd -f docker && usermod -aG docker vscode

USER vscode

# npm 전역 설치 위치를 사용자 홈으로 변경
RUN mkdir -p /home/vscode/.npm-global \
 && npm config set prefix /home/vscode/.npm-global

ENV PATH="/home/vscode/.npm-global/bin:${PATH}"

# Codex CLI
RUN npm install -g @openai/codex

WORKDIR /workspace

