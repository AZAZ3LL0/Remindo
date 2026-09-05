Closes the roadmap item **S9. Управление напоминаниями** (`tech.md` §15).

Builds on the v8 contract PR and targets its branch; merge that one first.

## What the slice does

`/list` existed and could do nothing but page. Everything a reminder needs after it is created was missing.

- **`/list` filters by category.** The filter travels with the arrows through `ListCb`, so it survives paging. A paused reminder is marked in the list, because an unmarked row reads as an active one.
- **The card** states the schedule, the note, the snooze step and the repeat, not just the title and the next moment. It is the screen where the user decides what to change, so it has to show what there is to change. Its next-fire line reads from the queue and falls back to the schedule while the planner has not caught up.
- **Pause and resume.** Only the button that changes something is drawn.
- **Editing** covers title, note, category, schedule, snooze step and automatic repeat, one field per screen. The category question reuses the shared picker and the schedule question re-enters the wizard of S3: the questions are the same ones, and a second copy of them would be a second copy to keep in step. The reminder id in FSM data is what tells the wizard's confirmation to update rather than create.
- **Deleting asks first**, and cancelling comes back to the card rather than to a dead end.
- **`/today`** lists the deliveries addressed to the user inside their own local day, marked done, skipped, missed or still waiting.

## The bug the slice had to fix

The planner only materialises `active` reminders, so pausing stopped the planner. It did not stop the queue: occurrences already materialised stayed `pending`, and the dispatcher went on sending them. A pause that still delivers is not a pause.

Leaving `active`, and any schedule edit, now takes back the `pending` occurrences nothing has gone out for, clears `planned_until` and gives back the `fired_count` those rows had spent. Already `sent` occurrences are left alone: their buttons are live on somebody's screen, and neither a pause nor an edit has the right to take them away. A `snoozed` delivery is left alone for the same reason — the user asked for it later.

## Contracts and types

No schema change, no migration. Everything the slice needs was fixed in the v8 contract PR; the only core file touched here is `texts.py`, for the string that says why a note was refused.

New: `app/services/today.py` (`TodayService`, `TodayEntry`), `app/bot/fsm/reminder_edit.py`, `app/bot/render/today.py`, `app/bot/handlers/manage.py`. `domain/reminders.py` gains `parse_user_snooze`, `parse_user_repeat` and `local_day_bounds`. `RemindersService` gains `get_editable`, `update` and the queue rollback; the repositories gain `delete_unsent`, `reset_planning` and the two day queries.

## Tests

- **Contract** — `tests/contract/test_manage_contract.py`: every screen passes `FakeBotGateway`, the new atoms round-trip inside 64 bytes, no preset collides with `man`/`off`/`clear`, no preset falls outside the domain limits, the arrows carry the filter, the card offers exactly one of pause and resume, the edit menu and the contract list the same fields, and every schedule kind and every delivery status has a string to render with.
- **Idempotency** — pausing twice takes the same rows back once and leaves `fired_count` where the first press left it; confirming a delete twice removes one reminder and answers the second press with "not found".
- **Error path** — `message is not modified` on a redraw is the expected outcome; `TelegramRetryAfter` and `TelegramForbiddenError` on the redraw leave the committed change in place and do not let the press be replayed into a second effect.
- **Property-based** — `local_day_bounds` over the DST zone set of §19.6: half-open, UTC-aware, both ends inside the day they name, 23 to 25 hours long, consecutive days meeting without a gap, and every real transition day covering its own midnight. Plus the bounds of the two new parsers, including that `0` is not a way to turn the repeat off.
- **Integration** — `tests/integration/test_manage.py`: what the pause takes back and what it must not, the schedule swap, the refused schedule leaving the row alone, the untouched timezone snapshot, the category gates, and `/today` answering in the asker's timezone.
- **End to end** — `tests/e2e/test_manage_slice.py`: create, list, filter, open, pause, resume, edit each field, re-ask the schedule through the wizard, delete with confirmation, and read the day.

`make lint`, `make typecheck` and `make test` are green: 1425 passed, coverage 97%.
