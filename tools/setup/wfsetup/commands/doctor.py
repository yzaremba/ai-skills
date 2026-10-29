"""Check an install: the clone's sources, what setup wrote in the homes and,
with --project, in a project, and the providers themselves.

    doctor [--json] [--home DIR] [--project DIR] [--allow-unshared-clone]
           [--only NAME]... [--skip NAME]...
           [--no-model-list] [--no-versions] [--no-collab]
           [--codex-probe]
           [--prove-discovery] [--save-probe DIR]

Setup itself writes nothing, anywhere: no file of a home, a project or the
clone, no install record, no state directory. A credentials file is never
opened. (--save-probe DIR, which you ask for, writes into DIR and nowhere
else; DIR is made if it is not there, and may not be inside the clone.)

Four checks start a program of a provider, and such a program may write
state of its own into its own home when it starts (Codex: its databases, an
installation id, its bundled skills). They are models, versions, discovery
and collaboration-skill, left out with --no-model-list, --no-versions,
--skip discovery and --no-collab; with all four the run starts no program.
With --home DIR every program is pointed at DIR and its provider homes, and
never reads or writes the real ones. The first line of the output says
which of the four ran.

Each check has a name and gives findings, each with a severity and one line:

    error     something is wrong and needs doing; the exit code is 1
    warning   something to look at; the exit code stays 0
    info      a fact, or why a check could not be made (a provider that is
              not installed, a home never rendered)
    ok        the check found nothing

The checks, in the order they run:

    sources              the clone's sources, as `validate` checks them: each
                         problem is an error. Role sizes are info.
    drift                a generated file (a role definition, a loaded role,
                         a Codex profile; in a project its definitions, the
                         starting role's keys, "agent" and "effortLevel" in
                         .claude/settings.json, and its block) made from other
                         sources or settings than today's, and one that
                         render would no longer make: warnings. Run render.
    hand-edits           a generated file whose content is not what setup
                         wrote, and a block or a key setup wrote that was
                         changed since: warnings. render keeps such a thing
                         and reports it; `render --overwrite-edited` backs
                         it up and replaces it.
    missing              what the install record lists and is gone from
                         disk: an error. What render would create now and
                         the record does not list: a warning, and info on a
                         home (or a project) that was never rendered, and
                         for the generated files of a home rendered with
                         --no-roles. The roles turned off by the setting
                         roles.enabled = false, for the home or for the
                         project, are an info line that names the file:
                         nothing of them is then missing, and what an
                         earlier run generated is reported by drift as
                         render would no longer make it. With the home's
                         roles off, an info line also says that each
                         project rendered with roles keeps its starting
                         role until `render --project DIR` takes it out.
                         Something at a path where render would
                         install, which setup did not make: an error, since
                         render stops on it.
    links                a link the record lists that is missing, is no
                         longer a link, leads elsewhere than setup pointed
                         it, leads to something that does not exist (a moved
                         or removed clone), or resolves outside the clone:
                         errors.
    duplicate-skills     a skill name setup installs that is also in another
                         skill location of the same provider, with both
                         paths: a warning. For Codex the deprecated
                         <codex home>/skills, which it still reads, and it
                         does not merge two skills of one name; with
                         --project the project's .claude/skills and
                         .agents/skills.
    other-clones         a link in a skills or rules directory, or in the
                         record, that leads into another clone of this
                         repository, and a clone inside a skills directory:
                         warnings. The collaboration skill linked from
                         another clone is info: it runs from the development
                         clone by intent. A clone is told by what it holds
                         (tools/setup/workflow_setup.py and roles/); git is
                         not run.
    clone                whether both sides of the machine can read the clone
                         this runs from: an error where they cannot, a
                         warning with --allow-unshared-clone, info where the
                         setting setup.allow_unshared_clone = true in
                         ~/.agents/workflow.toml allows it (decided once,
                         for every run; the line names the file); not asked
                         with --home or on a Linux with no Windows side. A
                         setting that allows it where it is not needed is
                         info as well. A project's file that holds [setup]
                         is an error: the group is read from the user's
                         file alone.
    models               each installed provider's own model list beside its
                         mapping: a mapped model that is not in the list, or
                         an effort a definition resolves to that the list
                         does not give its model, is an error; a mapped
                         model listed as hidden, or with other efforts than
                         the dictionary has, a warning; a list that cannot
                         be read, a warning with the reason. Claude Code has
                         no list: info. This starts the provider's list
                         command (`codex debug models`); --no-model-list
                         leaves the check out.
    versions             `<program> --version` of each installed provider: a
                         version newer than the one its dictionary was
                         checked on, or older than the oldest supported, or
                         one that cannot be read, is a warning.
                         --no-versions leaves the check out.
    codex-settings       keys of the user's Codex config.toml, each with its
                         value or as unset:
                         agents.max_concurrent_threads_per_session (below 8
                         is a warning),
                         features.multi_agent_v2.min_wait_timeout_ms, the
                         wait floor (below 300000 is a warning), with
                         default_wait_timeout_ms and max_wait_timeout_ms of
                         that table where they are set (an order Codex
                         refuses, min <= default <= max broken, is a
                         warning), sandbox_mode (while it is set Codex
                         uses it and ignores default_permissions: info) and
                         default_permissions. No other key is read out of
                         the file (but project_doc_max_bytes, for the check
                         instruction-files, and model and
                         model_reasoning_effort, the Manager's pin below)
                         and no other value is printed.
                         A file that cannot be read is a warning that says
                         where the fault is, not what the line holds. Then,
                         as info:
                         whether the blocks `render --apply-codex-settings`
                         writes are in the file and as setup wrote them, by
                         the install record; and what that command would do
                         now and would leave to you (a limit you set
                         yourself; an [agents] table it cannot add to, with
                         the line to add; a features.multi_agent_v2 of
                         yours, with whether its floor is met and the lines
                         to add; no permission profile while
                         sandbox_mode is set, which setup never changes, so
                         that git commands go through approval one by one).
                         A block of setup's that defines the profile while
                         the file sets neither default_permissions nor
                         sandbox_mode is an error: Codex will not start.
                         --codex-probe adds the steps of the one Codex
                         session, started by you, that shows whether this
                         Codex ignores a `-c default_permissions=...`
                         override while sandbox_mode is set.
                         The Manager's pin, model and model_reasoning_effort
                         in the block at the head: a warning where the block
                         holds other values than the Manager resolves to
                         now, or where the file sets either key itself
                         beside setup's blocks, with the lines to delete.
    profiles             what the settings set for something that is not
                         there (a role id no definition has, a provider with
                         no dictionary): warnings. A profile that does not
                         resolve: an error.
    v1                   what a v1 install left in a home: an import line of
                         a v1 rule, a v1 rule or skill copy, a v1 link.
                         Each is an error until `render --migrate-v1`
                         removes it; a place the other side owns is info.
    interrupted-run      an earlier run of setup that was stopped half way:
                         a warning with the changes found made and those
                         dropped; the temporary files its record lists, its
                         lock and what its start left (the next run that
                         writes removes these); a lock setup cannot judge;
                         backups under a state directory that no record
                         lists (setup never removes them by itself;
                         `uninstall --discard-backups` does). A file that
                         is only named like a temporary of setup's is info:
                         it is left alone.
    loaded-skill-size    a loaded role whose skill is estimated over what
                         Claude Code keeps of a skill after a compaction: a
                         warning. Codex documents no such cut and its
                         dictionary names no figure: its sizes are info.
    instruction-files    with --project DIR, whether both providers load
                         DIR/AGENTS.md, where the lesson index of the
                         project-memory skill is; without it, info.
                         Claude Code reads AGENTS.md directly only while no
                         CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md is
                         in DIR or in a directory above it. The user's own
                         CLAUDE.md, the one that lies in the Claude Code
                         home, is not one of them; a file elsewhere that is
                         a link to it is. One of the three with no remedy
                         is an error. The remedies: a line `@AGENTS.md` in
                         one of those files, the path relative to the file
                         (only an import written in the file itself is
                         seen, and not one in a code block, a code span or
                         an HTML comment; where that cannot be told, none
                         is found), or
                         pluginConfigs."agents-md@builtin".options.instructionFiles
                         set to "claude-md-and-agents-md" in the user's
                         settings.json; that one key is read from the file
                         and nothing else, and Claude Code ignores it in a
                         project's settings files. Under the id
                         "cc-plugin-agents-md@builtin" alone the setting is
                         a warning: Claude Code before 2.1.285 ignores that
                         id. Two ids with different values are a warning
                         and no remedy. A file over the 4 MiB above which
                         Claude Code skips an instruction file is said to
                         be skipped and is not opened: a warning for a
                         CLAUDE.md, whose import is then no remedy, an
                         error for DIR/AGENTS.md. A file over three
                         quarters of that is a warning. An
                         AGENTS.override.md in DIR that is not empty is a
                         warning: Codex takes one file from a directory,
                         the first that is not empty, and it replaces
                         AGENTS.md there; an empty one is info. The
                         instruction files Codex loads (its home's, and
                         DIR's) over three quarters of its limit together
                         are a warning: 32 KiB, or project_doc_max_bytes in
                         the user's config.toml when set. DIR is taken by
                         its real path.
    discovery            whether each provider itself lists every skill,
                         loaded role, role definition and starting role that
                         is installed. Only a provider's own output counts,
                         never a model's answer. Each item is proven (the
                         output lists it: ok, with the command), unproven
                         (no output that was read could list it) or missing
                         (an output that should list it was read and does
                         not: an error); one line gives the count of each.
                         Unproven items are info on a plain run, all in one
                         line with the reason for each and what would prove
                         it; with --prove-discovery each one the probes
                         did not prove is a warning.
                         A file the provider could not load (a definition
                         that does not parse or lacks a required key, a
                         skill with no SKILL.md) is an error. Without a
                         session: Codex's skills, loaded roles and starting
                         role, by `codex debug prompt-input`, the same with
                         `--profile <role>`, and the `skills/list` request
                         of `codex app-server` (experimental in Codex).
                         Codex's role definitions and everything on Claude
                         Code are unproven without a session.
                         --prove-discovery also starts ONE SESSION WITH A
                         MODEL PER PROVIDER, WHICH SPENDS QUOTA: `claude -p`
                         with a one-line prompt, read up to its first event
                         and then ended, and one `codex exec` with the same
                         prompt, whose event stream is searched for the
                         agent names in the spawn tool's text. Neither
                         reads what the model answered.
                         --save-probe DIR writes what each probe gave,
                         reduced to names (keys, event types, the lists of
                         skills, agents, commands and tools; no description,
                         prompt, model output, path or id), one JSON file a
                         probe, into DIR: the one thing doctor writes.
    collaboration-skill  the state of multiagent-collab, by starting that
                         skill's own doctor with this interpreter, found
                         through the link in a provider's skills directory.
                         Each check it fails is reported with its own
                         severity: its errors are errors here, its warnings
                         warnings. A doctor that cannot be started, does not
                         finish or prints what cannot be read is a warning.
                         Not installed: info. --no-collab leaves it out.

--only NAME runs the named checks and no other; --skip NAME leaves one out.
Both may be given more than once. A check that fails by a fault of its own
is reported as an error finding of its name, and the others still run.

Programs started: the list command of a provider, `<program> --version`, the
collaboration skill's doctor, and the offline commands of the check
`discovery`. Each has a fixed argument list, no shell and a time limit. None
starts a session with a model; only --prove-discovery does.

A place whose real path is on the other side of the machine (a link from the
WSL home into the Windows home, or the reverse) is read where it can be read
and said to be the other side's.

The output: the findings by check, then one line with the counts by
severity. With --json one object with the same facts ("checks", each with
"name", "severity" and "findings"; "not_run"; "counts"; "summary";
"exit_code").

Exit code 0 when no finding is an error, 1 when one is, and 2 when the
command itself could not run (a directory that is not there, a name that is
no check), which is printed to stderr; 130 when interrupted with Ctrl-C, and
128 plus the signal's number when told to end by a signal (143 for
SIGTERM); 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import json

from .. import discovery, doctor, homes, locations

SUMMARY = "check the sources, what setup installed and the providers; setup writes nothing, exit code 1 on an error"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    locations.add_arguments(parser)
    homes.add_arguments(parser)
    parser.add_argument(
        "--only", action="append", default=[], metavar="NAME",
        help="run this check and no other; may be given more than once. The checks: " + ", ".join(doctor.names()),
    )
    parser.add_argument(
        "--skip", action="append", default=[], metavar="NAME",
        help="leave this check out; may be given more than once",
    )
    for check in doctor.CHECKS:
        check.add_arguments(parser)


def run(args: argparse.Namespace) -> int:
    chosen, left_out = doctor.select(args, only=args.only, skip=args.skip)
    where = locations.from_args(args, writes=False)
    if args.save_probe is not None:
        # Refused before any check runs, as every faulty argument is.
        discovery.save_directory(args.save_probe, where.clone)
    context = doctor.Context(where, args)
    found = doctor.report(context, doctor.run(context, chosen), left_out)
    if args.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
    else:
        for line in doctor.report_lines(found):
            print(line)
    return found["exit_code"]
