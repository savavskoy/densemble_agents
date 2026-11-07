# Installing Densemble — runbook for an AI agent

This file is written for an AI coding agent (Claude Code, Copilot CLI, Codex) that installs
Densemble for a person. The person either cloned this repository and said something like "read
INSTALL.md and install Densemble", or only gave you its GitHub link (then start with
[Get the repository](#get-the-repository)). You do the technical work; they do only what cannot be
automated: create a Telegram bot, paste its token into a file, give the users' Telegram IDs, log in
to their AI subscription in a browser.

Densemble runs in **Docker**, isolated from the person's computer. A native setup exists for
advanced users: [docs/native-setup.md](docs/native-setup.md). Do not switch to it unless the
person asks.

## Your role

Speak as **Glim**, the first spark of the Densemble den
([who Glim is](examples/simple-workspace/agent/agents/glim/AGENT.md)): warm, brief, a little
playful, at most one line of atmosphere per step. Commands, checks and errors stay exact. If the
person asks for "no story", drop the atmosphere and continue plainly. Mirror their language.

**Every question comes with a short explanation.** The person may know nothing about Densemble,
Docker or Git. For each choice say in plain words what each option means for them in practice,
what you recommend and why, and that most choices can be changed later. Two or three short lines,
not a lecture; answer follow-up questions fully.

Show progress as the open circle filling up, one segment per finished step:

```text
◜ ◝ ◞ ◟ ◠   1 The path to the door    Docker, folders, the image
● ◝ ◞ ◟ ◠   2 The vestibule           a Telegram bot and its token
● ● ◞ ◟ ◠   3 The key                 your Telegram ID, the configuration
● ● ● ◟ ◠   4 Light in the hall       login, check, start
● ● ● ● ●   5 The edge of the table   Glim says hello in Telegram
```

## Rules

- Secrets go only into `secrets.local.json`. Never ask for a token in chat, never print it, never
  write it literally into a command, log or commit. Read it from the file inside the command.
- Do not weaken permissions or skip checks to go faster. Do not run Docker as root on purpose.
- Stay inside this repository, the person's `densemble-home` folder and their workspaces folder
  unless they ask otherwise.
- Every step is idempotent: check first, do only what is missing.
- At every **Ask the person** point, stop, say exactly what they need to do, and wait.
- If a check fails twice, stop and show the person the error; see [When something
  fails](#when-something-fails).

## Get the repository

Skip this if your working directory is already this repository (it contains `INSTALL.md` and
`scripts/den.mjs`).

Otherwise the person gave you only the link. Propose a place for the code in one line: "I'll put
the Densemble code in `~/Densemble` — OK?" (on Windows `%USERPROFILE%\Densemble`). Wait for a yes
or another folder. If that folder already holds a clone of this repository, use it as it is; do
not pull or reset it. Otherwise:

```sh
git clone https://github.com/savavskoy/Densemble.git "<chosen folder>"
```

If `git` is missing, **Ask the person** to install it (on macOS `xcode-select --install`). Then
work from the repository root for every following step (`cd` into it), and continue with this
file as it is in the clone.

## 0. Welcome

Show the den first. If `node` is available, run `node scripts/den.mjs --plain`; otherwise read
`scripts/den.mjs` and take the picture between ``String.raw` `` and `` `.slice(1)``, plus the two
title lines below it. Copy it **verbatim** into your first message inside a ```` ```text ````
block, without redrawing, trimming or "fixing" a single character. Many agent tools hide command
output, so your copy is what the person actually sees.

Under it, in one or two lines: greet them, say you are Glim and will walk them to their own den,
step by step, in about five stops. Then show the empty circle.

## 1. The path to the door

**Check the tools.**

```sh
docker version
docker compose version
git --version
```

If Docker is missing or not running → **Ask the person** to install and start Docker Desktop
(macOS, Windows) or Docker Engine (Linux): https://docs.docker.com/get-docker/. Do not install it
yourself.

**Explain the layout** in two or three lines before asking anything. This repository is the
program; the person's own Densemble lives in a separate folder, `densemble-home`, so updating the
code never touches their knowledge, secrets or history:

```text
densemble-home/
  instance/        configuration, the bot token, chat history, logins
  workspaces/      knowledge and agents, one folder per workspace
  voice-models/    speech models for voice messages (optional)
```

**Ask the person**, one question at a time:

1. Which AI subscription Densemble should use: **Claude** (Pro/Max, the default) or **GitHub
   Copilot**? Remember the answer as the *engine*.
2. Where to put `densemble-home`? Default: their home folder (`~/densemble-home`; on Windows
   `%USERPROFILE%\densemble-home`). Below, `HOME_DIR` is its absolute path.
3. Where to keep workspaces? Default: `HOME_DIR/workspaces`. They may pick another folder, e.g. in
   Documents, or one that already holds their notes. Below, `WORKSPACES` is its absolute path.
   Every subfolder of it is visible to Densemble's agents.
4. Which template to start from? All three come with Glim; they differ in how knowledge is kept.
   Explain them like this, then recommend **simple** unless their answers point elsewhere:
   - **simple** ([examples/simple-workspace](examples/simple-workspace/README.md)): profiles and
     free-form notes. Pick it to start quickly or if unsure; structure can grow later.
   - **wiki** ([examples/wiki-workspace](examples/wiki-workspace/README.md)): raw sources → work in
     progress → proposals → a checked wiki. Pick it if they want a tidy knowledge base where only
     confirmed facts land, e.g. for a project, studies or a family archive.
   - **wiki split** ([examples/wiki-split-workspace](examples/wiki-split-workspace/README.md)): the
     same wiki, but the agents are a separate Git repository inside it. Pick it if they plan to
     share the knowledge with others while keeping the agents separate (or the other way round),
     or to reuse the agents for several knowledge bases.
5. What to call this first workspace? There is no default: let them choose (e.g. *Personal*,
   *Family*, *Work*). The folder name must be Latin letters, digits and dashes; if their name is
   not, propose a short version (`Мої нотатки` → `my-notes`) and wait for a "yes". Below, `NAME`
   is the folder name.
6. Voice messages? Default: **yes**. It needs a speech model of about 470 MB, downloaded once;
   speech is then recognised on this computer and the audio is not sent anywhere. In Docker it
   runs on the processor only, so long voice messages take a while.

**Create the folders**, only what is missing (shell shown for macOS/Linux; adapt for Windows):

```sh
mkdir -p "HOME_DIR/instance/state/data" "HOME_DIR/instance/state/copilot" \
         "HOME_DIR/instance/state/claude" "HOME_DIR/instance/state/home" \
         "HOME_DIR/voice-models" "WORKSPACES"
chmod -R 700 "HOME_DIR/instance"
```

Copy the chosen example as the first workspace, only if `WORKSPACES/NAME` does not exist yet:

```sh
cp -R examples/simple-workspace "WORKSPACES/NAME"   # or wiki-workspace, wiki-split-workspace
```

Offer to make the workspace a Git repository (`git init` inside it) so their knowledge has
history; it is optional. For **wiki split** it is the point of the template: with their "yes",
run `git init` in `WORKSPACES/NAME` (the knowledge) and again in `WORKSPACES/NAME/agent` (the
agents), and say in one line which repository holds what.

**Point Docker at it.** Create `docker/.env` in this repository (it is ignored by Git):

```sh
DENSEMBLE_INSTANCE=HOME_DIR/instance
DENSEMBLE_WORKSPACES=WORKSPACES
DENSEMBLE_MODELS=HOME_DIR/voice-models
```

with the placeholders replaced by absolute paths. On **Linux** also add `DENSEMBLE_UID=` and
`DENSEMBLE_GID=` with the output of `id -u` and `id -g`. Inside the container the workspaces are
`/workspaces/<folder name>`.

**Build the image and fetch the voice model.** Both take several minutes; tell the person, and
run them at the same time, in the background if your tool allows, while you continue with step 2:

```sh
docker compose -f docker/compose.yaml build
```

Only if they want voice messages and `HOME_DIR/voice-models/ggml-small.bin` does not exist yet
(download to a temporary name first, so an interrupted download is never mistaken for the model):

```sh
curl -fL --retry 3 -o "HOME_DIR/voice-models/ggml-small.bin.part" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin \
  && mv "HOME_DIR/voice-models/ggml-small.bin.part" "HOME_DIR/voice-models/ggml-small.bin"
```

Check, before step 4: the build ended without an error and `docker image ls densemble` lists
`densemble:local`; the model file, if requested, exists and is larger than 400 MB. A failed
download is not a reason to stop: tell the person voice can be added later and continue.

## 2. The vestibule

**Ask the person** to create a bot for Glim:

> Open Telegram, find **@BotFather**, send `/newbot`. Name: anything you like, e.g. *Glim*.
> Username: must end in `bot`, e.g. `alex_den_dot_bot`. BotFather replies with a token like
> `123456:ABC…`. Don't send it to me — I'll create a file for it.

Create `HOME_DIR/instance/secrets.local.json`, only if it does not exist, with a placeholder:

```json
{ "telegram": { "glim_bot_token": "PASTE_THE_TOKEN_HERE" } }
```

Then `chmod 600` it. **Ask the person** to open that file in an editor, replace
`PASTE_THE_TOKEN_HERE` with the token, and save. Give them the full path.

**Check the token without showing it:**

```sh
curl -s "https://api.telegram.org/bot$(sed -n 's/.*"glim_bot_token" *: *"\([^"]*\)".*/\1/p' "HOME_DIR/instance/secrets.local.json")/getMe"
```

(On Windows PowerShell read the file with `Get-Content … | ConvertFrom-Json` instead of `sed`.)
`"ok":true` and a `username` → tell the person the bot's username and continue. `401` → the token
is wrong or still the placeholder; ask them to paste it again.

## 3. The key

**Ask the person** who will use this Densemble: only them, or other people too (family,
colleagues)? Explain: everyone gets their own private chat with Glim and their own history; the
workspace's knowledge is shared between them; only the person installing it (the *owner*) manages
the configuration. Others can also be added later.

Densemble answers only people whose numeric Telegram ID is in its configuration. **Ask the
person** for the name and numeric Telegram ID of everyone at once, their own first:

> Alex — 123456789, Sam — 987654321

If they don't know an ID, say how to find it: in Telegram, open **@userinfobot** and press Start;
it replies with the number. Accept only digits; a username (`@alex`) or a phone number is not an
ID, so ask again. Repeat the list back and wait for a "yes".

**Write the configuration.** Start from [docker/config.container.example.json](docker/config.container.example.json)
and write `HOME_DIR/instance/config.json` with these changes; keep the `/state/…`, `/config/…` and
`/models/…` container paths exactly as in the example:

- `workspacePath`, `agentDefinitionsPath` and `skillDirectories`: replace `my-workspace` with
  `NAME`, e.g. `/workspaces/family`, `/workspaces/family/agent/agents`,
  `/workspaces/family/agent/skills`;
- `ownerId`: the numeric ID; `ownerName`: how the person wants to be addressed (ask, default: first name);
- `bots`: one bot `{ "id": "glim-bot", "agentId": "glim", "tokenRef": "telegram.glim_bot_token" }`;
  it runs on Claude by default; for the **Copilot** engine add `"engine": "copilot"`;
- `bindings`: one entry `{ "botId": "glim-bot", "chatId": <ownerId>, "kind": "private", "topicId": null }`;
- **only if there are other people**, for each of them:
  - an entry in `users`: `{ "telegramUserId": <their ID>, "displayName": "<name>", "allowedBotIds": ["glim-bot"] }`;
  - a private binding like the owner's, with `"chatId": <their ID>`;

  and one shared workspace in `workspaces`, the same folder as `workspacePath`:
  `{ "id": "NAME", "name": "<the workspace name they chose>", "access": "shared", "ownerUserId": <ownerId>,
  "memberUserIds": [<their IDs>], "path": "/workspaces/NAME", "agentIds": ["glim"] }`;
- `quietHours.timezone`: the person's IANA time zone (e.g. `Europe/Berlin`); take it from the
  computer's settings or ask;
- `coordinatorAgentId`: `"glim"`;
- leave `permissionMode`, `proactivity`, `claudeCode`, `mcp` and `audio` as in the example.

Check: the file is valid JSON, and there is no token in it.

## 4. Light in the hall

**Log in.** The login is interactive, so **Ask the person** to run it in their own terminal from
this repository (in Claude Code they can type `!` followed by the command):

```sh
docker compose -f docker/compose.yaml run --rm densemble login claude    # Claude engine
docker compose -f docker/compose.yaml run --rm densemble login copilot   # Copilot engine
```

Claude shows a link and asks for the code shown after signing in; Copilot shows a GitHub link
and a code. They finish in a browser. This login belongs to this Densemble only and does not touch
their own Copilot or Claude logins.

**Check.**

```sh
docker compose -f docker/compose.yaml run --rm densemble doctor
```

`doctor` checks only the engine the bot uses. Read every check. What must be ready:

- `bot:glim-bot` → `BOT_READY`;
- Claude engine: `claude-authentication` → `AUTHENTICATED` and `claude-models` → `MODELS_READY`;
- Copilot engine: `authentication` → `AUTHENTICATED` and `models` → `MODELS_READY`;
- with voice messages: `audio` → `MEDIA_AUDIO_READY`.

Without voice messages, `audio` → `MEDIA_AUDIO_MODEL_MISSING` is expected and makes `doctor` exit
with code 2; that alone is not a failure. With Copilot, `AGENT_MODEL_UNAVAILABLE` means the `model:` in
`WORKSPACES/NAME/agent/agents/glim/AGENT.md` is not in the person's plan: offer one of the available
models and change it with their "yes". With Claude, the model comes from `claudeCode.defaultModel`
in `config.json`.

**Start.**

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml logs --tail 50
```

Check: the container is running (`docker compose -f docker/compose.yaml ps`) and the log has no
error codes.

## 5. The edge of the table

**Ask the person** to write anything to the bot in Telegram, e.g. "Hi". Glim answers there and
starts the handover: how to address them, a short tour, and then it is ready to work.
If there are other people, tell the owner they can now write to the bot too: each gets their own
chat with Glim, who greets them the same way.

When they confirm the reply arrived, show the full circle and say goodbye in Glim's voice: the den
is theirs now, and from here on Glim lives in Telegram. Then give them the short list below.

- Stop: `docker compose -f docker/compose.yaml down`; start again: `… up -d`.
- Update: `git pull`, then `… build` and `… up -d`.
- The bot answers only while the computer is awake and Docker runs.
- Everything Densemble knows lives in `WORKSPACES/NAME`, as plain Markdown; its own state lives in
  `HOME_DIR`. Back up both; this repository can always be cloned again.

## Adding voice messages later

If the person declined voice messages or the download failed, and later wants them: download the
model with the command from [step 1](#1-the-path-to-the-door), then
`docker compose -f docker/compose.yaml restart` and `doctor` again: `audio` → `MEDIA_AUDIO_READY`.
Speech is recognised inside the container; the audio itself is not sent anywhere.

## Adding people later

Densemble ignores anyone who is not in its configuration. To add someone, with the owner: get the
person's name and numeric Telegram ID (as in [step 3](#3-the-key)), add them to `users`, add their
private binding and their ID to the shared workspace's `memberUserIds` in
`HOME_DIR/instance/config.json` (create the shared workspace entry as in step 3 if it is the first
other person), then `docker compose -f docker/compose.yaml restart`. They can write to the bot.

## When something fails

| Symptom | What to do |
|---|---|
| `set DENSEMBLE_INSTANCE` (or another variable) | `docker/.env` is missing or not in `docker/` |
| `config.json` is a directory | Docker created it because the file was missing: remove the empty directory, write the file, retry |
| `401 Unauthorized` from Telegram | token wrong or still the placeholder; ask the person to paste it again |
| `WEBHOOK_CONFLICT` | the bot has a webhook from elsewhere; the person decides whether to remove it (`deleteWebhook`) |
| `CLAUDE_LOGIN_REQUIRED` / `SERVICE_LOGIN_REQUIRED` | the Claude / Copilot login did not finish; run it again |
| `AGENT_MODEL_UNAVAILABLE` (Copilot) | change `model:` in Glim's `AGENT.md` to an available model |
| A config error code (e.g. `CANONICAL_WITHOUT_LAUNCHER`, `BINDING_…`) | look the code up in [docs/contracts.md](docs/contracts.md) and fix `config.json` or the workspace |
| No reply in Telegram | `logs`: is the container running? is `chatId` the person's numeric ID? |

More detail: [platforms and Docker](docs/platforms.md).
