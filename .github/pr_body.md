Bumps the core to **v10** and appends §23, the contract of **S11. Статистика** (`tech.md` §15). Contract change only: it defines what the slice may build and ships the shared files it needs. The slice itself follows in its own PR.

## What §23 settles

**Where the numbers come from.** Statistics read `delivery_actions` and nothing else. The queue is not a source: a pause (§21.3) and an unsubscribe (§22.6) delete rows that never went out, so a completion rate computed from `deliveries` would change retroactively when somebody presses Pause. An outcome is `done | skip | auto_expire`; a snooze postpones a reminder rather than resolving it, and counting it in the denominator would turn postponing into failing.

**Whose they are.** A journal row is addressed to `delivery_actions.user_id`, so a watcher (§22.11) has their own streak on a shared reminder and the owner never sees it as theirs.

**Which category.** The breakdown joins through to `reminders.category_id` and reads it at query time rather than freezing it into the journal. Editing a category (§21.4) moves a reminder's whole history with it; a streak torn in half would lie to both categories.

**The windows.** Seven and thirty days are rolling half-open intervals, not calendar weeks: a calendar window jumps on a DST transition and on a move, and a completion rate should not change because somebody changed timezone.

## The weekly digest

A fourth worker cycle, `digest.send`, described as a contract and tested as one. Three decisions worth naming:

- **The idempotency key is the weekly moment, not the send.** `users.digest_sent_at` stores the Monday-09:00 moment the digest covered, not the instant it went out. The send drifts — the cycle wakes once a minute, quiet hours postpone it, a retry postpones it again — and comparing a drifting `now` against the start of a week is arithmetic that a stored moment does not need.
- **An empty week is marked but not sent.** A digest with no outcomes is the bot telling somebody they did nothing, unprompted. The mark still goes down, or the cycle would come back to that user every minute until the week ends.
- **Quiet hours apply.** §20.1 named three paths that assign a delivery moment afresh and required each to pass through `apply_quiet_hours`; the digest is the fourth. The retry exception does not carry over: a retry is a delivery that already came due, and unlike an occurrence a digest has no TTL to expire against while the silence lasts.

Transport failures use a shorter table than §7.2, because retrying a digest for longer than a week is pointless: `forbidden` blocks the user and marks it, `bad_request` marks it, `retry_after` and `transient` leave it for the next tick.

## The switch is not deferred

`users.digest_enabled` ships in the same migration as the digest, defaulting to on. A weekly message with no off switch is a defect rather than a feature, and adding the column a slice later means a week of sending something nobody can stop. It reaches the user through `SetCb(field="digest")` and toggles in place on the settings screen: the question has one answer and two values, so a screen holding a single switch would only stand between the two.

That placeholder is why `render_settings` and `settings_kb` move here rather than with the slice: `settings.title` gains `{digest}`, and a string nobody fills crashes the settings screen instead of postponing it. Both now come from one `settings_screen(user)` builder, so the state printed in the text and the button offering to flip it cannot disagree.

## Contracts and types

New: `StatCb` (prefix `t`, frozen), `JobId.DIGEST_SEND`, `users.digest_enabled` and `users.digest_sent_at` with their migration, `DIGEST_WEEKDAY` / `DIGEST_HOUR` / `DIGEST_BATCH_SIZE`, `app/bot/keyboards/stats.py`, and the text keys of §23.10.

`StatCb` carries the category next to the page for the reason `ListCb` does (§21.1): a page that loses the slice on the first arrow lies about what it shows. `PageCb.scope` and the `Scope` alias gain `stats`, which no arrow will ever use — `paginated_kb` takes `scope` positionally, and a screen naming somebody else's scope for a parameter it overrides anyway would be worse than an unused literal.

`SetCb.field` gains `digest`, append-only like `PageCb.scope` in v9.

## Verification

`make lint`, `make typecheck` and `make test` are green (1683 passed). The migration was applied on an empty database and on the previous revision, and reversed in between; `test_prefixes_are_frozen` was extended with `t`, which is the guard doing its job rather than a change of contract.
