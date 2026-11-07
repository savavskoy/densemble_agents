# Wiki workspace

A Densemble workspace with a knowledge base that only accepts checked knowledge. Start here if
you (or your family, or your team) want the agents to keep a structured wiki rather than loose
notes. For the smallest possible start, see [simple-workspace](../simple-workspace/README.md).

```
AGENTS.md            shared rules and how knowledge moves
agent/               agents (Glim) and skills
raw/                 unprocessed sources; not in Git
current_context/     work in progress
proposals/           finished pieces waiting for a "yes"
wiki/                checked knowledge; INDEX.md is the entry point
```

## The path of a piece of knowledge

```
raw  ──process──▶  current_context  ──ready──▶  proposals  ──"yes"──▶  wiki
```

A recording lands in `raw/`. An agent processes it into notes in `current_context/` while the
work is going on. When something has settled, the agent writes it up as a proposal. A person
accepts it, and only then the agent merges it into the wiki, keeping every fact in one place.
Unfinished material never reaches the wiki.

## Using it

Copy this folder somewhere outside the Densemble code and make it yours; a Git repository is
recommended so the wiki has history. Point `workspacePath` at your copy, `agentDefinitionsPath`
at its `agent/agents`, `skillDirectories` at its `agent/skills`, and bind a bot to the `glim`
agent. Check that the model in `agent/agents/glim/AGENT.md` is available to your engine; `/model`
lists the choices.
