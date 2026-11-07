---
name: create-agent
description: Create a new Densemble agent (persona) in this workspace and tell the owner how to give it a Telegram bot. Use when the owner wants a new specialist, or to rename or retire one.
---

# Create an agent

## 1. Agree on the agent

Ask the owner, one question at a time, and skip what they already said:

- what the agent is for, and what it must **not** do;
- a name and character (any look: a person, a creature, an object, a spark);
- which files or topic folder it should read and write.

Propose a short `id` (lowercase letters, digits, dashes, e.g. `money-owl`) and wait for a "yes".

## 2. Write `agent/agents/<id>/AGENT.md`

One file per agent. The frontmatter is required: without it Densemble refuses to start.

```markdown
---
name: <id>
description: <One sentence: who they are and when to pick them.>
model: <same model as Glim's unless the owner wants another>
---
# <Name> — <role in a few words>

## Who <Name> is
<Character, look, how they talk.>

## Domain
<What they do. What is not theirs.>

## Knowledge
<Files and folders they read and write.>

## Skills
<Links to the SKILL.md files this agent uses that are not already linked from AGENTS.md.>
```

`name` must equal the folder name. Links inside `AGENT.md` must point to files that exist in
this workspace. Skills follow the rules in the "Skills" section of `AGENTS.md`: link a skill
only this agent uses from its own `AGENT.md`, and one every agent uses from `AGENTS.md`.

## 3. Hand the rest to the owner

You cannot change Densemble's configuration. Tell the owner exactly what to do:

1. Create a bot in Telegram with @BotFather and copy its token.
2. Add the token to the secrets file under a new key, e.g. `telegram.<id>_bot_token`. Do not
   paste it into this chat.
3. In `config.local.json` add a `bots` entry (`id`, `agentId: "<id>"`, `tokenRef`) and a private
   `bindings` entry for their own chat with that bot.
4. Restart Densemble and send `/start` to the new bot.

## Rename or retire

- Rename: change the folder and `name` together, then the `agentId` in `config.local.json`.
- Retire: delete the folder, remove the bot and binding from `config.local.json`, restart.
