"""Print each effective setting and the layer it came from.

Layers, later wins: shipped (the clone's defaults), user
(~/.agents/workflow.toml), project (.agents/workflow.toml in the project)
and local (.agents/workflow.local.toml beside it).

The group setup (setup.allow_unshared_clone) is read from the user's file
alone: a project's file that holds it is an error here, as in every command
that reads the group.

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

The group project is not printed as merged lines, because its lists do not
merge key by key: the project's set is every name in project.enabled of
either file, less every name in the local file's project.disabled, plus the
units those need. In place of the merged lines the group prints each list of
each file, with its layer (project or local), then the resulting set, then a
line for each unit added as a dependency, with what needs it:

    project.enabled = ["alpha", "beta"]  (project)
    project.disabled = ["alpha"]  (local)
    project set = ["beta", "solo"]
      solo: installed as a dependency of beta

Any KEY inside the group (project.enabled) prints the whole of it. A project
whose two files hold no [project] group, and a run with no --project, print
nothing for it. A name that is no unit, and a name in both lists of one
file, are errors naming the file. With --json the same is "project", a
sibling of "settings", and absent in the same cases: "files" (each with
"layer", "file", "enabled" and "disabled", null for a list the file does not
hold), "set", "needed" (a unit added as a dependency, and what needs it) and
"overrides" (such a unit that a list leaves out, with the list's "key" and
"file").

Exit code 0, or 2 on an error, which is printed to stderr; 130 when
interrupted with Ctrl-C, and 128 plus the signal's number when told to end
by a signal; 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import definitions, locations, profiles, schema, settings, tomlio, validate
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
    where = locations.from_args(args, writes=False)
    resolved: Resolution | None = None
    wanted: list[tuple[str, ...]] = []
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
    chosen = None
    if any(key.startswith("project.") for key in entries):
        entries = {key: entry for key, entry in entries.items() if not key.startswith("project.")}
    if (not args.key or any(parts[0] == "project" for parts in wanted)) and _project_files(where):
        chosen = definitions.project_selection(where, validate.check(where).skills)
    if args.json:
        report: dict[str, Any] = {
            "schema_version": schema.SCHEMA_VERSION,
            "settings": {
                key: {"value": entry.value, "layer": entry.layer, "file": str(entry.file)}
                for key, entry in entries.items()
            },
        }
        if chosen is not None:
            report["project"] = _project_json(where, chosen)
        if resolved is not None:
            report["profiles"] = _profiles_json(resolved.profiles)
            report["notes"] = list(resolved.notes)
        print(json.dumps(report, indent=2))
    else:
        for key, entry in entries.items():
            print(f"{key} = {tomlio.format_value(entry.value)}  ({entry.layer})")
        if chosen is not None:
            for line in _project_lines(where, chosen):
                print(line)
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


def _project_files(where: locations.Locations) -> list[tuple[str, Any, dict[str, Any]]]:
    """The layer, file and ``[project]`` table of each project file that holds the group."""
    return [
        (document.layer, document.file, document.data["project"])
        for document in settings.documents(where, ("project",))
        if document.layer in settings.PROJECT_LAYERS and isinstance(document.data.get("project"), dict)
    ]


def _project_lines(where: locations.Locations, chosen: definitions.Selection) -> list[str]:
    lines = []
    for layer, _, group in _project_files(where):
        for key in ("enabled", "disabled"):
            if key in group:
                lines.append(f"project.{key} = {tomlio.format_value(group[key])}  ({layer})")
    lines.append(f"project set = {tomlio.format_value(sorted(chosen.units))}")
    lines.extend(f"  {note}" for note in chosen.notes())
    return lines


def _project_json(where: locations.Locations, chosen: definitions.Selection) -> dict[str, Any]:
    return {
        "files": [
            {"layer": layer, "file": str(file), "enabled": group.get("enabled"), "disabled": group.get("disabled")}
            for layer, file, group in _project_files(where)
        ],
        "set": sorted(chosen.units),
        "needed": {name: list(by) for name, by in sorted(chosen.needed.items())},
        "overrides": {name: {"key": key, "file": str(file)} for name, (key, file) in sorted(chosen.overrides.items())},
    }


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
