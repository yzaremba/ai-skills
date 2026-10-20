## Questions to the user

Two project settings say how you put open questions to the user. Read them once a session with `python scripts/settings.py process --project <project root>` of the `prd-implementation` skill; if it cannot run, say so and use the defaults.

- **`process.questions`.** `all-together` (the default): every open question in one message, numbered. `one-at-a-time`: one question, then wait.
- **`process.recommend`.** `true` (the default): each question carries your recommendation and its reason in a line. `false`: the options only.
