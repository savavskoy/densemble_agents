# Platforms and Docker

Densemble runs:

| Where | How | Background service |
|---|---|---|
| macOS on Apple Silicon | natively (as before) | LaunchAgent (`make install`, `make start`) |
| Linux (glibc, x64 or arm64) | natively | systemd user unit (`node dist/main.js service-unit`) |
| Any computer with Docker — macOS, Windows, Linux | the `docker/` image | the container's restart policy |

Native Windows, musl Linux (Alpine) and Intel Macs are not supported: Densemble refuses to start
there with `PLATFORM_UNSUPPORTED`. On Windows use Docker Desktop.

## What works where

| Feature | macOS native | Linux native / Docker |
|---|---|---|
| Telegram chats, Copilot and Claude Code engines, `/stop`, `/model` | yes | yes |
| Voice messages, documents, photos, file export | yes | yes |
| Proactivity, multi-user workspaces, permissions | yes | yes |
| `doctor`, backup / restore, `modules-status` | yes | yes |
| Modules `recordings` and `reels` | yes | not yet — reported as `unavailable` (`MODULE_PLATFORM_UNSUPPORTED`) |
| System notifications | yes | — |

All the platform differences live in [`src/platform/`](../src/platform/); no other code checks the
operating system.

## An isolated instance in Docker

The container sees **only** what you mount: its configuration, secrets file, state folder, speech
models and your workspaces folder. It cannot see your home folder, your other files, your
personal Densemble or the Docker socket. Agents run as a normal user (never root), without Linux
capabilities, on a read-only filesystem. Densemble refuses to start as root
(`CONTAINER_ROOT_FORBIDDEN`) or with its state outside a mount (`CONTAINER_STATE_NOT_MOUNTED`), so
nothing is lost when the container is recreated.

### 1. Prepare `densemble-home`

Your own Densemble lives outside this repository, by default in `~/densemble-home`:

```text
densemble-home/
  instance/        config.json, secrets.local.json, state/
  workspaces/      one folder per workspace, e.g. family/
  voice-models/    ggml-small.bin for voice messages (optional)
```

```sh
mkdir -p ~/densemble-home/instance/state/{data,copilot,claude,home} ~/densemble-home/{workspaces,voice-models}
chmod -R 700 ~/densemble-home/instance
cp docker/config.container.example.json ~/densemble-home/instance/config.json
cp -R examples/simple-workspace ~/densemble-home/workspaces/family
```

- `config.json`: set `ownerId`, bots, bindings, agents. **Paths are container paths**: a workspace
  folder `family` is `/workspaces/family`; keep `/state/...`, `/config/...` and `/models/...` as in
  the example.
- `secrets.local.json` next to it: the bot tokens referenced by `tokenRef`. Use bots of their own:
  one Telegram bot cannot serve two instances.
- Workspaces hold the agents (`agent/agents`, `agent/skills`; start from
  [`examples/simple-workspace`](../examples/simple-workspace/README.md)). The workspaces folder may
  live elsewhere, e.g. in Documents. Voice: see [native setup → voice](native-setup.md#local-voice-and-media).

### 2. Point Docker at it

Create `docker/.env` (ignored by git):

```sh
DENSEMBLE_INSTANCE=/Users/you/densemble-home/instance
DENSEMBLE_WORKSPACES=/Users/you/densemble-home/workspaces
DENSEMBLE_MODELS=/Users/you/densemble-home/voice-models
# Linux hosts only — so files the agents create in the workspace stay yours:
# DENSEMBLE_UID=1000
# DENSEMBLE_GID=1000
```

On Windows use paths like `C:/Users/you/densemble-home/instance`. Several instances: a separate
`densemble-home`, another `.env` and `DENSEMBLE_NAME`.

### 3. Build, log in, check, start

From the repository root:

```sh
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml run --rm densemble login claude    # or: login copilot
docker compose -f docker/compose.yaml run --rm densemble doctor
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml logs -f
```

`login copilot` prints a GitHub URL and a code; `login claude` prints a URL and asks for the code
shown after you sign in. Finish in a browser on any device. The login is stored in the instance's
`state/` and is separate from your own Copilot/Claude logins; it survives restarts and new images.
Run `login` while the instance is stopped (`down`), because it takes the instance lock. The image
sets `DENSEMBLE_CONFIG=/config/config.json`, so container commands need no `--config`.

Update: `git pull`, then `build` and `up -d` again. Stop: `down`.

### What is and is not isolated

- Isolated: every host path that is not mounted, other instances, your own engine logins.
- Not isolated: whatever you mount (agents can read and change every workspace in the workspaces
  folder and read the secrets file, exactly as natively; `private`/`shared` workspace access is
  enforced by Densemble, not by the container); outgoing network access (agents can reach the internet);
  the host administrator, who can read everything the container uses.
- The bots answer only while the computer is awake and Docker runs. For 24/7, move the instance to
  a server (below).

## Moving an instance to another machine

**Whole instance (simplest).** Stop it (`down`), copy `densemble-home` — config, secrets, the
entire `state/`, workspaces and voice models — to the new machine, set `docker/.env` there and
`up -d`. Conversations, proactive items, Claude Code histories and engine logins all come along.
On a Linux host set `DENSEMBLE_UID/GID` and make the copied `state/` owned by that user.

**Backup and restore** (also between Docker and native installs). Backups hold conversations,
proactive items, media and Copilot histories, but deliberately **no engine logins**:

1. Old machine: `down`, then
   `docker compose -f docker/compose.yaml run --rm -v /path/to/backups:/backup densemble backup --target /backup/team-1`.
2. New machine: config, secrets, workspaces and voice models in place, an empty `state/` as in step 1.
3. The same command with `restore --target /backup/team-1`, then `login`, `up -d`.

A backup restores on any supported platform, natively or in Docker.

## Native Linux

Install Node 24 (`.nvmrc`), `ffmpeg` and `whisper-cli`, then as on macOS: `npm ci`, `npm run build`,
`node dist/main.js login copilot --config config.local.json` (or `make copilot-login` /
`make claude-login`; stop the service first, the login takes the instance lock), `doctor`, `start`. Point
`audio.*Path` at `/usr/bin/ffmpeg`, `/usr/bin/ffprobe` and your `whisper-cli`. For a background
service:

```sh
mkdir -p ~/.config/systemd/user
node dist/main.js service-unit --config "$PWD/config.local.json" > ~/.config/systemd/user/densemble.service
systemctl --user daemon-reload && systemctl --user enable --now densemble
loginctl enable-linger "$USER"   # keep it running after logout
```

Densemble never installs the unit itself.
