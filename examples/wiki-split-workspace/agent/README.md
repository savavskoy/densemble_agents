# Agents

This folder is a **separate Git repository**: the agents and skills of this workspace. The
knowledge around it (`wiki/`, `current_context/`, `proposals/`) is another repository that
ignores this folder.

```
agents/<id>/AGENT.md     one file per agent: frontmatter (name, model) + instructions
skills/<name>/SKILL.md   how-to instructions the agents share
```

Change the agents here and commit here; their history stays apart from the knowledge. The same
agents can be copied into another knowledge base, and the knowledge can be shared with people
who never see these files.
