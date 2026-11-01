---
name: create-agent
description: Add a new persona (an agent the owner talks to through its own Telegram bot) to this workspace and Densemble. Use when the owner asks for a new agent, assistant or specialist.
---
# Creating an agent

A persona is an agent with its own role, tone and Telegram bot. It needs four things: a
definition, a launcher, a Telegram bot, and an entry in Densemble's configuration.

## 1. Agree on the role

With the owner, in a few lines: the agent's **id** (lowercase, digits, hyphens, e.g.
`fitness-coach`), display name, what it owns, what it must not do, and its tone. Check
`.github/agents/` so the role does not overlap an existing agent; if it does, extend that
agent instead.

## 2. Definition: `agent/agents/<id>/AGENT.md`

Sections: **Persona** (who, tone, how it addresses the owner), **Role** (what it owns and
what it hands to other agents), **Rules**, **Knowledge** (which `knowledge/` files it reads
and writes). Add an empty `memory.md` next to it. Link to knowledge files; do not copy facts.

## 3. Launcher: `.github/agents/<id>.agent.md`

```markdown
---
name: <id>
description: <one line: what this agent is for>
model: <a Copilot model id the owner has, same as the main agent's launcher>
---

Read and follow `agent/agents/<id>/AGENT.md` (after `AGENTS.md`).
```

The file name, `name:` and the folder in `agent/agents/` must all use the same id. Densemble
refuses to start if a launcher and its definition do not match.

## 4. Telegram bot and configuration (the owner, or their coding agent)

You cannot do this part from Telegram; give the owner these exact steps:

1. In Telegram, open **@BotFather** → `/newbot` → choose a name and a username ending in
   `bot`. BotFather replies with a token.
2. Put the token in the workspace's `secrets.local.json` under
   `telegram.<id>_bot_token` — in a file editor, never in a chat.
3. In Densemble's `config.local.json` add a bot and a private binding:

   ```json
   "bots": [ …, { "id": "<id>-bot", "agentId": "<id>", "tokenRef": "telegram.<id>_bot_token" } ],
   "bindings": [ …, { "botId": "<id>-bot", "chatId": <ownerId>, "kind": "private", "topicId": null } ]
   ```

   For the Claude Code engine add `"engine": "claude-code"` to the bot entry.
4. In the Densemble folder: `make restart`, then send `/start` to the new bot.

The owner can also open their coding agent (Copilot CLI, Claude Code, Codex) in the Densemble
folder and ask it to do step 4 by following this skill.

## 5. Done

The new agent greets the owner in its chat. Tell the owner in one line what it is for.
