"""Check the sources of the clone and print every problem found.

What is checked: the skills (a directory at the clone's root that holds
SKILL.md), rules/, roles/, providers/ and tools/setup/defaults.toml. Nothing
is written, nothing is run and no checked script is imported. "render" and
"doctor" run the same checks before anything else. What "render" would
refuse of the sources is reported here first: a name too long or not fit
for a file's name on every system, a control character in a title, a
description or a note, a line in a role's text that reads as one of setup's
markers, a file of an installed unit that is not UTF-8 text.

Text output is one line per problem, in a fixed order, then a count:

    roles/coder/role.toml: [role-toml] limits.edits: expected a boolean, got a string
    json-tools/SKILL.md:5: [skill-compatibility] the line must be ...
    2 problems

A problem names its file, relative to the clone, the line where it has
one, the rule in brackets, the key where it has one, and what is wrong.
With no problem the one line says what was checked.

With --json the output is one object: "schema_version", "ok", "problems"
(each with "file", "line", "key", "rule" and "message"; "line" and "key" are
null where the problem has none), "skills" (name, then "providers",
"invoke_only" and "own_setup") and "roles" (role id, then "bytes", the size
of ROLE.md with its includes, and "limit"). With --rules the rule ids are
printed, one per line with what each means, and nothing is checked.

--home and --project are accepted as by every command; the checks read the
clone only.

Exit code 0 when the sources are valid, 1 when a problem was found, and 2
on an error of the command itself, which is printed to stderr; 130 when
interrupted with Ctrl-C, and 128 plus the signal's number when told to end
by a signal; 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import json

from .. import locations, validate

SUMMARY = "check the clone's sources and print every problem found"
EXIT_PROBLEMS = 1


def configure(parser: argparse.ArgumentParser) -> None:
    locations.add_arguments(parser)
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--rules", action="store_true", help="print the rule ids and what each means, and check nothing")


def run(args: argparse.Namespace) -> int:
    if args.rules:
        if args.json:
            print(json.dumps(validate.RULES, indent=2))
        else:
            for rule, meaning in validate.RULES.items():
                print(f"{rule}: {meaning}")
        return 0
    report = validate.check(locations.from_args(args, writes=False))
    if args.json:
        print(json.dumps(report.as_json(), indent=2))
    else:
        for line in report.lines():
            print(line)
        count = len(report.problems)
        if count:
            print(f"{count} problem{'' if count == 1 else 's'}")
        else:
            print(f"no problems: {len(report.skills)} skills, {len(report.role_sizes)} roles")
    return 0 if report.ok else EXIT_PROBLEMS
