"""Reduce the output of `codex debug models` to a fixture.

    codex debug models > full.json
    python reduce_codex_models.py full.json codex-debug-models-<version>.json

Keeps the shape Codex prints, {"models": [...]}, the catalog's order, and
of each entry only `slug`, `visibility`, `default_reasoning_level` and the
`effort` of each `supported_reasoning_levels` item. Everything else (base
instructions, descriptions, limits, access programs) is dropped. The names
of the dropped keys are printed, so what was left out is seen.
"""
import json
import sys

KEPT = ("slug", "visibility", "default_reasoning_level", "supported_reasoning_levels")


def main(source: str, target: str) -> None:
    with open(source, encoding="utf-8") as handle:
        data = json.load(handle)
    dropped = set(data) - {"models"}
    models = []
    for entry in data["models"]:
        dropped.update(set(entry) - set(KEPT))
        models.append({
            "slug": entry["slug"],
            "visibility": entry["visibility"],
            "default_reasoning_level": entry["default_reasoning_level"],
            "supported_reasoning_levels": [
                {"effort": level["effort"]} for level in entry["supported_reasoning_levels"]
            ],
        })
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"models": models}, indent=2) + "\n")
    print(f"{len(models)} models written to {target}")
    print("dropped keys:", ", ".join(sorted(dropped)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
