---
name: densemble-proactivity
description: Schedule, list, pause or cancel your own reminders and check-ins in Telegram with the densemble_manage_proactivity tool. Use when the owner asks to be reminded, wants a regular check-in, or when a reminder would clearly help.
---
# Proactivity in Densemble

Densemble lets each agent write first in its own Telegram chat: one-off reminders, regular
check-ins and silent checks. You manage only your own items, in the current chat.

## When to speak up

- **Default is silence.** Write first only when not acting has a real cost: another person,
  money, health, a commitment or a deadline. Low-stakes items get no nagging.
- **Remind once.** Remind again, closer and sharper, only if the item matters and is not moving.
- **Learn only from the owner's explicit words** ("stop reminding me about this", "remind me
  again"). Silence is not an answer. Note such reactions in your `memory.md`.
- **Bundle, don't spam.** Densemble respects quiet hours and merges items due at the same time.
- When you set up a recurring item on your own initiative, tell the owner and how to cancel it.

## The tool: `densemble_manage_proactivity`

| `action` | Other fields | What it does |
|---|---|---|
| `schedule` | `kind`, `schedule`, `purpose` | Creates an item |
| `list` | — | Your active and paused items in this chat |
| `cancel` | `id` | Cancels one of your items |
| `pause` / `resume` | — | Pauses or resumes all your items in this chat |

`kind`:
- `oneoff` — a single reminder; needs `schedule: { "type": "once", "at": <epoch ms> }`.
- `recurring` — a regular check-in that always writes.
- `silent` — a regular check that writes only when there is something worth saying.

Repeating schedules:
- `{ "type": "weekly", "daysOfWeek": [1, 4], "hour": 9, "minute": 30 }` (0 = Sunday)
- `{ "type": "monthly", "daysOfMonth": [1], "hour": 10, "minute": 0 }`
- `{ "type": "interval", "everyMs": 86400000 }` (there is a minimum interval)

`purpose` is the note your future self receives when the item fires: write what to check or
say and why, in one or two sentences.

## Steps

1. `list` first, so you do not create a duplicate.
2. Choose the kind and schedule; times are in the owner's configured timezone.
3. `schedule`, then confirm to the owner in one line what will happen and when.
4. If a result has `ok: false`, tell the owner its `message`; do not retry blindly.
5. When the owner says an item is no longer needed, `cancel` it.
