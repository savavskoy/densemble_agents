---
name: publish-proposal
description: Publish an accepted proposal from proposals/ into the wiki — merge its content into the right pages, keep one fact in one place, update the index. Use only after a person has accepted the proposal.
---

# Publish a proposal

## 1. Check the decision

Open the proposal. Publish only if `status: accepted` and the person who accepted it may do so
(see "Who accepts a proposal" in `AGENTS.md`). Otherwise stop and say why.

## 2. Merge into the wiki

For every target page in the proposal:

- **Existing page:** merge the new facts into the right section. Replace outdated facts instead
  of adding a second version. Keep the page's language and style.
- **New page:** create it under the right folder of `wiki/`, start it with a `# Title` and a
  one-line summary.
- If a fact already lives on another page, link to it instead of repeating it.
- Use relative Markdown links and check that every link points to a file that exists.

If the wiki has changed since the proposal was written and the content no longer fits, stop and
ask instead of guessing.

## 3. Update the index

Add every new page to [`wiki/INDEX.md`](../../../wiki/INDEX.md) with a one-line description.
Fix descriptions of pages whose meaning changed.

## 4. Clean up

- Delete the proposal file; Git keeps its history.
- Remove or shorten the notes in `current_context/` that the proposal settled, so the same
  thing does not live in two places. Ask first if they are someone else's notes.
- Tell the person which pages changed, in one short list.
