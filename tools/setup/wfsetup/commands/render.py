"""Install the clone's skills and rules into the providers' homes, as links,
generate each provider's role definitions and the entry points of a session,
and with --project what a project gets.

    render [--dry-run] [--home DIR] [--project DIR] [--json] [--no-roles]
           [--overwrite-edited] [--follow-config-symlinks]
           [--allow-unshared-clone]
           [--apply-codex-settings [--worktree-root DIR]
            [--default-codex-permissions]] [--remove-codex-settings]
           [--migrate-v1 [--remove-stale PATH]...]

In this order: the clone's sources are checked ("validate"), and any problem
stops the run; on a machine with a Windows side and a WSL side the clone must
be one both can read, unless --allow-unshared-clone is given for this run or
the setting setup.allow_unshared_clone = true is in ~/.agents/workflow.toml
for every run (not asked with --home; the output says what allowed such a
clone); then one plan is made, printed, and applied. With --dry-run it is
only printed. The whole plan is checked before the first write, so a plan
that is refused writes nothing. Applying it is not atomic: if a change fails
part way, the changes before it stay and are recorded, the error says how
many, the next run goes on from there, and "uninstall" undoes them.

One run writes to a home at a time, and one to a project: a second one ends
at once with exit code 2 and names the run that holds the lock. A project
has its own lock, record and backups, in DIR/.agents/workflow-setup. A run
that was killed leaves its lock, its unfinished changes and perhaps a file
under a temporary name that its record lists; the next run that writes
clears the lock where that process is provably gone (else the message says
how), settles the changes from the disk, removes those temporary files, and
says so. It removes no backup, and no file that is only named like one of
its temporaries. A lock taken on another system (a project on a Windows
drive, used from Windows and from WSL) is never cleared from here.

Whatever the options, nothing is written, removed or linked inside the
clone setup runs from, outside the home and the project of the run (a
provider's home named by its environment variable counts as the home), or
at a credentials file. --follow-config-symlinks writes through a link only
where the link leads to a place inside those; a place it leads out of is
skipped and named.

What is installed, for each provider that is installed (its program is on
PATH, or its home exists):

    skills   a link for every skill whose "compatibility" line names the
             provider: in the skills directory of the Claude Code home, and
             in ~/.agents/skills for Codex. The link has the skill's name and
             leads to the skill's directory in the clone. A skill that names
             one provider is linked for that one only.
    rules    a link for every directory in the clone's rules/, in the rules
             directory of the Claude Code home. Codex has no such place.
    roles    a generated file for every role definition, in the agents
             directory of the provider's home: <definition>.md for Claude
             Code, <definition>.toml for Codex. Never a link: Codex refuses a
             linked role file.
    entry    how a session becomes a role: a generated skill for every role
             that can be loaded, and for Codex a profile file for the role a
             session starts as. See "Entry points" below.

Role definitions. A role's sources are roles/<role>/ROLE.md and role.toml in
the clone. Claude Code gets a definition for every role that can be
dispatched or can be the role a session starts as ("dispatch" or "start"
under [entry]); Codex gets one for every role that can be dispatched. A role
with [profile.hard] gives a second definition, <role>-hard. A definition
holds the role's text, its shared sections, its rows of roles/bindings.toml
and the provider's action notes, and begins with a notice that it is
generated and from what. Its model and effort come from the role's profile
and the user-level settings (~/.agents/workflow.toml); a project's settings
are not used for a home. Where a role may not change files, run commands or
dispatch, the Claude Code definition denies the tools (Edit, Write,
NotebookEdit; Bash, PowerShell, Monitor; Agent), and the Codex definition
asks for a read-only sandbox where the role may not change files. A role
that may not dispatch is denied both tools that start an agent, Agent and
Workflow. A role whose profile has cache = "long" waits between its turns, on
the user or on agents it dispatched: the Product Manager, the Architect, the
Implementation Manager and the two document reviewers. Its Claude Code
definition names the one-hour
prompt cache (experimental.cacheTtl: 1h), where a dispatched role is
otherwise on the five-minute one; a one-hour cache write is billed at a
higher rate, and Claude Code's own subagentPromptCacheTtl setting or
CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL variable overrides the definition.
Codex has no such key. The size of each definition, with its model and
effort, and its cache where it names one, is in the output.

Entry points. A role is given to a session in one of two ways, by "load" and
"start" under [entry] in its role.toml.

    load     The role as a skill of the role's name, in the provider's skills
             directory: <role>/SKILL.md and <role>/agents/openai.yaml,
             generated files and not a link. The user loads it with /<role>
             on Claude Code and $<role> on Codex. Neither provider loads it by
             itself: each copy has "disable-model-invocation: true" and
             "policy.allow_implicit_invocation: false". It holds what the
             role's definition holds, and before it that loading a role
             suspends any other, and the role's model and effort. No skill
             switches a session's model (on Claude Code a skill's model
             "applies for the rest of the current turn"; a Codex skill has no
             model setting), so the role tells the user how to switch: /model
             and /effort on Claude Code, /model on Codex. A role whose name is
             a skill of the clone, or multiagent-collab, stops the run before
             anything is written.
    start    Claude Code: "claude --agent <role> --effort <level>", served by
             the role's definition in the agents directory; nothing more is
             generated. The command names the role's effort because, as
             Claude Code documents it, a session takes the prompt, tools and
             model of the definition it starts as and not its effort: the
             effort comes from CLAUDE_CODE_EFFORT_LEVEL, --effort or
             /effort, then the effortLevel setting, then the model's default
             (code.claude.com/docs/en/model-config, read 2026-10-11). That
             is read from the documentation: no session has shown it yet,
             and naming the effort costs nothing if the definition's is
             taken after all. A role
             whose model takes no effort setting gets the command without
             --effort, and the output says so.
             Codex: "codex --profile <role>", which reads the generated file
             <role>.config.toml in the Codex home, a layer over config.toml
             there. It holds model, model_reasoning_effort and
             developer_instructions. The user's config.toml is not touched.
             Codex writes into that file, after setup's part: the answer
             to "trust this project?" as a [projects."<path>"] table,
             flags of its interface. render carries whatever follows
             setup's part over each time it writes the file, and it counts
             as no hand edit unless it sets one of setup's keys.

A loaded role and a long session. After a compaction Claude Code re-attaches
an invoked skill "keeping the first 5,000 tokens of each", and "Re-attached
skills share a combined budget of 25,000 tokens"
(code.claude.com/docs/en/skills, read 2026-10-05). The size of each loaded
role is in the output with an estimate of its tokens, one per three bytes,
which errs high; one that is likely over 5,000 is marked LONG, on either
provider: the figure is Claude Code's, and the project's own rule for a
loaded role on Codex, which cuts nothing. It is still written: what would be
cut is its end, the role's binding rows and the provider's action notes.
"validate" refuses a shipped role over the figure with the shipped settings,
so a mark here comes from the user's settings; "doctor" says the same
(loaded-skill-size).

The project (--project DIR). Without it nothing is written in any project.
With it the homes are installed and refreshed exactly as without it, from the
user-level settings, and DIR gets, from its own settings
(DIR/.agents/workflow.toml and workflow.local.toml over the user's):

    - A role definition in DIR/.claude/agents and DIR/.codex/agents for each
      definition the project's settings change, a [roles.<id>] override or a
      model for one. A project's definition replaces the user-level one of
      the same name on both providers. A project that changes none gets
      none, and a change for one role writes that role's files alone: no
      other generated file, in the home or the project, changes.
    - With roles.manager_default = true, the role with "start = true" as the
      default of every session in the project. Claude Code: "agent":
      "<role>" in DIR/.claude/settings.json, and "effortLevel": "<level>"
      beside it, the role's effort, under the same rules; only those two
      keys are touched. A value a key already has, which setup did not
      set, is kept and reported, with exit code 3: --overwrite-edited
      replaces it, and it comes back when setup takes its key out. The
      effortLevel setting takes low, medium, high and xhigh and not max:
      for a starting role whose effort is max, or whose model takes no
      effort setting, it is not set and the output says why, and one an
      earlier run set is taken out. While "agent" has a value that is
      not setup's and is kept, the project's sessions do not start as the
      role: effortLevel is then not set for the first time, and one an
      earlier run set is left as it is, with a note. A project's
      effortLevel applies to every session in the project, whatever it
      starts as, and it wins over a level saved in the user's own
      settings; --effort and /effort win over it. Codex: model,
      model_reasoning_effort and developer_instructions in a marked block at
      the head of DIR/.codex/config.toml, the rest of the file kept byte for
      byte. Codex reads a project's config only when the project is trusted,
      and there it wins over a profile. If the file already sets one of the
      three keys outside the block, nothing is written and the run stops:
      a key cannot be set twice, and the user's value stays in effect. No
      role, or more than one, with "start = true" stops the run as well.
    - Nothing for a loaded role. Its skill is installed at the user level,
      and a provider's own skill wins over a project's of the same name, so
      a project cannot override it: the loaded skill keeps the user-level
      model and effort. Where the project's settings give a loaded role
      another profile the output says so, with both; "show roles --project
      DIR" prints the project's.
    - The generated files are listed in setup's block of DIR/.gitignore,
      with .agents/workflow.local.toml and the project's state directory,
      DIR/.agents/workflow-setup/ (its install record, its backups and its
      lock). A block that is already there and holds a line setup does not
      write is yours: it is kept and reported, with exit code 3, and
      --overwrite-edited writes it. The key and the block are not
      listed: they are setup's part of files the project owns and may
      commit.

Turning roles.manager_default off, removing an override, --no-roles or
roles.enabled = false makes what an earlier run wrote for it stale: the next
run with --project removes it, and a directory setup created that this
leaves empty.

A provider that is installed and has no dictionary in the clone, or a
profile that names an effort its model does not accept, stops the run before
anything is written.

A generated file is written only where nothing is, or where the install
record shows that setup wrote the file. One that was edited by hand since is
kept and reported, the exit code is 3, and the rest of the run is done:
--overwrite-edited backs the file up and replaces it; removing the file and
running render again writes it anew.

A key or a block that was changed by hand since setup wrote it is kept and
reported in the same way, with exit code 3. So is what setup never wrote: a
key that has a value of yours, and a pair of setup's markers that the
install record does not hold, with other text between them than setup
writes (as after the state directory was removed by hand). Such a block is
your text until --overwrite-edited replaces it, after a backup of the file;
one that holds exactly what setup writes is taken up into the record, and
nothing in the file changes.

What --overwrite-edited replaces in a key or a block is yours, and is not
lost: the install record keeps it, and when setup's key or block goes
(`uninstall`, or a later render that no longer writes it) your value or
your text is put back in its place, and the file stays. Where it cannot be
put back in its place (the key or the block was changed again or is gone,
or text of yours was replaced there more than once), the backup that holds
it is never removed by setup: the output names it with its path, and
`uninstall` ends with 3 while it is there. A block whose lines are setup's
own and differ only in their line endings, in a file whose line endings
were changed as a whole (LF to CRLF or back), is not an edited block:
`render`, `doctor` and `uninstall` all take it for setup's.

--no-roles installs the process alone: no role definition and no entry point
is generated, in a home or a project. What an earlier run generated is then
removed, like any file or link that render would no longer make, and one
that was edited by hand is kept and reported. Running render without the
option generates them again.

The setting roles.enabled = false does the same on every run, without the
option: `init --no-roles` writes it, or it is set in the settings file. For
the home it is read from ~/.agents/workflow.toml; for the project from the
project's settings (DIR/.agents/workflow.toml and workflow.local.toml over
the user's), so a project can turn the roles off for itself. A project gets
roles only where the home has them: what it gets is built on the home's
definitions. --no-roles wins over the setting for its run. There is no
option that turns the roles on against the setting: what one run generated
the next run would remove again. Set roles.enabled = true (`init --roles`)
and run render. The output says when the roles are off, and whether by the
option or by the setting, in which file.

A run without --project writes nothing in a project, and setup keeps no
list of the projects it rendered (each project's record is in the
project). So when the home's roles go off, by the option or the setting, a
project rendered with roles keeps what render wrote there: the starting
role of roles.manager_default ("agent" in .claude/settings.json, setup's
block in .codex/config.toml), which names a definition the home no longer
has, and its own definitions. Run `render --project DIR` for each such
project to take them out; the output, and `doctor`, say so.

What is not written, and is reported:

    - A skill with a setup of its own (multiagent-collab): left alone,
      whatever is at its path.
    - A provider that is not installed: nothing is installed for it.
    - A place whose real path is on the other side of the machine (a link
      from the WSL home into the Windows home, or the reverse): skipped, the
      run on that side writes it.
    - A place that is, or lies under, a link to elsewhere on this side,
      inside the home: skipped unless --follow-config-symlinks is given,
      and the exit code is then 3. Where the link leads out of the home
      (or, in a project, out of the project): skipped with every option,
      and said so; that alone does not change the exit code.
    - A place that is a clone of this repository, or a link that leads
      into one (a skills directory linked to the clone itself): skipped
      with every option. Setup writes nothing into a clone, and nothing at
      all inside the clone it runs from.

A link is created only where nothing is, or where the install record shows
that setup made the link there. Anything else is a conflict: a file, a
directory, a link setup did not make (a link to another home's copy among
them), or setup's own link pointed elsewhere since. One conflict stops the
run before anything is written, for either provider; each is printed on a
line of its own, naming what is there.

A link that an earlier run made and this run would no longer make (the skill
left the clone, or no longer names that provider) is removed, if it still
points where setup pointed it. One that was changed since is kept and
reported. The same holds for a generated file whose role left the clone, or
whose provider is no longer installed: removed if it still holds what setup
wrote, kept and reported if it was edited.

Codex settings (--apply-codex-settings). Without the option render writes
nothing into the user's Codex config.toml. With it, the settings the
framework needs on Codex go into blocks between setup's markers in that
file, and every byte outside the markers stays as it is:

    - agents.max_concurrent_threads_per_session = 8, in an [agents] table in
      the block "codex-settings" at the end of the file. A limit the file
      already sets, by that key or by its legacy alias agents.max_threads,
      is reported and left alone, whatever its value. A file with an
      [agents] table of its own that lacks the key gets nothing: TOML allows
      a table to be defined once, so the one line to add is printed. A file
      that sets other agents.* keys at its top level gets the limit as a
      dotted key in the block "codex-settings-top" at the head of the file.
    - The permission profile "workflow" (permission profiles are beta in
      Codex): [permissions.workflow], which extends ":workspace" and makes
      ".git" writable under ":workspace_roots", in the block at the end.
      With --worktree-root DIR it also makes DIR writable. DIR is an
      absolute path, written without "." and ".." parts, or one that starts
      with ~/, written with / between its parts. A relative path, the root
      of the file system and the home directory itself are refused. It is
      the one path of this machine in the block, it is there because you
      gave it, and it is recorded nowhere else. While the file sets sandbox_mode no profile is written: Codex
      then uses the older sandbox settings and ignores default_permissions.
      The profile is printed instead, with what you would change, and
      sandbox_mode is never changed or removed.
    - The profile is defined and not selected. --default-codex-permissions
      also writes default_permissions = "workflow", in the block at the
      head of the file, where a top-level key must be. A default_permissions
      the file already sets, and a profile named "workflow" of your own,
      are reported and left alone.

The blocks stay: a later render without the option does not touch them, and
--remove-codex-settings takes them out where they still hold what setup
wrote. A run with the option writes what its options say, so leaving out
--worktree-root or --default-codex-permissions takes that part out again,
and says which option's absence took it out. The file is backed up before
it is changed: a full copy, with everything the file holds, under
~/.agents/workflow-setup/backups/ (for a project's file, under
DIR/.agents/workflow-setup/backups/). A file that is not valid TOML is refused
by the position of the fault alone. A block edited by hand is kept and
reported, with exit code 3. "doctor --only
codex-settings" says, without writing, what this option would do now.

A second run with the same inputs plans nothing and writes nothing, and says
so. What was made is listed in ~/.agents/workflow-setup/manifest.json, and
what was made in a project in DIR/.agents/workflow-setup/manifest.json, by
anchor ("home:", "clone:", "project:") and not by this machine's paths.

The output: the clone, with what allowed it where only this side reads it;
whether the roles are off, and why; for each provider its home, each place
and what became of each
link and each generated file; what is no longer installed; the plan, one
line per change; and one line that sums it up. With --json it is one object
with the same facts ("unshared_clone", "roles", "providers", "definitions",
"entry_points", "project", "stale", "plan", "errors", "counts", "summary",
"exit_code"); "unshared_clone" is null unless a clone only this side reads
was allowed, and then holds "why", "allowed_by" ("setting" or "option"),
"said" (the line printed) and "setting"; "roles" holds "enabled", "off_by"
("option", "setting" or null) and "setting" (the effective roles.enabled:
"value", "layer", "file"; null under --no-roles, when no settings file is
read for it), and "project" has its own "roles", where "off_by" may also be
"home"; "definitions"
lists every role definition with its provider, file, bytes, model, effort,
status and level (home or project); "entry_points" lists how each role is
loaded or started on each provider, with the file, its bytes and for a
loaded role the token estimate; "project" is null without --project, and
otherwise holds what the project got and, as "loaded_roles", each loaded
role whose profile the project's settings change, and as "session_effort"
the effort of a Claude Code session that starts as the starting role: the
role's model and effort, "setting" (what effortLevel is set to, or null) and
"why" (why it is not set, or null).

Migrating v1 (--migrate-v1). Without the option render removes nothing a v1
install left, and stops on one that is in the way of a link. With it, in the
same plan as everything else and so with the same dry run and backups, for
each home this run may write:

    - In the Claude Code CLAUDE.md the lines "@rules/prd-implementation.md"
      and "@rules/epic-implementation.md" are removed, exactly those and
      only as whole lines, and a marked block is added at the end that
      points to the two skills. This is the one place setup edits a user's
      text outside a marked block. The Codex AGENTS.md gets the same block;
      another tool's block in it is not touched. A file that is not there
      is created with the block alone.
    - The v1 rule files in the Claude Code rules directory
      (prd-implementation.md, epic-implementation.md and the loose
      avoid-bash-injection-heuristics.md), agents/sprint-coder.md, and the
      loose copies of the v1 skills in the skills directories, with Codex's
      deprecated <codex home>/skills among them, are removed when they are
      known: a regular file whose content is a committed version of the v1
      file (the hashes are in tools/setup/v1-known-hashes.json, for LF and
      CRLF line endings); a skill directory in which every file is one and
      which holds nothing else but the __pycache__ of its scripts. Every
      removed file is backed up first.
    - A link is removed as a link and never followed, and without being
      asked for only in these cases: it leads to a known copy (every file a
      committed version, wherever the copy is), or into the clone this
      command runs from, or nowhere at a path inside that clone, which
      moved on to v2. A link into any other tree (another clone, a git
      tree of your own that holds a skill of a v1 skill's name) is kept and
      reported; --remove-stale PATH removes it. A link whose text names a
      credentials file is never removed, with the option or without.
    - Anything else at one of those places is kept and reported with what
      differs: a copy edited by hand, a link setup does not recognise. The
      exit code is then 3, and "doctor" reports the item as an error until
      you decide. --remove-stale PATH (repeatable) removes the one named,
      after a backup; the dry run prints the option for each. It removes
      only what the dry run names at a v1 place: any other path stops the
      run.
    - A git clone inside a skills directory is never removed, with or
      without --remove-stale. It is reported, and is yours to move away. A
      skills directory that is a clone, or is a link that leads into one
      (the clone setup runs from among them), is left alone as a whole:
      nothing in it is removed or linked, with any option.
    - A migration that was interrupted is finished by running the same
      command again: a copy whose files were already removed is known by
      the install record, and what is left of it is removed.
    - A place the other side of the machine owns is skipped and reported,
      as always; run the migration on that side too.

Where migration removes a copy or a link at a path that render then links, the
install record keeps both, and undoing the install puts the copy or the link
back. Whenever a rule copy is to be removed the run warns that a project
whose .claude/rules/ links to it will be left with a dangling link: setup
does not know which projects do, and does not migrate a project. A second run
with the same options plans nothing. "migration" in the --json output lists
each item with its status ("remove", "edit", "up-to-date", "kept",
"never-removed", "skipped", "needs-flag") and the warnings; it is null
without the option.

Known limit. A Cowork session on the desktop does not load a linked
user-level rule: there Claude Code skips "a symlinked ~/.claude/rules/
directory or rule file that points outside the working directory"
(code.claude.com/docs/en/memory, read 2026-10-05). The page names the rules
directory and a rule file; a linked directory inside rules/, which is what
this command makes, is taken to be skipped the same way. Every other Claude
Code session loads the rule through the link.

Known limit. The guards on where setup writes (never inside the clone, at
a credentials file, or outside the home and the project) hold against the
disk as the run finds it, not against another program that changes the
same directories while the run is under way.

Exit code 0 when the plan was applied or there was nothing to do; 2 on an
error or a conflict, printed to stderr: nothing was written where the plan
was refused, and where a change failed while it was applied the error says
how many were made; 3 when the rest was done (or, with --dry-run, would be)
and at least one path was skipped that --follow-config-symlinks would write,
or one generated file, key or block was kept that --overwrite-edited would
replace, or one v1 copy or link was kept that --remove-stale would remove;
130 when interrupted with Ctrl-C, and 128 plus the signal's number when told
to end by a signal (143 for SIGTERM): what was changed until then is
recorded, and the next run goes on; 141 when the reader of the output went
away.
"""
from __future__ import annotations

import argparse
import json

from .. import fileops, homes, locations, render, validate
from ..errors import SetupError

SUMMARY = (
    "link the clone's skills and rules into the providers' homes, generate the role definitions and the "
    "entry points, and with --project what a project gets"
)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument(
        render.OVERWRITE_OPTION,
        action="store_true",
        help="replace a generated file, a key or a block that was edited by hand since setup wrote it, or that "
        "setup did not write (a project's own `agent` or `effortLevel` value; setup's markers with other text between them), "
        "after a backup of the file. Without it such a thing is kept and reported, with exit code 3",
    )
    locations.add_arguments(parser)
    fileops.add_arguments(parser)
    homes.add_arguments(parser)
    for part in render.PARTS:
        part.add_arguments(parser)


def run(args: argparse.Namespace) -> int:
    where = locations.from_args(args)
    sources = validate.require(where)
    found = homes.resolve(where)
    allowance = homes.clone_allowance(where, args.allow_unshared_clone)
    standing = homes.require_shared_clone(found, allowance.allowed)
    outcome = render.execute(
        found, sources, args, dry_run=args.dry_run, follow=args.follow_config_symlinks,
        overwrite_edited=args.overwrite_edited, unshared_clone=render.unshared_clone(standing, allowance),
    )
    if args.json:
        print(json.dumps(outcome.report, indent=2, ensure_ascii=False))
    else:
        for line in render.report_lines(outcome.report):
            print(line)
    if outcome.errors:
        raise SetupError(*outcome.errors)
    return outcome.code
