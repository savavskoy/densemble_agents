# syntax=docker/dockerfile:1
# Densemble for Linux (linux/amd64, linux/arm64). Build from the repository root:
#   docker compose -f docker/compose.yaml build
# Contract: oleh/programming/projects/densemble/specs/007-linux-docker/contracts/container.md
# No secrets, configuration or speech models are ever part of the image.

ARG NODE_IMAGE=node:24.21.0-bookworm-slim

# --- whisper-cli, pinned to the version used on macOS; portable CPU build (no host-specific instructions)
FROM ${NODE_IMAGE} AS whisper
ARG WHISPER_CPP_VERSION=v1.9.4
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${WHISPER_CPP_VERSION}" https://github.com/ggml-org/whisper.cpp /src/whisper.cpp
RUN cmake -S /src/whisper.cpp -B /build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DBUILD_SHARED_LIBS=OFF \
      -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF \
 && cmake --build /build --target whisper-cli -j"$(nproc)" \
 && install -m 0755 /build/bin/whisper-cli /usr/local/bin/whisper-cli

# --- dependencies from the lockfile; npm picks the linux engine/native packages by os/cpu/libc
FROM ${NODE_IMAGE} AS deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 make g++ \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM deps AS build
COPY tsconfig.json tsconfig.build.json vitest.config.ts ./
COPY src src
RUN npm run build

# --- offline test suite on Linux: docker build -f docker/Dockerfile --target test -t densemble:test .
FROM build AS test
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY --from=whisper /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli
COPY Makefile .nvmrc ./
COPY tests tests
COPY docker docker
# Not root: permission tests must see what a normal user sees.
RUN chown -R node:node /app
USER node
CMD ["npm", "test"]

FROM deps AS prod-deps
RUN npm prune --omit=dev --no-audit --no-fund

# --- runtime
FROM ${NODE_IMAGE} AS runtime
# ffmpeg/whisper for voice; tini as PID 1 reaps orphaned engine children; the rest is the agents' shell toolbox.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgomp1 tini ca-certificates git curl jq ripgrep python3 less \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 densemble \
 && useradd --uid 10001 --gid 10001 --home-dir /state/home --no-create-home --shell /bin/bash densemble
COPY --from=whisper /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli
WORKDIR /app
COPY --from=prod-deps /app/node_modules node_modules
COPY --from=build /app/dist dist
# Module instructions and READMEs are read from src/ at runtime.
COPY --from=build /app/src src
COPY package.json ./
ENV NODE_ENV=production DENSEMBLE_CONTAINER=1 DENSEMBLE_CONFIG=/config/config.json HOME=/state/home
USER 10001:10001
ENTRYPOINT ["tini", "--", "node", "/app/dist/main.js"]
CMD ["start"]
