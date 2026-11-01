---
name: create-skill
description: Create or update a reusable skill (how-to instructions for a class of tasks) in this workspace. Use when the owner asks to teach an agent how to do something repeatedly, or a procedure keeps being explained again.
---
# Creating a skill

A skill is a folder `agent/skills/<name>/` with a `SKILL.md`. Agents see each skill's
`description` and load the full text when a task matches it. All agents in this workspace
share the same skills.

## Steps

1. **Agree on the job.** In one or two lines with the owner: what task the skill covers,
   when it should trigger, and what a good result looks like. Check that no existing skill in
   `agent/skills/` already covers it; if one does, update it instead.
2. **Pick a name:** lowercase, digits and hyphens, describing the task (`weekly-review`,
   `meeting-notes`). The folder name and the `name:` field must match.
3. **Write `agent/skills/<name>/SKILL.md`:**

   ```markdown
   ---
   name: <name>
   description: <what it does>. Use when <the situations that should trigger it>.
   ---
   # <Title>

   ## Steps
   1. …

   ## Rules
   - …
   ```

   - The `description` decides when the skill is used: say what it does and when to use it.
   - Write steps an agent can follow without guessing: inputs, where files live, what to
     check, when to stop and ask the owner.
   - Link to knowledge files instead of copying facts into the skill.
   - Never put secrets in a skill; refer to keys in `secrets.local.json` by name.
4. **Helper files** (templates, small scripts) go next to `SKILL.md` in the same folder.
5. **Activate:** skills load when a session starts — tell the owner to send `/new` in
   Telegram. If it still does not appear, Densemble needs `make restart`.
6. Tell the owner in one line what the skill does and how to trigger it.
