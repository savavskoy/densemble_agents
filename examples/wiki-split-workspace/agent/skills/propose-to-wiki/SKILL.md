---
name: propose-to-wiki
description: Turn settled work from current_context (or a processed raw source) into a proposal for the wiki. Use when something is finished and worth keeping, or when someone asks to "add this to the wiki".
---

# Propose to the wiki

A proposal is a finished, self-contained piece of knowledge plus a plan for where it goes in
the wiki. It is not published until a person accepts it.

## 1. Check that it is ready

Do not propose:

- guesses, drafts or anything still under discussion — leave it in `current_context/`;
- facts already in the wiki — link to them instead;
- secrets, tokens or passwords.

If something is unclear, ask one question and wait.

## 2. Find where it belongs

Read [`wiki/INDEX.md`](../../../wiki/INDEX.md) and the pages it points to for this topic.
Decide for every fact: update an existing page, or create a new one. Prefer updating.

## 3. Write the proposal

Create `proposals/YYYY-MM-DD-short-name.md`:

```markdown
---
status: proposed
proposed-by: <person who asked for it>
date: YYYY-MM-DD
targets:
  - wiki/<existing-page>.md        # update
  - wiki/<new-page>.md             # new
sources:
  - current_context/<file>.md
  - raw/<file>                     # name only; raw is not in Git
---
# <What this adds, in one line>

## Why it matters
<One or two sentences.>

## Content
<The exact text to publish, grouped by target page.>
```

## 4. Ask for a decision

Tell the person in chat: what the proposal adds, which pages it touches, and who may accept it
(see "Who accepts a proposal" in `AGENTS.md`). Then stop. Do not publish it yourself.

On "yes", set `status: accepted` and follow [publish-proposal](../publish-proposal/SKILL.md).
On "no", set `status: rejected` and add one line with the reason; the person decides whether to
delete it.
