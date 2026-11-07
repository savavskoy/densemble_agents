# Simple workspace

A starting point for your own Densemble workspace: the folder your agents live and work in.
Copy it somewhere outside the Densemble code (for example
`~/densemble-home/workspaces/personal`) and make it yours. It is plain Markdown; a Git
repository is optional. If you want the agents to keep a structured wiki that only accepts
checked knowledge, start from [wiki-workspace](../wiki-workspace/README.md) instead.

```
AGENTS.md                         shared rules every agent reads first
people/                           one profile per person; Glim fills it in on first contact
agent/agents/glim/AGENT.md        Glim, your personal assistant
agent/skills/create-agent/        how to add your own agents
```

**Glim** is the amber dot from the Densemble sign, the first inhabitant of the den. On your
first chat he greets you, learns how to address you and shows how things work. After that he
is your personal assistant and takes on whatever you ask. When one kind of work grows too big
for one assistant, Glim suggests a specialist agent and explains why. Switch off the story
("plain mode") if you prefer, or let Glim go: his `AGENT.md` says how.

Point `workspacePath` at your copy, `agentDefinitionsPath` at its `agent/agents`,
`skillDirectories` at its `agent/skills`, and bind a bot to the `glim` agent. No
`agentLaunchersPath` is needed: each `AGENT.md` declares its own name and model in its
frontmatter. Check that the model there is available to your engine; `/model` lists the
choices.
