# Shared agent instructions

This folder is a Densemble workspace: the den. It holds the agents who work here and a
knowledge base that grows in one direction only, from raw material to a checked wiki. Every
agent reads this file first.

## Agents

- Each agent is one file, `agent/agents/<id>/AGENT.md`: its frontmatter names the agent and its
  model, the rest is its instructions. Read and follow your own `AGENT.md`.
- The default agent is **Glim**, the owner's personal assistant: [`agent/agents/glim/AGENT.md`](agent/agents/glim/AGENT.md).
- New agents are created with the [create-agent](agent/skills/create-agent/SKILL.md) skill.

## Where things live

| Folder | What it holds | In Git |
|---|---|---|
| `agent/` | agents and skills | yes |
| `raw/` | unprocessed sources: recordings, transcripts, documents, exports | **no** |
| `current_context/` | what is being worked on now: focus, decisions in progress, open questions | yes |
| `proposals/` | finished pieces waiting to enter the wiki, one file each | yes |
| `wiki/` | checked, structured knowledge; entry point [`wiki/INDEX.md`](wiki/INDEX.md) | yes |

Every person has a profile in [`wiki/people/`](wiki/people/README.md) (form of address,
language). At the start of every conversation read the profile of the person you are talking to.

## How knowledge moves

```
raw  ──process──▶  current_context  ──ready──▶  proposals  ──"yes"──▶  wiki
```

1. **raw** — open it only when someone asks you to process a specific source. Never change or
   delete originals. It is ignored by Git, so it may hold large and private files.
2. **current_context** — working notes. They may be incomplete or wrong, and they change.
   Write here freely while a task is in progress.
3. **proposals** — when something in progress has settled and is worth keeping, write it up as
   a proposal with the [propose-to-wiki](agent/skills/propose-to-wiki/SKILL.md) skill. Then
   stop: a proposal waits for a person's decision.
4. **wiki** — only an accepted proposal enters the wiki, through the
   [publish-proposal](agent/skills/publish-proposal/SKILL.md) skill.

**Nobody writes to `wiki/` directly**, with one exception: when a person explicitly tells you
to record a fact about themselves ("call me Sam", "I prefer English"), that instruction is the
acceptance; update their own profile in `wiki/people/` and say so.

### Who accepts a proposal

- In a private workspace: the owner.
- In a shared workspace: any member except the one who asked for the proposal.
- An agent never accepts its own or another agent's proposal.

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

- Read `wiki/INDEX.md` and then only the pages the request needs; do not load the whole wiki.
- Every fact lives in one wiki page; everything else links to it.
- The owner decides. Propose, then wait for an explicit "yes" before anything hard to undo.
- Secrets live only in the secrets file outside this workspace. Never write them into notes, and
  never ask for them in chat.
- Stay inside this workspace unless the owner asks otherwise.
- Do not run git commands that change state (commit, push, reset) unless the owner asks.
- Mirror the owner's language. Preserve the language of existing notes.
