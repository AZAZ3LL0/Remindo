Closes the roadmap item **S11. Статистика** (`tech.md` §15).

Builds on the v10 contract PR (#21), which is already in `main`.

## What the slice does

`delivery_actions` had been filling up since S6 and nobody could read it. `/stats` existed as a skeleton that printed one streak and two percentages, and the roadmap asked for a streak *per category* and a weekly digest that did not exist at all.

- **`/stats` now answers per category.** The screen leads with the whole picture — current streak, best streak, seven and thirty day completion — then breaks it down, one row per category the user has actually reacted in. Each row is a button into that category's own card, and the card leads back. The rows are the drill-in, so there is no filter picker: a screen already listing the categories does not need a second screen listing them again.
- **The weekly digest**, a fourth worker cycle next to the planner, the dispatcher and the reaper. Monday 09:00 in the *recipient's* timezone, one message, no buttons: the week's completions, the streak, and what each category contributed.
- **A switch to turn it off**, on the settings screen, because a weekly message you cannot stop is a defect.

## The three decisions the cycle turns on

**The idempotency key is the weekly moment, not the send.** `users.digest_sent_at` stores the Monday 09:00 the digest covered, never the instant it went out. The send drifts — the cycle wakes every minute, quiet hours postpone it, a `RetryAfter` postpones it again — and a stored `now` would have to be compared against the start of a week by arithmetic. Running the cycle twice sends one message; running it sixty times an hour for the rest of the week sends none.

**A week is seven local days, not 168 hours.** `digest_window` counts on the wall clock, so a DST transition inside the week makes it an hour shorter or longer and the digest still arrives at 09:00. Adjacent windows abut exactly, which is what lets the mark of one week be the start of the next.

**Quiet hours reach the digest.** §20.1 named three paths that assign a delivery moment afresh; this is the fourth, and the retry exception does not carry over — a digest has no TTL to expire against while the silence lasts, so postponing it loses nothing. The shift delays the send and never renames the week: what gets stored is the unshifted moment, or a silence ending after midnight would pass two digests off as one.

## Statistics read the journal

The queue was never a candidate. A pause (§21.3) and an unsubscribe (§22.6) delete `pending` rows, so a completion rate computed from `deliveries` would move retroactively when somebody presses Pause. `delivery_actions` is append-only, and a snooze is deliberately not an outcome: it postpones a reminder rather than resolving it, and in the denominator it would turn postponing into failing.

The breakdown joins through to `reminders.category_id` at query time rather than freezing the category into the journal, so editing a reminder's category carries its whole history with it instead of tearing a streak in half. The category rides along with each row in one query: a month of history would otherwise cost one query per reaction.

A row whose category is gone is dropped rather than drawn blank — it has nothing to be labelled with, and a button opening a card that cannot be rendered is worse than no button.

## Contracts and types

No schema change and no core file touched here: `StatCb`, `JobId.DIGEST_SEND`, the two `users` columns, the `DIGEST_*` settings, the stats keyboards and the text keys all landed in the v10 contract PR.

New: `app/domain/digest.py` (`DigestWindow`, `last_digest_moment`, `digest_window`, `digest_due_at`), `app/services/digest.py` (`DigestService`, `DigestResult`), `app/worker/digest.py`.

`app/domain/stats.py` gains `CategoryStats`, `StatsSummary.by_category` and `ActionRecord.category_id`; `StatsService` gains `summary_at` and `summary_for`, because the digest asks for a past moment rather than for `now` — a summary pinned to the send would report a different week on every retry. `UsersRepository` gains the candidate query and the mark, `CategoriesRepository` gains `list_by_ids`, and `DeliveriesRepository.list_actions_for_user` returns the category and accepts an upper bound.

The domain reads no clock and no configuration: `digest_due_at` takes `now`, the weekday, the hour and the mark as arguments, so a digest is reproducible in a test without patching anything.

## Tests

- **Contract** — `tests/contract/test_stats_contract.py`: every screen passes `FakeBotGateway`, `StatCb` round-trips inside 64 bytes at full size, the breakdown pages with its own factory and its arrows stay on the whole picture, the last page hides its forward arrow, the card returns to every category, the digest switch offers the side it would set and its atoms collide with no timezone or language code, the digest message carries no keyboard, and its title names the same week its idempotency key does.
- **Idempotency** — `tests/integration/test_digest.py`: two cycles send one digest; a tick three days later sends nothing; the next week is owed again; an empty week is marked but not sent; and the mark survives a blocked chat.
- **Error path** — `TelegramForbiddenError` blocks the user and closes the week, `TelegramBadRequest` closes it without a retry, and `TelegramRetryAfter` leaves it owed so the next tick delivers it. One failure does not cost the rest of the batch their week: each user commits on their own.
- **Property-based** — `tests/unit/test_digest.py` over `domain/digest.py`: the moment is never in the future, always lands on the configured local weekday, keeps its local hour unless that hour does not exist, and consecutive moments are one *local* week apart; windows of adjacent weeks abut exactly; a due digest is always the unshifted moment; a marked week is never owed again; and silence only ever postpones. Checked across the DST zone set of §19.6. `tests/unit/test_stats.py` adds the breakdown invariants: the parts add up to the whole, a category streak never beats the total, the breakdown is ordered and holds only categories with outcomes, and journal order changes nothing.
- **End to end** — `tests/e2e/test_stats_slice.py`: real routers from `/start` through two reminders in two categories, three answers, `/stats` showing both categories and 67%, a drill-in and back, the digest cycle delivering once to the chat, and the switch stopping it without marking the week.
