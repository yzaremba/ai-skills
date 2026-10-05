"""Print each effective setting and the layer it came from.

Layers, later wins: shipped (the clone's defaults), user
(~/.agents/workflow.toml), project (.agents/workflow.toml in the project)
and local (.agents/workflow.local.toml beside it).

KEY narrows the output to one group (process), one table (roles.coder) or
one value (process.docs_dir). Only the group KEY names is read and checked,
so a fault in another group does not get in the way. A key that is valid
but set in no layer prints nothing.

Several KEYs may be given (show process memory): the output is what each
would print, as one list in the order of a bare "show", with a value that
two KEYs both name printed once. Only the groups the KEYs name are read.

Text output is one line per value:

    process.docs_dir = "docs"  (shipped)

With --json the output is one object: "schema_version", and "settings",
which maps each dotted key to its "value", "layer" and "file".

The key "roles", and only that key, also prints the resolved profiles: the
model and the effort each role definition runs with on each provider. They
are worked out from the role files, the roles group and the providers
group, so "show roles" reads all three and a fault in any of them stops it;
"show roles.<key>" stays within the roles group. In text the settings lines
come first, then an empty line, a heading, and two lines for each
definition on each provider:

    coder @ codex: model = "gpt-6.1-sol"  (role: profile.tier "standard" [role], providers.codex.tiers.standard [shipped])
    coder @ codex: effort = "medium"  (role: profile.effort "medium" [role], providers.codex.efforts.medium [shipped])

A settings line starts with "roles."; a profile line never does. Before the
colon in the brackets is the layer that decided the value: role is the
role's own role.toml, the others are the settings layers. After it are the
keys the value was read through, each with its layer; a model named for the
role under role_models shows that key alone. "effort = none" is a model
that takes no effort setting.

A role with a high_stakes_tier uses it when roles.high_stakes is true. The
switch is then part of what decided the model: the line shows
"roles.high_stakes [<layer>]" among the keys, and its layer counts for the
layer before the colon:

    product-manager @ codex: model = "gpt-6-astra"  (project: profile.high_stakes_tier "frontier" [role], roles.high_stakes [project], providers.codex.tiers.frontier [shipped])

An explicit "tier" under [roles.<id>] wins over roles.high_stakes,
whichever layer sets each: a tier set for one role in the user's file is
not raised by a project that switches high_stakes on. An explicit setting
for one role beats the general switch.

"show roles" also says what the settings set for something that is not
there, as lines on stderr that start with "note:": a [roles.<id>] table or
a role_models key whose id no role definition has, and a
[providers.<name>] section of a provider that has no dictionary. They
change nothing and are not errors (a project may define a role of that id
later); the exit code stays 0.

With --json the profiles are "profiles", a sibling of "settings":
definition id, then "role", "tier", "effort" (the effort name),
"high_stakes" and "providers"; under "providers", the provider name, then
"model", "effort" and "notes". "high_stakes" is the roles.high_stakes
setting (value, layer, file, key) when the tier is the high-stakes one, and
null otherwise. An "effort" has "value", "layer", "mapping" and "not_used".
For a model that takes no effort setting, "value", "layer" and "mapping"
are null, because nothing decided a value that is not written, and
"not_used" holds the mapping that would have applied; otherwise "not_used"
is null. The notes of the paragraph above are "notes", a list beside
"profiles", and are then not repeated on stderr.

Exit code 0, or 2 on an error, which is printed to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import locations, profiles, schema, settings, tomlio
from ..errors import SetupError
from ..profiles import Resolution, Resolved, Source

SUMMARY = "print each effective setting and the layer it came from"
PROFILES_HEADING = "resolved profiles (definition @ provider):"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "key",
        nargs="*",
        metavar="KEY",
        help=f"a group ({', '.join(schema.GROUPS)}) or a dotted key such as process.docs_dir; "
        "every group when omitted; several may be given. \"roles\" adds the resolved profile "
        "of each role definition",
    )
    locations.add_arguments(parser)
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")


def run(args: argparse.Namespace) -> int:
    where = locations.from_args(args)
    resolved: Resolution | None = None
    if not args.key:
        entries = settings.resolve(where)
    else:
        wanted, problems = [], []
        for text in args.key:
            try:
                wanted.append(schema.parse_key(text))
            except SetupError as exc:
                problems.extend(exc.lines)
        if problems:
            raise SetupError(*problems)
        # One read for all the keys, of the groups they name and no other.
        # The result is in the schema's order, so the keys merge by
        # filtering it.
        groups = tuple(group for group in schema.GROUPS if any(parts[0] == group for parts in wanted))
        prefixes = [".".join(parts) for parts in wanted]
        entries = {
            key: entry
            for key, entry in settings.resolve(where, groups).items()
            if any(key == prefix or key.startswith(prefix + ".") for prefix in prefixes)
        }
        if ("roles",) in wanted:
            resolved = profiles.resolution(where)
    if args.json:
        report: dict[str, Any] = {
            "schema_version": schema.SCHEMA_VERSION,
            "settings": {
                key: {"value": entry.value, "layer": entry.layer, "file": str(entry.file)}
                for key, entry in entries.items()
            },
        }
        if resolved is not None:
            report["profiles"] = _profiles_json(resolved.profiles)
            report["notes"] = list(resolved.notes)
        print(json.dumps(report, indent=2))
    else:
        for key, entry in entries.items():
            print(f"{key} = {tomlio.format_value(entry.value)}  ({entry.layer})")
        if resolved is not None and resolved.profiles:
            print()
            print(PROFILES_HEADING)
            for found in resolved.profiles:
                for line in _profile_lines(found):
                    print(line)
        if resolved is not None:
            for note in resolved.notes:
                print(f"note: {note}", file=sys.stderr)
    return 0


def _through(source: Source) -> str:
    return f"{source.key} [{source.layer}]"


def _named(source: Source) -> str:
    return f"{source.key} {tomlio.format_value(source.value)} [{source.layer}]"


def _profile_lines(found: Resolved) -> list[str]:
    head = f"{found.definition} @ {found.provider}"
    if found.explicit_model:
        model_path = _through(found.model_from)
    else:
        switch = f"{_through(found.high_stakes)}, " if found.high_stakes is not None else ""
        model_path = f"{_named(found.tier)}, {switch}{_through(found.model_from)}"
    effort_path = f"{_named(found.effort_name)}, {_through(found.effort_from)}"
    notes = "".join(f"; {note}" for note in found.notes)
    if found.effort is None:
        effort = f"{head}: effort = none  ({notes[2:]}; not used: {effort_path})"
    else:
        effort = f"{head}: effort = {tomlio.format_value(found.effort)}  ({found.effort_layer}: {effort_path}{notes})"
    return [
        f"{head}: model = {tomlio.format_value(found.model)}  ({found.model_layer}: {model_path})",
        effort,
    ]


def _source_json(source: Source) -> dict[str, Any]:
    return {"value": source.value, "layer": source.layer, "file": str(source.file), "key": source.key}


def _effort_json(found: Resolved) -> dict[str, Any]:
    mapping = _source_json(found.effort_from)
    if found.effort is None:
        return {"value": None, "layer": None, "mapping": None, "not_used": mapping}
    return {"value": found.effort, "layer": found.effort_layer, "mapping": mapping, "not_used": None}


def _profiles_json(resolved: tuple[Resolved, ...]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for found in resolved:
        definition = report.setdefault(
            found.definition,
            {
                "role": found.role,
                "tier": _source_json(found.tier),
                "effort": _source_json(found.effort_name),
                "high_stakes": None if found.high_stakes is None else _source_json(found.high_stakes),
                "providers": {},
            },
        )
        definition["providers"][found.provider] = {
            "model": {
                "value": found.model,
                "layer": found.model_layer,
                "from": "role_models" if found.explicit_model else "tier",
                "mapping": _source_json(found.model_from),
            },
            "effort": _effort_json(found),
            "notes": list(found.notes),
        }
    return report
