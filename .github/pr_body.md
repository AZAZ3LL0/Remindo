Builds on the v13 contract PR (#28). Base it on `main` once that one lands.

Eight buttons under the input field, always. Before this PR the only way into any screen was typing a slash command or opening Telegram's own command menu, which is a list of names rather than a row of actions.

## What lands

- **`app/bot/handlers/menu.py`**, registered **first** in `HANDLER_MODULES`. A press arrives as plain text, so anywhere later the wizard takes it for an answer to the current question. The mirror of the catch-all, which is last because it must win over nobody, and both ends now say so in one comment on the tuple.
- **A press calls the command's handler** rather than repeating its body. A second copy of the logic would drift from the first, the way the menu and the help table would drift without one list.
- **The keyboard is drawn where a message carries no inline markup**: the returning greeting, the end of onboarding, `/help`, the answer to unrecognised text, and a message after a language switch. One message holds one `reply_markup`, so these are the only places it can ride.
- **The onboarding attachment sits on the timezone confirmation**, not on the help screen after it: the invitee branch returns early with an inline keyboard, and put there both branches end with the menu drawn.

## A latent bug this made visible

Free-text steps were filtered by state alone. `/list` typed on the title step became the title, and the reminder was created named `/list`. Seventeen handlers across five modules now carry `NOT_A_COMMAND`, built once from the command list.

The other half of the same rule: opening a screen clears the FSM. `/settings` and `/categories` already did; `/list`, `/today`, `/stats`, `/shared` and `/help` did not, so a user who navigated away found their next sentence becoming the title of a reminder they had left. `/new` now clears too — **a change beyond the reply keyboard** — because the abandoned draft it inherited could still carry `edit_reminder_id`, which would have turned a new reminder into an update of an old one.

## One existing test moved a line

`test_settings_switches_the_language_and_repeating_it_changes_nothing` asserts the settings screen is the last thing rendered. The language switch now also sends the redrawn keyboard, so that send happens **before** the screen is redrawn rather than after. The assertion is unchanged and still means what it meant.

## Tests

29 new, both required kinds plus the routing invariant.

- **Contract** (`tests/contract/test_menu_keyboard.py`) walks the real dispatcher, not a copy: every button has a registered handler, every command reaches the keyboard, every button is routed. Captions are unique across the union of locales and carry no placeholders, the index covers both locales, the rows are two wide, the markup is persistent and not one-time, and the menu router is first while `help` and `errors` stay last.
- **End to end** (`tests/e2e/test_menu_slice.py`) presses all eight captions and asserts each opens exactly the screen its command opens; a caption pressed on the wizard's title step navigates instead of naming, and the next free phrase is no longer taken as a title; a typed `/list` on that step opens the list; ordinary text still reaches the wizard; a `ru` caption still works after switching to `en`, and the keyboard comes back in the new language.

Mutation-checked rather than assumed: moving the `menu` router to the end of `HANDLER_MODULES` fails exactly two tests, the contract one on order and the end-to-end one on the wizard.

`ruff check`, `ruff format --check`, `mypy app` green. 1905 passed, coverage 97.25%.
