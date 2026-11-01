# Workspace instructions

This folder is the owner's personal workspace: their knowledge base and the home of their
AI agents. Every agent that works here (in Telegram through Densemble, or in Copilot CLI,
Claude Code or Codex) reads this file first.

## Layout

- `knowledge/` — the owner's facts, notes and documents, in plain Markdown.
  [`knowledge/profile.md`](knowledge/profile.md) is the starting point.
- `agent/agents/<id>/AGENT.md` — one persona per folder: who the agent is, what it owns,
  how it talks. Its `memory.md` holds only what that agent itself needs to remember.
- `.github/agents/<id>.agent.md` — the launcher for each persona (name, description,
  default model) that points to its `AGENT.md`.
- `agent/skills/<name>/SKILL.md` — reusable "how to" instructions for a class of tasks.
- `secrets.local.json` — credentials (bot tokens and similar). Local only, never committed,
  never read aloud, never pasted into chat.

## Agents

- Unless a specific agent was selected, act as the main agent:
  [`agent/agents/assistant/AGENT.md`](agent/agents/assistant/AGENT.md).
- To add a persona, follow the [`create-agent`](agent/skills/create-agent/SKILL.md) skill;
  to add a skill, the [`create-skill`](agent/skills/create-skill/SKILL.md) skill.
- Before your first answer in a new conversation, say in one line which agent is speaking.

## Working with knowledge

- Golden rule: every fact lives in one file; everything else links to it.
- Save durable facts, decisions and preferences the owner states explicitly in the most
  relevant existing file under `knowledge/`; create a new file only when nothing fits.
  Replace outdated facts in place. After saving, say which file changed.
- Do not save chat transcripts, raw prompts or temporary to-dos.
- Do not turn a guess about the owner's preferences into a rule; ask first.
- Keep the language of each existing note; do not translate notes unless asked.

## Safety

- Credentials live only in `secrets.local.json`. Never put them in other files, messages,
  examples or logs.
- Stay inside this workspace unless the owner explicitly asks otherwise.
- Ask before anything hard to undo or visible to other people: deleting files, sending
  messages or e-mail, spending money, publishing.
- If this folder is a git repository, do not commit or push unless the owner asks.

## Language

Reply in the language the owner is writing in.
