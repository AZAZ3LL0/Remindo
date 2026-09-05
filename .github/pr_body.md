Bumps the core to **v8** and adds §21, the contract of the roadmap item **S9. Управление напоминаниями** (`tech.md` §15). No slice code here: the slice ships in its own PR on top of this one.

S9 had no contract at all. Six things were missing, and the gap block naming them is in the session that opened this PR.

## What the contract decides

- **The list needs a filter that survives pagination.** `PageCb` carries a page and nothing else, and packing a category into `scope` is forbidden by §6. The list screen gets its own factory, `ListCb` (prefix `l`), with `category_id = 0` meaning "every category": BIGSERIAL starts at one, so zero can never collide with a real row. `paginated_kb` §9 takes one optional `nav` builder so the arrows can be `ListCb`; every existing caller is untouched.
- **Editing needs a screen.** `RemCb(action="edit")` led nowhere. `EditCb` (prefix `e`) names the field about to change and carries no value: the value arrives on the next screen through `WizCb`, the way category creation already does (§17.1). Opening the filter picker is a `WizCb` atom too, because opening a picker is a command, not a page.
- **Pausing has to stop delivery.** The planner only materialises `active` reminders, but occurrences already in the queue kept going out. §21.3 says leaving `active`, and any schedule edit, drops `pending` occurrences nothing has been sent for, clears `planned_until` and gives back the `fired_count` those rows had spent. Already `sent` occurrences are left alone: their buttons are live on the user's screen, and a pause has no business taking them away.
- **Snooze and repeat get limits.** §18.7 and §20.8 both deferred their screens to S9 without naming bounds. `SNOOZE_*` and `REPEAT_*` land in `domain/contracts.py`, a day at the top like an interval, five minutes at the bottom of a repeat because a repeat faster than a sweep never happens.
- **The card gets a schedule and a note.** It is the screen where the user decides what to change, and neither was visible on it. `reminder.card` gains `{schedule}` and `{note}`, `list.item` gains `{mark}` so a paused row does not read as an active one, and five `schedule.*` keys state a schedule as a fact rather than asking the wizard's question.
- **Cancelling a delete returns to the card.** `confirm_kb("delete", ...)` sends cancel to `RemCb(action="open")` instead of the shared atom: unlike creation and category archiving, deletion has somewhere to go back to. The `create` and `archive` branches are unchanged.

## Contracts and types

New: `ListCb`, `EditCb`, `NO_CATEGORY_FILTER`, four `SNOOZE_*`/`REPEAT_*` limits, `app/bot/keyboards/reminders.py` with seven screens, `render_schedule_summary`, and the §21.7 text keys in both locales.

Changed: `paginated_kb` gains a keyword-only `nav`, `confirm_kb` changes only its `delete` branch, `render_reminder_card` and `render_reminder_list` fill the new placeholders. No schema change, no migration, no enum value, no renamed prefix.

## Tests

`tests/contract/test_callbacks.py` covers both new factories: round trip, 64 bytes at maximal values, the frozen prefix order, and that `0` can never be a real category. The text contract test already holds every new key to both locales and a matching placeholder set. `make lint`, `make typecheck` and `make test` are green (1308 passed, coverage 97%).
