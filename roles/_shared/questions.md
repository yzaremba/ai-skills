## Questions to the user

Two settings of the project say how you put open questions to the user. Read them once per session with `python scripts/settings.py process --project <project root>` of the `prd-implementation` skill; if it cannot be run, say so and use the defaults.

- **`process.questions`.** `one-at-a-time` (the default): one question, then wait. `all-together`: every open question in one message, numbered.
- **`process.recommend`.** `true` (the default): each question carries your recommendation and its reason in a line. `false`: the options only.
