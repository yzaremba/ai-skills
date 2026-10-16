"""Print the homes this run would handle, and whose each place is.

It only reads: it looks at paths, reads the text of links and lists the
names in the providers' directories. It opens no file of a home, a project
or the clone, prints no file's content, and never looks into a credentials
file. (On Linux it reads the kernel's release and its mount table, which is
how WSL and the Windows drives are told.) It starts no program.

What is printed:

    side      linux, wsl or windows, and the other side of the machine
    clone     the repository the tool runs from, and whether both sides can
              read it. A command that installs refuses a clone they cannot
              both read unless --allow-unshared-clone is given; this
              command only says so
    for each provider (claude-code, codex)
              whether it counts as installed (its program is on PATH, or
              its home exists), its home and where that came from
              (default, an environment variable, --home), and each place
              in it that setup uses, with whose it is:

        this side      this run writes it
        shared         it is, or lies under, a link to elsewhere on this
                       side; written once, where the link leads
        already handled  the same directory as a place listed before
        other side     its real path is on the other side's file system;
                       this run skips it, the run on that side writes it

              and, for a directory of this side, what each name in it is
              now: a link into the clone, a link to elsewhere on this side
              or to the other side, something of its own that is not a
              link, or a skill managed by its own setup.

The homes are the Claude Code home (CLAUDE_CONFIG_DIR, else ~/.claude) and
the Codex home (CODEX_HOME, else ~/.codex), with Codex's user skills in
~/.agents/skills. With --home DIR they are DIR/.claude, DIR/.codex and
DIR/.agents, and the two environment variables are ignored.

With --json the output is one object with the same facts.

Exit code 0, or 2 on an error, which is printed to stderr; 130 when
interrupted with Ctrl-C, and 128 plus the signal's number when told to end
by a signal; 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import json

from .. import homes, locations

SUMMARY = "print the providers' homes and whose each place is (reads only)"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    locations.add_arguments(parser)


def run(args: argparse.Namespace) -> int:
    found = homes.report(homes.resolve(locations.from_args(args, writes=False)))
    if args.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
    else:
        for line in homes.report_lines(found):
            print(line)
    return 0
