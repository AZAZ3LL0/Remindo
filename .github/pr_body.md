Builds on the v12 contract PR (#26), which is already in `main`.

Closes the four holes that made the bot unusable for anyone opening it for the first time. All four hit the same person, and none of them belonged to a roadmap slice.

## What lands

- **`/help`** — one screen: what the bot does, every command with its description, and how Готово / Отложить / Пропустить feed the statistics. 438 characters in ru, 498 in en.
- **The Telegram command menu**, published at startup for both languages. `bot.commands_published commands=8 languages=2` now appears in the log on boot; before this PR `grep -rn set_my_commands app/` returned nothing and typing `/` in the chat offered the user nothing.
- **An answer to unrecognised text** instead of silence.
- **Onboarding ends on help**, not on the settings screen a new user has just finished with.

## One list, or they drift

The menu and the help table are one fact shown twice, so both are built from `app/bot/commands.py` and nothing else. The contract test welds that list to the real dispatcher: every advertised command has a registered handler, and every command handler reaches the menu. The one exception, `/start`, is a named constant — Telegram draws its own Start button — so the test checks the exemption rather than stepping around it.

`cmd.*` serves both consumers: the menu entry and the help row are the same string, and `help.screen` deliberately carries no placeholders so a ninth command edits the command list alone.

## The catch-all, and why its position is a safety condition

`handle_unknown` is an unfiltered `@router.message()`, which is exactly the kind of handler that can eat everything. It is safe because of where it is registered, not because of what it matches: every text handler in the product is state-filtered and lives in a router above it, so the wizard's input reaches the wizard first.

That is one line away from breaking silently and catastrophically — a reminder could never be created again — so it has its own test: pick a category, type a title, and assert the bot moves on to the schedule question rather than answering "Не понял".

While wiring the router I found the same hazard already latent: `tests/e2e/conftest.py` kept its **own copy** of the handler-module list for detaching router singletons, and a module missing from that copy breaks every dispatcher build after the first. Rather than adding `help` to the copy, I moved the list into `app/bot/main.py` as `HANDLER_MODULES` and had both `build_dispatcher` and the fixture read it. **This is a change you did not ask for** — it removes the duplication that would have caused exactly this bug again.

## One behaviour change to an existing test

`test_a_picked_zone_finishes_onboarding_and_opens_settings` asserted `"Настройки" in last_text`. It is now `..._opens_the_help_screen` and asserts `/new` is offered. The old assertion pinned the behaviour §25.5 deliberately changes; it is renamed rather than deleted so the diff shows the swap.

## Tests

| type | what it pins |
|---|---|
| contract | menu passes `FakeBotGateway` validation in both locales; list welded to the real dispatcher in both directions; a leading slash, upper case, an over-long name, an empty or 257-char description, or a duplicate command each fail the fake first; help fits one message and names every command |
| idempotency | publishing the menu twice leaves one menu per language |
| error path | a refused menu does not stop the bot from booting, and one language failing does not cost the other its menu |
| end to end | `/help` answers; unknown text answers; a step waiting only for a button still answers text; **the catch-all never steals the wizard's input**; no command is ever treated as unknown text |

No property-based test, and that is deliberate rather than an omission: §10.4 requires one for pure domain logic, and this slice adds no pure function to `app/domain` — it is a list, a renderer and routing. A Hypothesis test over string concatenation would mirror the code, which §10 forbids.

1852 passed, coverage 97%.

## Verified live

`docker compose up -d bot` logs `bot.commands_published commands=8 languages=2`. The help screen was rendered through the same code path that reaches Telegram and read in both locales.

The menu and `/help` inside real Telegram still need a real `BOT_TOKEN`: under `USE_FAKE_BOT=true` the process never enters polling (`app/bot/main.py`). That is a limit of the stand, not of the slice, and the end-to-end tests drive the same path through `FakeTelegramSession`.
