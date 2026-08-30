## What this slice does

A delivered reminder is answered with Done / Snooze / Skip, and the tap closes the message it came from. Every decision about whether a tap counts and what it writes moved into a pure `app/domain/reactions.py`, the way S4 moved the planner window and S5 the delivery verdict, so the service is left with the row lock, the transaction and the SQL.

Three behaviours changed:

- a terminal reaction is accepted while a delivery waits out a snooze. Only a terminal delivery or a closed occurrence refuses a tap, which is what tech.md 7.4 says; a second snooze on the same stale button is still a no-op and never pushes the redelivery further away;
- the message loses its buttons on every tap, a rejected one included. Delivery is at-least-once, so the same delivery can carry live buttons in more than one message, and the redraw is rebuilt from the message entities instead of its plain text so a title containing `<` survives it;
- a redraw Telegram refuses is logged and dropped. The reaction is committed by then, and the old code let the failure reach the error handler, which told the user their tap failed after it had counted.

## Contracts and types touched

None. No enum value, callback factory, schedule payload, text key or database column changed. `ReactionResult` now carries `ActionKind` and `RejectReason` instead of two bare strings; both already exist in `app/domain/contracts.py` and in the new domain module.

Two modules are new, following the S4 and S5 layout: `app/domain/reactions.py` and `app/bot/render/reactions.py`.

## Test coverage

- contract: `tests/contract/test_reactions_contract.py` — the redrawn message clears the same limits the original did and carries no keyboard, in both locales and at the longest allowed title; the reminder survives its own answer; every button maps onto an action the domain knows.
- idempotency: `tests/integration/test_reactions.py` — each of the three reactions twice writes one action row and one status, a second snooze leaves `next_attempt_at` where it was, and the same run end to end in `tests/e2e/test_reactions_slice.py`.
- error path: a refused `EditMessageText` leaves the reaction applied and answers the user normally; a late tap on an expired occurrence and a tap from another recipient write nothing.
- property-based: `tests/unit/test_reactions.py` — whatever a tap writes, the state it leaves refuses the same tap; an answered delivery and an expired occurrence refuse every reaction; a snooze always lands in the future; only a final answer from the last recipient closes the occurrence.
