# Wiki split workspace

The [wiki workspace](../wiki-workspace/README.md), split into **two Git repositories**: one for
the knowledge, one for the agents. Start here if the knowledge and the agents should live
different lives:

- share the knowledge with your family or team, but keep the agents to yourself (or the other way
  round);
- reuse the same agents for several knowledge bases;
- review and roll back changes to agents separately from changes to knowledge.

If none of this matters to you, the plain [wiki workspace](../wiki-workspace/README.md) is
simpler.

```
AGENTS.md            ┐
raw/                 │  knowledge repository
current_context/     │  (raw/ is not in Git)
proposals/           │
wiki/                ┘
agent/               ── agents repository, ignored by the knowledge repository
  agents/glim/AGENT.md
  skills/
```

Densemble sees one workspace: the knowledge folder, with the agents inside it in `agent/`. Only
Git sees two repositories. The knowledge moves the same way as in the wiki workspace:

```
raw  ──process──▶  current_context  ──ready──▶  proposals  ──"yes"──▶  wiki
```

## Using it

Copy this folder somewhere outside the Densemble code, then create the two repositories:

```sh
cd my-knowledge          # your copy
git init                 # the knowledge repository (it ignores agent/)
cd agent && git init     # the agents repository
```

To share either one, give it its own remote. Do not make `agent/` a symlink: Densemble rejects
symlinked agent files. Configure Densemble exactly as for the wiki workspace: `workspacePath` is
your copy, `agentDefinitionsPath` its `agent/agents`, `skillDirectories` its `agent/skills`.
