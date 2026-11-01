# Densemble

> **Your AI team in Telegram — on the subscription you already pay for, with knowledge you own.**

**Status: experimental early access.** macOS on Apple Silicon only. No support is promised;
issues are welcome. Setup takes 30–90 minutes, guided by your own coding agent.

Densemble runs on your Mac and connects AI agents to Telegram. Each agent has its own
persona, its own bot and its own chat, and they all work in one folder you own: your
knowledge base in plain Markdown.

## Why

- **Subscription, not API billing.** Agents run on GitHub Copilot or Claude Code (Claude
  Pro/Max) — a flat monthly subscription instead of pay-per-call API keys.
- **A team, not one assistant.** Several personas with roles, one Telegram bot each. Start
  with one main agent and add more when you need them.
- **Your knowledge stays yours.** Everything is Markdown in your own folder (git if you
  like). `AGENTS.md` is read by Copilot CLI, Claude Code and Codex too, so nothing is locked in.
- **Safe by design.** No HTTP server, nothing exposed to the internet. Only you (and people
  you explicitly add) can talk to your bots.

## Who it is for

Developers and tinkerers who already use Copilot CLI, Claude Code or Codex and want an agent
team for their life and work, reachable from the phone.

## Requirements

- A Mac with Apple Silicon (M1 or newer)
- Node.js 24 (the installer helps you get it)
- A GitHub Copilot subscription or a Claude Pro/Max subscription
- Telegram

## Install

Read [`INSTALL.md`](INSTALL.md) first: it is a runbook your coding agent will follow, and it
will run commands on your Mac. Then:

```sh
git clone <this repository> densemble
cd densemble
```

Open Claude Code, Copilot CLI or Codex in that folder and say:

> Read INSTALL.md and install and run Densemble for me.

The agent does the technical work. You create a Telegram bot in @BotFather, log in to your
subscription in the browser, and answer a few questions. At the end your main agent says
hello in Telegram.

## What you get

- A workspace folder (from [`workspace-template/`](workspace-template/)) with one main agent,
  the **assistant**, who coordinates the team and helps you add agents and skills.
- Telegram commands: `/help`, `/status`, `/model`, `/new`, `/sessions`, `/workspace`,
  `/stop`, `/proactive`.
- Agents that can remind you and check in on their own, within quiet hours you set.
- Optional: voice messages (local transcription), recording transcription, reels from long
  videos — see the [user guide](docs/user-guide/README.md).

## Documentation

- [User guide](docs/user-guide/README.md)
- [Developer guide](docs/development.md): architecture, configuration, background service,
  backups, tests
- [Contracts](docs/contracts.md): configuration schema and behaviour in detail

## Be aware

- You let an AI agent run commands from a downloaded repository. Read `INSTALL.md` before
  you do.
- The runbook is followed by a language model, so the experience varies between models.
- Densemble relies on the terms of your AI subscription; check them for your use.

## License

[MIT](LICENSE)
