Core contract change for the roadmap item **S10. Совместные напоминания** (`tech.md` §15). Bumps the core to **v9** and appends §22.

Merge this before the slice PR; the slice branches off it.

## Why a contract change

S10 had nowhere to land. An invitation had no row to live in, no factory to be pressed with, no strings to speak, and the link `t.me/<bot>?start=inv_<token>` had no bot name to be built from. None of that can be invented inside a slice PR (`tech.md` §0, §11.2).

## What §22 fixes

- **An invitation is a row, not a signature.** A token derived from the reminder id with a secret can be neither revoked nor expired: a link that reaches a group chat once keeps working forever. `reminder_invites` carries `expires_at` and `revoked_at`, and a partial unique index keeps exactly one live invitation per reminder, so revoking actually revokes.
- **`ShareCb`** (prefix `i`) is the access screen's own factory: open, invite, revoke, accept, decline, leave, confirm_leave. It carries the reminder id and not the token, because by the time any of those is pressed the recipient row already exists.
- **Acceptance goes through a recipient row**, `role = 'watcher'` with `accepted_at IS NULL`, which is exactly what the schema of §4.2 already describes. A row rather than FSM state, because the invitee usually meets the bot for the first time: onboarding has to ask for a timezone first, and the invitation has to survive it.
- **Accepting and unsubscribing correct the queue.** The planner creates deliveries at materialisation, so a watcher who accepts later would receive nothing already materialised, and one who leaves would keep receiving what is already queued. Accepting backfills deliveries for `pending` occurrences still ahead; leaving takes back the `pending` deliveries of that user. `sent` is left alone for the same reason a pause leaves it alone (§21.3).
- **A watcher cap.** Every acceptance multiplies deliveries per occurrence, so a link leaked into a public chat would turn one reminder into a broadcast.
- **`BOT_USERNAME` in the configuration.** `getMe` is a network call and `USE_FAKE_BOT` has no network, so the link is built from configuration or not at all.

## Contracts and types

`tech.md` §22 (v9). New table `reminder_invites` with migration `9c1f4b7ae520`, and the model `ReminderInvite`.

`domain/contracts.py` gains `INVITE_TOKEN_BYTES`, `INVITE_TOKEN_LENGTH`, `INVITE_TTL_HOURS`, `REMINDER_WATCHERS_MAX`, `DEEP_LINK_MAX_LENGTH`. `domain/errors.py` gains `InviteExpiredError` and `RecipientLimitError`; an unknown token stays a `NotFoundError` and one's own invitation a `PermissionDeniedError`, because neither needs a second name.

`callbacks.py` gains `ShareCb` and the `shared` value of `PageCb.scope`. `confirm_kb` takes a fourth action, `leave`. `keyboards/share.py` holds the four access screens; `reminder_card_kb` gains the Access button. `texts.py` gains the `share.*` and `btn.*` keys, and `reminder.card` gains a third placeholder, `{shared}` — the card is the one screen where a reminder's state is read, and a reminder that goes out to three more people has to say so. `render_reminder_card` takes `watchers: int = 0`, so no existing call changes.

## Tests

Contract only, as core PRs are: the new factory round-trips inside 64 bytes and the frozen prefix list gains `i`. The slice PR brings the rest.

`ruff check`, `ruff format --check`, `mypy app` and `pytest` are green: 1526 passed.
