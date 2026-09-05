Closes the roadmap item **S10. Совместные напоминания** (`tech.md` §15).

Builds on the v9 contract PR and targets its branch; merge that one first.

## What the slice does

A reminder could only ever reach the person who made it. The schema had a `reminder_recipients` table with a `watcher` role and an `accepted_at` column, and the planner already delivered to everyone accepted — but nothing could put a second row there.

- **The owner hands out a link.** The card gains an Access button. Behind it: who receives this reminder, who is still deciding, a button to mint `t.me/<bot>?start=inv_<token>`, and a button to take it back. The link is sent as a message of its own, because it is meant to be forwarded and the next redraw would take it away.
- **The invitee follows it and answers.** The link resolves into a pending recipient row, and the invitee sees the reminder itself before deciding — a link in a chat should not subscribe anybody silently.
- **Onboarding comes first.** An invitee usually meets the bot through the link, so `/start inv_…` asks for a timezone before anything else and shows the invitation once it is answered. Without a timezone the reminder has no local time to be shown in. The invitation survives the detour because it is a row, not FSM state.
- **`/shared`** lists what other people share, pending invitations marked, each row opening a read-only card with an unsubscribe button.
- **Both sides can end it.** The owner revokes the link; the watcher unsubscribes, with a confirmation.

## The two queue bugs the slice had to fix

The planner creates deliveries at materialisation time, so joining and leaving both left the queue lying.

**Accepting** now backfills deliveries for the occurrences still ahead — otherwise a watcher who accepted at noon would receive nothing until the planner reached past the horizon it had already covered. The boundary is `fire_at > now` rather than every `pending` row: an occurrence whose moment has passed is already with the dispatcher, and a watcher who joined a minute ago should not be told about something that was due before they arrived.

**Unsubscribing** now takes back the `pending` deliveries of that recipient. `sent` and `snoozed` are left alone, by the same rule a pause follows (§21.3): live buttons are on somebody's screen, and a snooze was the user's own request.

## Contracts and types

No schema change and no core file touched here: everything the slice needs landed in the v9 contract PR.

New: `app/domain/sharing.py` (token, deep link, `InviteState`, `check_join`), `app/services/sharing.py` (`SharingService`, `Participant`, `SharedReminder`), `app/db/repositories/invites.py`, `app/bot/handlers/share.py`, `app/bot/render/share.py`.

`RecipientsRepository` gains the recipient queries; `OccurrencesRepository` gains `list_upcoming`; `DeliveriesRepository` gains `delete_pending_for_recipient`. `handlers/start.py` routes a start payload into the sharing module and finishes onboarding into the invitation rather than into the settings screen — `/start` keeps one entry point, so the two modules do not have to import each other.

The domain draws no randomness: `new_invite_token` takes the entropy as an argument the way pure functions take `now` from the `Clock`, and the service supplies it. A token is therefore reproducible in a test without patching anything.

## Tests

- **Contract** — `tests/contract/test_share_contract.py`: every screen passes `FakeBotGateway`, `ShareCb` round-trips inside 64 bytes at full size and is registered with the gateway, the shared list pages without losing its scope, revoking is drawn only when there is a link to revoke, cancelling a leave returns to the screen it was asked on, the token length matches the entropy it is made of, a full-size payload fits Telegram's limit, and a recipient with no username and no name still has something to be called.
- **Idempotency** — following a link twice leaves one row; accepting twice backfills one set of deliveries and does not move the moment the first press recorded; revoking twice revokes once; unsubscribing twice unsubscribes once; and a planner cycle over a two-recipient reminder creates nothing on its second run.
- **Error path** — `TelegramRetryAfter` and `TelegramForbiddenError` on the redraw leave the committed change in place and do not let the press be replayed into a second effect; an identical redraw answers `message is not modified`, which is the expected outcome.
- **Property-based** — `tests/unit/test_sharing.py` over `domain/sharing.py`: a token is always the contract's length, uses only characters Telegram accepts, and is a function of its entropy alone; a payload round-trips and fits the deep-link limit; the prefix is split off by length and not by separator, because the token alphabet contains `_` too; revocation wins over the clock at every offset; and the watcher limit refuses a newcomer while always letting an existing watcher back in.
- **Integration** — `tests/integration/test_sharing.py`: the queue corrections above and what they must not touch, the refusal table of §22.5 including the owner's own link and a full reminder, a watcher who cannot edit or see somebody else's reminder in `/list`, a stranger's crafted press, a delete cascading into the invitation, a pause taking back the watcher's queue too, and an occurrence closing only once every recipient has reacted.
- **End to end** — `tests/e2e/test_share_slice.py`: two people through real routers, from `/new` to a reminder the dispatcher sends to both chats. The suite gains a second feeder, because a shared reminder cannot be exercised by one person.

`ruff check`, `ruff format --check`, `mypy app` and `pytest` are green: 1636 passed, coverage 97%. `docker compose up` starts the stack with `USE_FAKE_BOT=true` and no token.
