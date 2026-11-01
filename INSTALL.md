# Installing Densemble — a runbook for your coding agent

**Human:** read this file before you hand it to an agent: it will run commands on your Mac.
Then open your coding agent (Claude Code, Copilot CLI or Codex) in this folder and say:

> Read INSTALL.md and install and run Densemble for me.

Expect 30–90 minutes. You will be asked to do only what cannot be automated: create a
Telegram bot, log in to your AI subscription in a browser, and make a few choices.

**Agent:** this is a runbook, not prose. Work through the steps in order. Every step has a
**Check**; do not continue until it passes. Steps are safe to repeat: if a check already
passes, move on. `STOP AND ASK` means: ask the human with the given wording, wait, continue.

## Rules for the agent

1. **Secrets.** Bot tokens live only in the workspace's `secrets.local.json` (mode `0600`).
   Never print a token, never put it in a command line, a commit, a log or this chat. Ask the
   human to paste it into the file themselves. If they paste it into the chat anyway, write it
   to the file, do not repeat it, and suggest regenerating it later in BotFather (`/revoke`).
2. **Do not weaken safety to go faster:** no `chmod 777`, no disabling macOS protections, no
   `sudo` unless a step says so, no skipping a failed check.
3. **Stay in two folders:** this Densemble folder and the workspace folder the human chooses.
   Do not touch the human's other files, global CLI settings, `~/.copilot` or `~/.claude`.
4. **No git operations that change state** in this folder (no commit, push, pull, reset).
5. Run commands from this folder (the one containing `INSTALL.md`) unless a step says otherwise.
6. If a step fails twice, show the human the exact error and the
   [common failures](#common-failures), and ask how to proceed.

Values you collect along the way (keep them in your working notes, never in a file except
where a step says so):

| Name | Example |
|---|---|
| `CODE` | absolute path of this folder |
| `WORKSPACE` | absolute path of the human's workspace, e.g. `/Users/alex/densemble-workspace` |
| `ENGINE` | `copilot` or `claude-code` |
| `OWNER_NAME`, `TIMEZONE` | `Alex`, `Europe/Berlin` |
| `OWNER_ID` | the human's numeric Telegram user ID |

## 1. Check the Mac

```sh
uname -sm            # must print: Darwin arm64
sw_vers -productVersion
xcode-select -p      # Command Line Tools path; native modules may need them
```

**Check:** `Darwin arm64`. Densemble supports only Apple Silicon macOS. On anything else, stop
and tell the human it is not supported.
If `xcode-select -p` fails, ask the human to run `xcode-select --install` and finish the dialog.

## 2. Node.js 24 and npm 11

The exact version is in `.nvmrc`. Prefer `nvm`:

```sh
command -v nvm || ls ~/.nvm/nvm.sh
source ~/.nvm/nvm.sh && nvm install && nvm use
node -v && npm -v
```

If there is no nvm, STOP AND ASK: *"Densemble needs Node.js 24. May I install nvm (the Node
version manager) from https://github.com/nvm-sh/nvm with its official install script?"*

**Check:** `node -v` prints `v24.…`, `npm -v` prints `11.…`. Use this Node for every command.

## 3. Choose the AI engine

STOP AND ASK: *"Which subscription should your agents run on: GitHub Copilot or Claude
(Claude Code)? You can add the other one later."*

- Copilot → `ENGINE=copilot`. Needs an active Copilot subscription on the human's GitHub account.
- Claude → `ENGINE=claude-code`. Needs a Claude Pro/Max subscription.

**Check:** `ENGINE` is set.

## 4. Install, test and build

```sh
npm ci
npm test
npm run build
```

**Check:** all three succeed (`npm test` ends with all test files passed; a few skipped is
fine). If `npm ci` fails building `better-sqlite3`, the Command Line Tools from step 1 are
missing. An npm warning that `koffi` has install scripts "not yet covered by allowScripts" is
expected; do not approve or change scripts.

## 5. Create the workspace

The workspace is the human's own folder: their knowledge base and the home of their agents.
It must be **outside** this Densemble folder.

STOP AND ASK: *"Where should I create your workspace — the folder where your knowledge and
your agents will live? (Default: `~/densemble-workspace`.) If you already have a folder with
notes you want your agents to use, give me its path instead."*

- **New folder:** copy the template, without its README:

  ```sh
  mkdir -p "$WORKSPACE"
  rsync -a --ignore-existing --exclude README.md workspace-template/ "$WORKSPACE/"
  ```

- **Existing folder:** list what is there first. Add the template files with the same
  `rsync --ignore-existing` (it never overwrites). If the folder already has an `AGENTS.md`,
  do not replace it: show the human the template's `AGENTS.md` and offer to merge its
  sections in.

Then STOP AND ASK: *"Do you want the workspace to be a git repository, so you have history
of your notes? (Recommended; it stays local unless you push it somewhere.)"* If yes:
`git -C "$WORKSPACE" init` (the template's `.gitignore` already excludes `secrets.local.json`).

**Check:** `"$WORKSPACE"/.github/agents/assistant.agent.md`,
`"$WORKSPACE"/agent/agents/assistant/AGENT.md` and `"$WORKSPACE"/AGENTS.md` exist, and
`$WORKSPACE` is not inside `$CODE`.

## 6. About the owner

STOP AND ASK, as one message:
*"A few details for your agents: 1) What name should they call you? 2) Your timezone
(e.g. Europe/Berlin)? 3) Quiet hours when agents must not write first (default 01:00–09:30)?
4) Your main agent is called `assistant`. Keep that, or give it another name?"*

- Write the name, timezone and language into `"$WORKSPACE"/knowledge/profile.md`.
- If they want another agent name, choose an id (lowercase, digits, hyphens) and rename it
  everywhere: the folder `agent/agents/assistant`, the file
  `.github/agents/assistant.agent.md`, its `name:` field and the path inside it, the
  `assistant` id in `AGENTS.md`, and the secret key and config values below. Replace the
  display name in its `AGENT.md` heading. Use the new id wherever this runbook says
  `assistant`.

**Check:** `OWNER_NAME` and `TIMEZONE` are set; the launcher's `name:` equals its file name
and its folder in `agent/agents/`.

## 7. Telegram bot

STOP AND ASK:
*"Now create your bot in Telegram: 1) open @BotFather, 2) send /newbot, 3) choose a display
name and a username that ends in `bot`. BotFather replies with a token. Do not send the
token to me — I'll open a file for you to paste it into."*

Create the secrets file and open it for the human:

```sh
cd "$WORKSPACE"
test -f secrets.local.json || cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
open -e secrets.local.json
```

Say: *"Replace `replace-with-the-token-from-BotFather` with your token, keep the quotes,
save and close the file, then tell me 'done'."*

Verify the token without printing it (run from `$CODE`, pass the path as an argument):

```sh
node -e 'const s=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));const t=s.telegram.assistant_bot_token;fetch(`https://api.telegram.org/bot${t}/getMe`).then(r=>r.json()).then(j=>console.log(j.ok?`OK @${j.result.username}`:`FAIL ${j.description}`))' "$WORKSPACE/secrets.local.json"
```

**Check:** prints `OK @<bot username>`. On `FAIL Unauthorized`, the token is wrong or has
extra spaces: ask the human to fix the file.

## 8. The human's Telegram ID

STOP AND ASK: *"Open your new bot @<bot username> in Telegram and press Start (or send it
any message). Tell me when you've done it."*

```sh
node -e 'const s=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));const t=s.telegram.assistant_bot_token;fetch(`https://api.telegram.org/bot${t}/getUpdates`).then(r=>r.json()).then(j=>{for(const u of j.result??[]){const m=u.message;if(m)console.log(m.from.id,"@"+(m.from.username??"-"),m.chat.type)}})' "$WORKSPACE/secrets.local.json"
```

**Check:** a line with a numeric ID and `private`. That number is `OWNER_ID`. If several
people appear, ask the human which username is theirs. If nothing appears, ask them to send
another message and run it again. (This works only before Densemble runs; afterwards the
service consumes the updates.)

## 9. Permissions mode

STOP AND ASK: *"How careful should your agents be? **Manual**: they ask you with a button in
Telegram before each action (safer, more taps). **Autopilot**: they act on their own inside
their tools (faster; use only if you trust the setup). If unsure, choose manual — you can
switch later."*

**Check:** `permissionMode` is `manual` or `autopilot`.

## 10. Configuration

Create private runtime folders and `config.local.json` in `$CODE` (it is git-ignored):

```sh
mkdir -p data runtime/copilot && chmod 700 data runtime/copilot
# only for ENGINE=claude-code:
mkdir -p runtime/claude && chmod 700 runtime/claude
```

Write `config.local.json` with real absolute paths and values (no `~`, no placeholders):

```json
{
  "workspacePath": "<WORKSPACE>",
  "agentDefinitionsPath": "<WORKSPACE>/agent/agents",
  "agentLaunchersPath": "<WORKSPACE>/.github/agents",
  "secretsPath": "<WORKSPACE>/secrets.local.json",
  "runtimeDataPath": "./data",
  "runtimeHomePath": "./runtime/copilot",
  "skillDirectories": ["<WORKSPACE>/agent/skills"],
  "ownerId": <OWNER_ID>,
  "ownerName": "<OWNER_NAME>",
  "quietHours": { "start": "01:00", "end": "09:30", "timezone": "<TIMEZONE>" },
  "permissionMode": "<manual|autopilot>",
  "coordinatorAgentId": "assistant",
  "bots": [
    { "id": "assistant-bot", "agentId": "assistant", "tokenRef": "telegram.assistant_bot_token" }
  ],
  "bindings": [
    { "botId": "assistant-bot", "chatId": <OWNER_ID>, "kind": "private", "topicId": null }
  ],
  "mcp": { "mode": "none" }
}
```

For `ENGINE=claude-code` also add
`"claudeCode": { "homePath": "./runtime/claude", "defaultModel": "claude-sonnet-5-5" }` and
`"engine": "claude-code"` to the bot entry.

The configuration is strict: unknown fields, wrong paths or an unresolved secret stop the
service with an explicit code. All fields are described in
[`docs/contracts.md`](docs/contracts.md); a fuller example is
[`config.example.json`](config.example.json).

**Check** (validates paths, agents and the secret reference; prints no secret):

```sh
node --input-type=module -e 'import { loadConfig } from "./dist/config/index.js"; try { const c = loadConfig("config.local.json", { codeRoot: process.cwd() }); console.log("OK", c.agents.map((a) => a.id)); } catch (e) { console.log("FAIL", e.code ?? e.message); }'
```

prints `OK [ 'assistant' ]`. A `FAIL <CODE>` names the problem (see
[common failures](#common-failures)).

## 11. Log in to the AI subscription

The service uses its **own** login, separate from the human's terminal tools.

- **Copilot.** Ask the human to run this in a terminal in `$CODE` (in Claude Code they can
  type `!` followed by the command) and finish the browser login:

  ```sh
  env -u COPILOT_GITHUB_TOKEN -u GH_TOKEN -u GITHUB_TOKEN \
    COPILOT_HOME="$PWD/runtime/copilot" COPILOT_AUTO_UPDATE=false \
    ./node_modules/@github/copilot-darwin-arm64/copilot login --web-flow
  ```

- **Claude Code.** Ask the human to run `make claude-login` in `$CODE` and finish the browser
  login.

Never copy an existing login and never read stored tokens.

**Copilot only — choose the model.** List the models this account may use:

```sh
node --input-type=module -e 'import { loadConfig } from "./dist/config/index.js"; import { pinnedRuntimePath, serviceClientOptions } from "./dist/agents/copilot.js"; import { CopilotClient } from "@github/copilot-sdk"; const client = new CopilotClient(serviceClientOptions(loadConfig("config.local.json", { codeRoot: process.cwd() }), await pinnedRuntimePath())); await client.start(); try { const auth = await client.getAuthStatus(); if (!auth.isAuthenticated) console.log("NOT_LOGGED_IN"); else for (const m of await client.listModels()) console.log(m.id); } finally { await client.stop(); }'
```

If the `model:` in `"$WORKSPACE"/.github/agents/assistant.agent.md` is not in the list,
STOP AND ASK which listed model to use (suggest a capable general model) and put it there.

**Check:** `make doctor` (next step) shows the login as ready.

## 12. Doctor

```sh
make doctor
```

It prints a JSON report — `ready` overall and a `checks` list of `{ component, ready, code }` —
and exits with code 2 while something is not ready.

**Check:**
- `authentication` → `AUTHENTICATED` and `models` → `MODELS_READY` (Copilot), or
  `claude-authentication` and `claude-models` ready (Claude Code);
- `bot:assistant-bot` ready;
- voice and module lines may be not ready: voice messages and modules are optional
  ([user guide](docs/user-guide/README.md)).

With `ENGINE=claude-code` and no Copilot login, the Copilot `authentication` line is
expected to be not ready, so the exit code stays 2; tell the human and continue.

## 13. Run in the background

STOP AND ASK: *"Everything is ready. May I install Densemble as a background service that
starts when you log in to your Mac? (You can stop it any time with `make stop`.)"*

```sh
make install
make start
make status
```

**Check:** `make status` shows the service loaded, and the log has a ready line for the bot:
`grep -h TG_BOT_READY data/logs/service.log | tail -1`.

If the human declined, run it in a terminal instead: `make run` (Ctrl+C stops it).

## 14. Final check: hello in Telegram

STOP AND ASK: *"Send 'Hi' to @<bot username> in Telegram. Did your agent answer?"*

**Check:** the agent introduces itself and answers. Installation is done. Tell the human:

- Talk to the agent in Telegram; `/help` lists the commands.
- To add agents or skills, ask the agent ("I want an agent for …"); it follows the
  `create-agent` and `create-skill` skills in the workspace.
- Restart after configuration changes: `make restart` in `$CODE`.
- Optional features — voice messages, recording transcription, reels — are in the
  [user guide](docs/user-guide/README.md) and the [developer guide](docs/development.md).

## Common failures

| Symptom | Cause and fix |
|---|---|
| `FAIL EXTERNAL_CANONICAL_SECRETS_REQUIRED` | `secretsPath` must point to a file named `secrets.local.json` outside this folder (in the workspace). |
| `FAIL SKILL_DIRECTORIES_INVALID` | `skillDirectories` must contain `<WORKSPACE>/agent/skills`, written exactly. |
| `FAIL LAUNCHER_ID_MISMATCH`, `CANONICAL_REFERENCE_MISMATCH`, `CANONICAL_WITHOUT_LAUNCHER` | The agent id differs between the launcher file name, its `name:`, the path inside it and the folder in `agent/agents/`. Make them identical. |
| `FAIL NO_AGENTS` | `agentLaunchersPath` has no `*.agent.md` files. |
| `FAIL CONFIG_SCHEMA_INVALID` | A typo, a missing value or an extra field in `config.local.json`; the schema is strict. Compare with step 10. |
| `FAIL CONFIG_JSON_UNREADABLE` | `config.local.json` is not valid JSON (often a trailing comma or a leftover `<placeholder>`). |
| `models` → `AGENT_MODEL_UNAVAILABLE` | The launcher's `model:` is not available on this account: step 11, choose the model. |
| `authentication` → `SERVICE_LOGIN_REQUIRED` | The service login (step 11) is missing; the terminal CLI's own login does not count. |
| The bot does not answer at all | Wrong `ownerId` or `chatId` (step 8), or the service is not running: `make status`, `make logs`. Messages from unconfigured people and chats are ignored on purpose. |
| `MODULE_NOT_FOUND … dist/main.js` in the logs | The build is missing: `make stop`, `npm ci`, `npm run build`, `make install`, `make start`. |
| `npm ci` fails on `better-sqlite3` or `sharp` | Command Line Tools are missing (`xcode-select --install`), or Node is not 24. |
