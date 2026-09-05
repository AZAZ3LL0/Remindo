Contract only. The slice that uses it is a separate PR, stacked on this branch.

`tech.md` §9 promised the main menu a reply keyboard and no slice ever built one: `grep -rn ReplyKeyboardMarkup app/` returns nothing. The product answers only to eight typed words, which asks a new user to remember what §25 had just admitted they cannot be asked to remember. The Telegram command menu sits behind a button and lists commands; a permanent keyboard shows actions.

## What §26 fixes

- **§26.1** The keyboard is the third consumer of `app/bot/commands.py`. It takes the whole list with no exemptions of its own: `MENU_EXEMPT_COMMANDS` keeps `/start` out of the Telegram menu, which draws its own Start button, and a keyboard has nothing there to duplicate. Eight commands, eight buttons, two to a row, same order.
- **§26.2** Captions are their own keys, not the `cmd.*` descriptions. A menu row is wide and a button is narrow, and «Таймзона, язык, тихие часы» does not fit on one. This is not a second set of descriptions: the two key families have different jobs and are bound by the command name, which the contract test checks.
- **§26.3** A caption is matched across **every** locale. A reply keyboard is drawn in the chat once and stays; somebody who switched language is pressing captions of the language they left. Hence the invariant that captions are unique in the union of locales.
- **§26.4** The menu router is registered **first**, and that is a correctness condition. A press arrives as an ordinary text message, indistinguishable from an answer to the wizard, so navigation has to beat free text. It is the mirror of §25.4: the catch-all is last because it must beat nobody.
- **§26.5** Navigation drops the wizard, for both forms of it. Typed commands were never winning against a form step at all — `/list` on the title step names a reminder `/list` — and the keyboard made that visible rather than causing it.
- **§26.6** `is_persistent` is required and `one_time_keyboard` refused: a menu that hides after the first press stops being permanent exactly when somebody starts using it.

## What ships with it

- `btn.menu_*`, eight captions in both locales. Plain text, no emoji, like the other sixty `btn.*` strings.
- `app/bot/commands.py` gains `MENU_BUTTONS`, `ALL_COMMAND_NAMES` and `main_menu_labels()`. Still no rendering in it.
- `app/bot/keyboards/menu.py` — `main_menu_kb(lang)`.
- `app/bot/filters.py` — `NOT_A_COMMAND`, built once from `ALL_COMMAND_NAMES`, so a ninth command is kept out of every free-text step by adding it in one place.

`OutgoingMessage` is deliberately untouched: the keyboard belongs to the `bot` process, and the worker sends reminders rather than menus.

## Tests

Nothing new here. The existing catalogue contract covers the eight captions the moment they exist (both locales, matching placeholders, non-empty), and the tests that weld the keyboard to the dispatcher ride with the slice that registers it.

`ruff check`, `ruff format --check`, `mypy app`, `pytest` green: 1876 passed.
