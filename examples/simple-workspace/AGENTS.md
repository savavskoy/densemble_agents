# Shared agent instructions

This folder is a Densemble workspace: the den. It holds the owner's knowledge and the
definitions of the agents who work here. Every agent reads this file first.

## Agents

- Each agent is one file, `agent/agents/<id>/AGENT.md`: its frontmatter names the agent and its
  model, the rest is its instructions. Read and follow your own `AGENT.md`.
- The default agent is **Glim**, the owner's personal assistant: [`agent/agents/glim/AGENT.md`](agent/agents/glim/AGENT.md).
- New agents are created with the [create-agent](agent/skills/create-agent/SKILL.md) skill.

## Knowledge

- [`people/`](people/README.md) — one profile per person: how to address them, which language to
  use. At the start of every conversation read the profile of the person you are talking to.
- Put durable facts in a topic folder next to `people/`. Every fact lives in one file;
  everything else links to it. Do not save chat transcripts or temporary tasks.
- Preserve the language of existing notes.

## Skills

A skill is instructions for a model: **when** to use it (triggers), **how** (steps, commands) and
**what to avoid** (gotchas, rules). Agents decide; skills explain how.

- One folder per skill: `agent/skills/<kebab-name>/SKILL.md`, starting with frontmatter: `name`
  and a `description` of what it covers and when to load it. Supporting files (examples,
  templates) may sit next to it.
- A skill is a file. When a task matches a skill linked from your instructions, read its
  `SKILL.md` first and follow it; never invent steps it does not document. If you hit a new
  gotcha while using it, add it there.
- Where a skill is linked: one that every agent uses is linked from this file; one used by a
  single agent, or by some but not all, only from those agents' `AGENT.md` ("Skills" section).
  Link it, never copy its steps into instructions.
- Skills hold no personal knowledge (that lives in the knowledge folders, linked) and no secrets.

## Rules for everyone in the den

- The owner decides. Propose, then wait for an explicit "yes" before anything hard to undo.
- Secrets live only in the secrets file outside this workspace. Never write them into notes, and
  never ask for them in chat.
- Stay inside this workspace unless the owner asks otherwise.
- Do not run git commands that change state (commit, push, reset) unless the owner asks.
- Mirror the owner's language.
