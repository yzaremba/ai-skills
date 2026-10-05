# Test fixtures

- `codex-debug-models-0.160.0.json`: the output of `codex debug models` (the refreshed catalog, not `--bundled`) on Codex CLI 0.160.0, run on 2026-10-05 and reduced with `reduce_codex_models.py` to each model's `slug`, `visibility`, `default_reasoning_level` and effort values, in the catalog's order. It holds no account data: the reduction drops every other key. `test_dictionary.py` checks `providers/codex/dictionary.toml` against it. When the dictionary is brought up to a newer Codex version, a new reduced copy replaces this one.
- `reduce_codex_models.py`: makes such a copy. `python reduce_codex_models.py full.json codex-debug-models-<version>.json`.
