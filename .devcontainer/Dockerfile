FROM node:20

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

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

# node 사용자는 기본 이미지에 존재하며 UID 1000을 사용
RUN groupadd -f docker \
 && usermod -aG docker,sudo node \
 && echo "node ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/node \
 && chmod 0440 /etc/sudoers.d/node

USER node

# npm 전역 설치 위치를 사용자 홈으로 변경
RUN mkdir -p /home/node/.npm-global \
 && npm config set prefix /home/node/.npm-global

ENV PATH="/home/node/.npm-global/bin:${PATH}"
ENV UV_LINK_MODE=copy

# Codex CLI
RUN npm install -g @openai/codex

WORKDIR /workspace
