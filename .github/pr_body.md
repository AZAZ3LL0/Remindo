Closes the roadmap item **S8. Тихие часы и автоповтор** (`tech.md` §15).

Opens #14 (`contract-change`): two lines of §7.3 and §7.4 disagree with §1.1, and the slice ships the fix on a local stub. `tech.md` is untouched, the core stays at v6.

## What the slice does

`apply_quiet_hours` already moved a *planned* moment out of the silence. Every other way a delivery entered the queue walked straight back into it.

- **Snooze** computed `now + snooze_minutes` and queued it. Ten more minutes at 22:55 answered at 23:05, inside the silence the user had just configured. It now lands at the end of the silence, and `snoozed_until` carries that moment, so the answer on screen tells the truth.
- **The automatic repeat** queued `now`. It now obeys the same silence, and a repeat the silence would push past `occurrence.expires_at` is dropped rather than deferred: its buttons would be dead on arrival, and the sweep expires the occurrence anyway.
- **A snooze the silence would push past the TTL** falls back to the requested moment. Late beats lost (§1.1).
- **Quiet hours are read from the user**, not from `reminders.timezone`. That column is a snapshot taken at creation (§4.2), so a user who moved was being silenced against the wall clock of the city they left.
- **Expiry** re-checks in the domain that the occurrence is not already answered, so a `done` occurrence is never overwritten with silence.

## Bug found and fixed

`repeats_sent` lives on the occurrence, but the reaper bumped it once per delivery. A shared reminder handed the same occurrence back for every recipient, so one sweep burned the whole repeat budget. The budget is now read once per sweep and spent once.

## Contracts and types

No schema change, no migration, no new callback data, no new text keys.

Two new modules: `app/domain/sweeping.py` (`RepeatPlan`, `decide_repeat`, `is_overdue`) and `app/services/recipients.py` (`quiet_hours_of`). `app/domain/quiet_hours.py` gains the `QuietHours` value object; `app/domain/reactions.py` gains `postpone`, and `decide_reaction` now takes the silence and the TTL.

## Tests

- **Contract** — `tests/contract/test_reaper_contract.py`: the expiry edit passes `FakeBotGateway`, the repeat hands the queue an aware moment, and both halves of the lifecycle agree on what `expired` means.
- **Idempotency** — sweeping twice expires once, writes one `auto_expire` and edits one message; the repeat budget holds across sweeps and across recipients.
- **Error path** — `TelegramForbiddenError` and `TelegramRetryAfter` on the expiry edit: the occurrence still expires and the action is still written.
- **Property-based** — `tests/unit/test_sweeping.py` on `decide_repeat` and `is_overdue`, plus new invariants on `postpone` and `QuietHours`, including the ambiguous local hour on the autumn transition in `Europe/Berlin`.
- **End to end** — `tests/e2e/test_quiet_hours_slice.py`: silence the night, create a 03:00 reminder, watch it stay quiet at 03:00, arrive at 07:00, repeat once, expire, and refuse a tap afterwards.
