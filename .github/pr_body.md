Core change for the help surface. Appends §25 and bumps the core to **v12**.

Not a roadmap item — §15 is closed, S0 through S12. This covers what no slice covered: the first minute of a new user. A product with eight commands, none of which is listed anywhere, is indistinguishable from a broken bot to somebody who just opened it.

## What is missing today

Four holes, all hitting the same person:

1. **No `/help`.** No screen anywhere explains the product.
2. **The Telegram command menu is empty.** `grep -rn set_my_commands app/` returns nothing, so typing `/` in the chat offers none of the eight commands that exist.
3. **Unknown text gets silence.** There is not one unfiltered `@router.message()`, so anything that is neither a command nor an answer to the wizard falls through to nothing. In a messenger, silence reads as a crash, not as "I did not understand".
4. **Onboarding ends on the settings screen** (`app/bot/handlers/start.py:117`). Somebody who has just named their timezone gets a list of settings instead of an answer to "so now what".

## §25, and the three decisions in it

**One list, two consumers.** The Telegram menu and the command table in `/help` are one fact shown twice; drifting apart they lie in both directions — the menu offers what does not exist, or the help omits what does. So the list lives once, in `app/bot/commands.py`, and both screens are built from it. A contract test keeps it welded to the dispatcher: every menu command has a registered handler and every command handler reaches the menu, walking the real `build_dispatcher` rather than a copy of the list. The single exception is `/start`, and it is a named constant rather than an oversight — Telegram has its own Start button. Naming it means the test checks the exception instead of stepping around it.

**The menu goes through the protocol.** §8 requires everything external to sit behind a protocol and run against the fake from day one, and a menu push is a network call like any other. `BotGateway` gets `set_commands`, `FakeBotGateway` records it per language and validates it the way `validate_outgoing` validates a message: command matching `^[a-z0-9_]{1,32}$`, non-empty description within 256 characters, no duplicates, at most 100 entries. Otherwise the menu would be the one part of the bot that `USE_FAKE_BOT=true` cannot check, and the first thing to break for a live user.

`BotCommandSpec.command` carries no leading slash, the way Telegram accepts it — the slash is drawn by the help renderer, because storing one value in two shapes is how the two screens drift.

**A failed menu push must not stop the bot.** If Telegram rejects it, the process still enters polling and the refusal is logged at error level. A bot that will not boot because a command caption failed to update is worse than a bot with a stale caption — the same rule by which §23.5 does not drop a digest batch over one recipient.

## What lands

| file | change |
|---|---|
| `tech.md` | §25, version `v12`, changelog line |
| `app/gateways/bot_gateway.py` | `BotCommandSpec`, `set_commands` on the protocol and on `AiogramBotGateway` |
| `app/gateways/fakes.py` | `validate_commands`, per-language recording in `FakeBotGateway` |
| `app/bot/render/texts.py` | `help.screen`, `help.unknown`, and eight `cmd.*` descriptions |

`help.screen` deliberately carries no placeholders: the command table is glued on from `cmd.*` rather than formatted in, so adding a ninth command edits one place instead of two. The `cmd.*` strings serve both the Telegram menu entry and the help table — there is no second set of descriptions for the same thing.

## Boundaries

No sectioned help behind buttons and no new CallbackData factory: a product of eight commands is explained faster than a menu about it can be read. No step-by-step tutorial either — the `/new` wizard already walks the user through, and a second guided flow on top would explain the first instead of letting them use it.

## Checks

`ruff check`, `ruff format --check`, `mypy app` clean; 1822 passed.
