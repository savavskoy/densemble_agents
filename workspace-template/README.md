# Workspace template

A starting point for your own Densemble workspace: your knowledge base and the home of your
agents. Do not use this folder directly — the installer ([`INSTALL.md`](../INSTALL.md))
copies it to a place you choose, outside the Densemble code folder.

What you get:

- [`AGENTS.md`](AGENTS.md) — shared rules every agent reads first.
- **assistant** — the main agent and coordinator
  ([`agent/agents/assistant/AGENT.md`](agent/agents/assistant/AGENT.md)), with its launcher in
  `.github/agents/`.
- Minimal skills in `agent/skills/`: `create-agent`, `create-skill`, `densemble-proactivity`.
- [`knowledge/profile.md`](knowledge/profile.md) — where your facts start.

Everything is plain Markdown. Copilot CLI, Claude Code and Codex read `AGENTS.md` too, so you
can work with the same agents and knowledge from your terminal.
