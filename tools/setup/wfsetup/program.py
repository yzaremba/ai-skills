"""Install the clone's skills, rules and roles into the providers' homes, and
into a project.

    setup.py [DIR] [--yes | --dry-run] [--json] [--provider NAME]...
             [--overwrite-edited] [--home DIR] [--follow-config-symlinks]
             [--allow-unlisted] [--no-versions] [--codex-probe] [--no-collab]
             [--install NAME...] [--reset KEY]... [--rewrite-settings]
             [--tier PROVIDER:TIER=MODEL]... [--effort PROVIDER:NAME=VALUE]...
             [--role-model PROVIDER:ROLE=MODEL]... [--docs-dir DIR]
             [--questions HOW] [--recommend | --no-recommend]
             [--manager-default | --no-manager-default] [--high-stakes |
             --no-high-stakes] [--max-parallel-coders N] [--memory-dir DIR]
             [--codex-settings off|on|profile] [--worktree-root DIR]
    setup.py --check [DIR] [--json] [--home DIR] [--only NAME]... [--skip NAME]...
             [--no-versions] [--no-collab] [--codex-probe]
    setup.py --uninstall [DIR] [--home DIR] [--dry-run] [--json]
             [--follow-config-symlinks] [--keep-settings | --discard-backups [--yes]]

Without DIR the run is about this machine's homes, the Claude Code home and
the Codex home that are installed. With DIR it is about the project at DIR
as well: the homes are installed and refreshed exactly as without it, and
the project gets what its own settings (DIR/.agents/workflow.toml and
workflow.local.toml over the user's) ask for. The project is only ever DIR,
never the working directory.

The settings file. A value given by flag is written to the settings file of
the run, ~/.agents/workflow.toml, or with DIR DIR/.agents/workflow.toml; a
value accepted as shown is not, and a second run with the same flags writes
nothing. The home's file holds the tier and effort mapping of each installed
provider in full, as the run confirmed it: a home run whose file lacks them,
a first one among them, writes the mapping of each installed provider, and a
later update of the clone's dictionaries does not change it. A project's file
holds only what a flag stated, since what it leaves out is each user's own.
--install NAME... is the whole list of what is installed (skills and rules of
the clone by name, and `roles`), replacing the file's; --reset KEY takes a key
out of the file, so that the layer below gives it again. The file is checked
before it is written: each value by the settings schema, each mapped model
against the provider's own list where one can be read (`codex debug models`;
an unlisted model is an error unless --allow-unlisted keeps it), and each
effort against what the model accepts. The install is planned and checked on
the file as it will be, before either is written, and a plan that is refused
writes neither; then the settings are written first, after the clone check
and under the same lock as the install; --dry-run shows both plans and
writes neither. A file that was written or edited by hand is rewritten from its
values (every key kept, comments and layout not) only with --yes together
with --rewrite-settings, after a backup of it; a file that holds an old key
stops the run, and the file written holds none. Where such a file lacks only
an installed provider's tier or effort mapping, a run adds the mapping at its
end, its lines as they are, after a backup, with no --rewrite-settings.

In this order: the clone's sources are checked (the check that
tools/setup/validate.py runs alone), and any problem stops the run; the
homes are found, a provider named by --provider counting as installed; on a
Windows machine a clone off a local drive stops the run, and on a machine
with a Windows side and a WSL side a clone the Windows side cannot read gives
one warning line; then one plan is made, printed, and applied. The whole
plan is checked before the first write, so a plan that is refused writes
nothing. Applying it is not atomic: if a change fails part way, the changes
before it stay and are recorded, the error says how many, and the next run
goes on from there.

Without --yes and --dry-run, on a terminal, setup shows one numbered screen:
where the run is about (this machine, or the project), the items to install,
for a project whether its sessions start as the Manager, the process and
memory settings, the roles settings, each installed provider's tiers and
efforts, and for this machine the Codex config item, each with its value
now and the layer and file it comes from. Enter shows the plan, file by file,
and asks "Apply? [Y/n]": n ends the run with exit code 1 and writes nothing.
Numbers (3 5) open those options and show the screen again; r and numbers
(r 3 5) take those keys out of the file the run writes, so that the layer
below gives them again. A value changed there is written, a value accepted as
shown is not. An old key is named on the screen with what replaces it, and
the settings file the run writes does not hold it. The items line asks for
a checklist of the clone's skills, the rule and `roles` (a needed item ticked and marked, and held ticked while what needs it is; on a project's screen the home's items marked "from this machine" and held ticked) and the Codex item for off, on or on with the profile, then the worktree
root. A generated file, key or block edited by hand since setup wrote it is
asked about when the plan is made ("replace, after a backup? [y/N]"), and the
plan is made again with the answers; one not replaced is kept and reported,
with exit code 3. A run
is applied with --yes, or shows its plan with --dry-run and writes nothing;
without either and without a terminal it stops and names --yes. An
unattended run (--yes, --dry-run or no terminal) that finds a key a settings
file holds under an old name stops, with the key, its file and what replaces
it, and nothing is written.

What is installed, for each provider that is installed (its program is on
PATH, or its home exists, or --provider names it); a provider that is not
installed gets nothing. No provider installed and none named is an error
that names --provider. The run assumes no user but the one it runs as:
running as root on Linux, with no terminal, is the same as any other run.

    skills   a link for every skill whose "compatibility" line names the
             provider: in the skills directory of the Claude Code home, and
             in ~/.agents/skills for Codex. The link has the skill's name and
             leads to the skill's directory in the clone. A skill that names
             one provider is linked for that one only.
             With DIR, the skills the project lists (install in its settings
             files, with the skills they need) are linked the same way into
             DIR/.claude/skills and DIR/.agents/skills, and listed in the
             project's ignore block; a skill the home installs is skipped.
             The link is a junction on Windows; from WSL, in a project on a
             Windows drive, a relative link where the clone is on the same
             drive, none where it is on another (run setup from Windows),
             and an absolute link where the clone is in the Linux file
             system. A link already at a project's path that leads to the
             skill's directory is kept: the other side's link, whatever its
             form, or one made by hand, which setup takes over. Anything else
             there is a conflict. A link of a skill that left the list is
             removed; one the other side may have made, of a skill still
             listed, is left to it.
    rules    a link for every directory in the clone's rules/, in the rules
             directory of the Claude Code home. Codex has no such place.
             With DIR, the rules the project lists are copied, not linked,
             into DIR/.claude/rules/<name>/ (Claude Code only), and the copy
             follows the clone on every run. A rule the home installs is not
             copied.
    roles    a generated file for every role definition, in the agents
             directory of the provider's home: <definition>.md for Claude
             Code, <definition>.toml for Codex. Never a link: Codex refuses a
             linked role file.
    entry    how a session becomes a role: a generated skill for every role
             that can be loaded, and for Codex a profile file for the role a
             session starts as. See "Entry points" below.

Where the run renders the Codex home (Codex installed, its program on PATH),
it starts the list command of Codex's dictionary (`codex debug models`, also
with --dry-run), a program of the provider's that may write state of its own
into its home, and ends the output with a note on the models the list offers
and the dictionary lacks. A list that cannot be read is one line, and neither
changes the exit code.

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
the user or on agents it dispatched: its Claude Code definition names the
one-hour prompt cache (experimental.cacheTtl: 1h), where a dispatched role is
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
             switches a session's model, so the role tells the user how to
             switch: /model and /effort on Claude Code, /model on Codex. A
             role whose name is a skill of the clone, or multiagent-collab,
             stops the run before anything is written.
    start    Claude Code: "claude --agent <role> --effort <level>", served by
             the role's definition in the agents directory; nothing more is
             generated. The command names the role's effort because a
             session takes the prompt, tools and model of the definition it
             starts as and not its effort: the effort comes from
             CLAUDE_CODE_EFFORT_LEVEL, --effort or /effort, then the
             effortLevel setting, then the model's default
             (code.claude.com/docs/en/model-config, read 2026-10-11). That is
             read from the documentation: no session has shown it. A role
             whose model takes no effort setting gets the command without
             --effort, and the output says so.
             Codex: "codex --profile <role> --no-daemon", which reads the
             generated file <role>.config.toml in the Codex home, a layer
             over config.toml there. That file holds model,
             model_reasoning_effort and developer_instructions. A profile
             session runs without the shared background server anyway;
             --no-daemon says so and silences Codex's warning about it. The
             user's config.toml is not touched. Codex writes into that file,
             after setup's part (the answer to "trust this project?" as a
             [projects."<path>"] table, flags of its interface): setup
             carries whatever follows its part over each time it writes the
             file, and it counts as no hand edit unless it sets one of
             setup's keys.

A loaded role and a long session. After a compaction Claude Code re-attaches
an invoked skill "keeping the first 5,000 tokens of each", and "Re-attached
skills share a combined budget of 25,000 tokens"
(code.claude.com/docs/en/skills, read 2026-10-05); the figure is
skills.compaction_tokens in providers/claude-code/dictionary.toml. The size
of each loaded role is in the output with an estimate of its tokens, one per
three bytes, which errs high; on Claude Code one that is likely over 5,000
is marked LONG. Codex documents no such cut, so there the size is shown and
nothing is marked. A LONG role is still written: what would be cut is its
end, the role's binding rows and the provider's action notes.

The project (DIR). Without DIR nothing is written in any project. With it
the homes are installed and refreshed exactly as without it, from the
user-level settings, and DIR gets, from its own settings (DIR/.agents/
workflow.toml and workflow.local.toml over the user's):

    - A role definition in DIR/.claude/agents and DIR/.codex/agents for each
      definition the project's settings change, a [roles.<id>] override or a
      model for one. A project's definition replaces the user-level one of
      the same name on both providers. A project that changes none gets
      none, and a change for one role writes that role's files alone.
    - With roles.manager_default = true, the role with "start = true" as the
      default of every session in the project. Claude Code: "agent":
      "<role>" in DIR/.claude/settings.json, and "effortLevel": "<level>"
      beside it, the role's effort; only those two keys are touched. A value
      a key already has, which setup did not set, is kept and reported, with
      exit code 3: --overwrite-edited replaces it, and it comes back when
      setup takes its key out. The effortLevel setting takes low, medium,
      high and xhigh and not max: for a starting role whose effort is max,
      or whose model takes no effort setting, it is not set and the output
      says why, and one an earlier run set is taken out. While "agent" has a
      value that is not setup's and is kept, effortLevel is not set for the
      first time, and one an earlier run set is left as it is, with a note.
      A project's effortLevel applies to every session in the project,
      whatever it starts as, and it wins over a level saved in the user's
      own settings; --effort and /effort win over it. The two keys are
      set, changed and taken out only by a run that writes DIR/.agents/
      workflow.toml, as a flag that changes a value of it does, or one given
      --manager-default or --no-manager-default. Any other
      run, a refresh, leaves them as they are, set or not, with what the
      install record holds of them, even where the home's mapping now gives
      the role another effort, and a note says so: .claude/settings.json is
      tracked, and one user's mapping is not the project's. Codex: model,
      model_reasoning_effort and developer_instructions in a marked block at
      the head of DIR/.codex/config.toml, the rest of the file kept byte for
      byte. Codex reads a project's config only when the project is trusted,
      and there it wins over a profile. If the file already sets one of the
      three keys outside the block, nothing is written and the run stops: a
      key cannot be set twice, and the user's value stays in effect. No
      role, or more than one, with "start = true" stops the run as well.
    - Nothing for a loaded role. Its skill is installed at the user level,
      and a provider's own skill wins over a project's of the same name, so
      a project cannot override it: the loaded skill keeps the user-level
      model and effort. Where the project's settings give a loaded role
      another profile the output says so, with both.
    - The generated files are listed in setup's block of the repository's
      exclude file, info/exclude in its git directory (DIR/.git/info/exclude,
      or the common one of a linked worktree, which all its worktrees
      read), with .agents/workflow.local.toml and the project's state
      directory, DIR/.agents/workflow-setup/ (its install record, its
      backups and its lock). Nothing is listed in .gitignore, and setup
      never edits it: setup's block there from an earlier version is named,
      with its file and lines, for you to remove, and its record entry is
      forgotten. A DIR that is
      no git repository's top gets no list, and a note says why. A block
      that is already there and holds a line setup does not write is yours:
      it is kept and reported, with exit code 3, and --overwrite-edited
      writes it. The key and the block are not listed: they are setup's
      part of files the project owns and may commit. A .codex/config.toml
      that setup created is listed; one that was there before never is.

With roles.manager_default = true, the Codex block in DIR/.codex/config.toml
is written only where git does not track that file (git -C DIR ls-files
--error-unmatch). Where git tracks it, or git cannot be started, nothing is
written there and a line says that Codex sessions in the project will not
start as the Manager; setup's block already in a tracked file is named, with
its lines, for you to remove, its record entry is forgotten and the file is
never edited.

After applying (not with --dry-run or --json), setup prints the git add and
git commit lines for DIR/.agents/workflow.toml and DIR/.claude/settings.json
when the run wrote them (it commits nothing; a file the run took out again
is listed only if git tracks it), and on a Windows and WSL machine one line
with the command for the other side (py -3 and Windows paths from WSL;
python3 and WSL paths from Windows), only where the clone is on a drive both
sides read, not on a --home run and not after a refused run. It runs no
check.

Turning roles.manager_default off, removing an override, or taking `roles`
out of the home's `install` makes what an earlier run wrote for it stale: the
next run with DIR removes it, and a directory setup created that this leaves
empty. The two keys of .claude/settings.json go only with a run that writes
DIR/.agents/workflow.toml, or one given --manager-default or
--no-manager-default (even where the file already holds that value); any
other run leaves them.

The roles are an item of `install`. They are on when the home's effective
`install` (~/.agents/workflow.toml over the shipped one) holds `roles`. When
it does not, the process alone is installed: no role definition and no entry
point is generated, in a home or a project. What an earlier run generated is
then removed, like any file or link that setup would no longer make, and one
that was edited by hand is kept and reported. A project gets roles only where
the home has them: what it gets is built on the home's definitions. `roles`
in a project's own `install` where the home has none is a note, and nothing
of the roles is installed for the project. The output says when the roles are
off, and in which file. A run without DIR writes nothing in a project, so
when the home's roles go off, a project set up with roles keeps what setup
wrote there (the starting role of roles.manager_default, which names a
definition the home no longer has, and its own definitions) until a run with
that DIR takes them out; the starting role's keys in .claude/settings.json,
until a run with that DIR writes its .agents/workflow.toml or is given
--manager-default or --no-manager-default.

A provider that is installed and has no dictionary in the clone, or a
profile that names an effort its model does not accept, stops the run before
anything is written.

A generated file is written only where nothing is, or where the install
record shows that setup wrote the file. One that was edited by hand since is
kept and reported, the exit code is 3, and the rest of the run is done:
--overwrite-edited backs the file up and replaces it; removing the file and
running setup again writes it anew. A key or a block changed by hand since
setup wrote it is kept and reported in the same way, and so is what setup
never wrote: a key that has a value of yours, and a pair of setup's markers
that the install record does not hold, with other text between them than
setup writes. Such a block is your text until --overwrite-edited replaces
it, after a backup of the file; one that holds exactly what setup writes is
taken up into the record, and nothing in the file changes.

What --overwrite-edited replaces in a key or a block is yours, and is not
lost: the install record keeps it, and when setup's key or block goes your
value or your text is put back in its place, and the file stays. Where it
cannot be put back (the key or the block was changed again or is gone, or
text of yours was replaced there more than once), the backup that holds it is
never removed by setup: the output names it with its path. A block whose
lines are setup's own and differ only in their line endings, in a file whose
line endings were changed as a whole (LF to CRLF or back), is not an edited
block.

A link is created only where nothing is, or where the install record shows
that setup made the link there. Anything else is a conflict: a file, a
directory, a link setup did not make (a link to another home's copy among
them), or setup's own link pointed elsewhere since. One conflict stops the
run before anything is written, for either provider; each is printed on a
line of its own, naming what is there. A link that an earlier run made and
this run would no longer make (the skill left the clone, or no longer names
that provider) is removed, if it still points where setup pointed it; one
that was changed since is kept and reported. The same holds for a generated
file whose role left the clone, or whose provider is no longer installed.

What is not written, and is reported:

    - A skill with a setup of its own (multiagent-collab): left alone,
      whatever is at its path.
    - A provider that is not installed: nothing is installed for it.
    - A place whose real path is on the other side of the machine (a link
      from the WSL home into the Windows home, or the reverse): skipped, the
      run on that side writes it.
    - A place that is, or lies under, a link to elsewhere on this side,
      inside the home: skipped unless --follow-config-symlinks is given, and
      the exit code is then 3. Where the link leads out of the home (or, in
      a project, out of the project): skipped with every option, and said
      so; that alone does not change the exit code.
    - A place that is a clone of this repository, or a link that leads into
      one: skipped with every option. Setup writes nothing into a clone, and
      nothing at all inside the clone it runs from.

One run writes to a home at a time, and one to a project: a second one ends
at once with exit code 2 and names the run that holds the lock. A project has
its own lock, record and backups, in DIR/.agents/workflow-setup. A run that
was killed leaves its lock, its unfinished changes and perhaps a file under a
temporary name that its record lists; the next run that writes clears the
lock where that process is provably gone (else the message says how), settles
the changes from the disk, removes those temporary files, and says so. It
removes no backup. A lock taken on another system (a project on a Windows
drive, used from Windows and from WSL) is never cleared from here.

A second run with the same inputs plans nothing and writes nothing, and says
so. What was made is listed in ~/.agents/workflow-setup/manifest.json, and
what was made in a project in DIR/.agents/workflow-setup/manifest.json, by
anchor ("home:", "clone:", "project:", and "git-info:exclude" for the
repository's exclude file) and not by this machine's paths.

The output: the clone, with the warning where the Windows side cannot read
it; whether the roles are off, and why; for each provider its home, each
place and what became of each link and each generated file; what is no
longer installed; the plan, one line per change; and one line that sums it
up. With --json the report is the "install" object, with "clone_warning"
(null unless the Windows side cannot read the clone; on Windows a clone off a
local drive stops the run instead), "roles" ("on" and "file", the settings
file whose `install` decided it), "providers", "definitions" (every role
definition with its provider, file, bytes, model, effort, status and level),
"entry_points" (how each role is loaded or started on each provider, with the
file, its bytes and for a loaded role the token estimate), "project" (null
without DIR; otherwise what the project got, as "loaded_roles" each loaded
role whose profile the project's settings change, and as "session_effort" the
effort of a Claude Code session that starts as the starting role), "stale",
"plan", "errors", "counts", "summary" and "exit_code".

Known limit. A Cowork session on the desktop does not load a linked
user-level rule: there Claude Code skips "a symlinked ~/.claude/rules/
directory or rule file that points outside the working directory"
(code.claude.com/docs/en/memory, read 2026-10-05). The page names the rules
directory and a rule file; a linked directory inside rules/, which is what
setup makes, is taken to be skipped the same way. Every other Claude Code
session loads the rule through the link.

Known limit. The guards on where setup writes (never inside the clone, at a
credentials file, or outside the home and the project) hold against the disk
as the run finds it, not against another program that changes the same
directories while the run is under way.

The Codex config item (this machine's Codex home, not a project's). Without
--codex-settings setup writes nothing into the user's Codex config.toml that
the file's blocks do not already hold: the item is what the blocks between
setup's markers hold (off, on, or on with the profile, and the worktree
root), a run keeps it, and every byte outside the markers stays as it is.
With on, the settings the framework needs on Codex go into those blocks:

    - agents.max_concurrent_threads_per_session = 8, in an [agents] table in
      the block "codex-settings" at the end of the file. A limit the file
      already sets, by that key or by its legacy alias agents.max_threads,
      is reported and left alone, whatever its value. A file with an
      [agents] table of its own that lacks the key gets nothing: TOML allows
      a table to be defined once, so the one line to add is printed. A file
      that sets other agents.* keys at its top level gets the limit as a
      dotted key in the block "codex-settings-top" at the head of the file.
    - The wait floor: [features.multi_agent_v2] with min_wait_timeout_ms =
      300000 and default_wait_timeout_ms = 3600000, in the block at the
      end. Codex raises a wait_agent timeout below the floor to it, and a
      wait with no timeout waits the maximum. A file that defines anything
      at features.multi_agent_v2 (a table, dotted keys, an inline table or
      the feature's switch) gets nothing: its values are reported, with
      whether the floor is met, and the lines to add are printed.
    - The permission profile "workflow" (permission profiles are beta in
      Codex): [permissions.workflow], which extends ":workspace" and makes
      ".git" writable under ":workspace_roots", in the block at the end.
      With --worktree-root DIR it also makes DIR writable. DIR is an
      absolute path, written without "." and ".." parts, or one that starts
      with ~/, written with / between its parts. A relative path, the root
      of the file system and the home directory itself are refused. It is
      the one path of this machine in the block, it is there because you
      gave it, and it is recorded nowhere else. While the file sets
      sandbox_mode no profile is written: Codex then uses the older sandbox
      settings and ignores default_permissions. The profile is printed
      instead, with what you would change, and sandbox_mode is never
      changed or removed.
    - The profile is written only where default_permissions is set after
      the run: Codex (0.163.0) refuses to load a config that defines a
      profile and sets no default_permissions. profile writes it and
      default_permissions = "workflow", in the block at the head of the
      file, where a top-level key must be. With on the profile is written
      unselected where the file sets default_permissions itself (any value,
      a built-in among them), and otherwise printed as text, with what you
      would do. A default_permissions the file already sets, and a profile
      named "workflow" of your own, are reported and left alone. An earlier
      block that defines the profile with no default_permissions beside it
      is an error of "setup.py --check --only codex-settings"; a run with on takes
      the profile out of it.
    - The Manager's pin: where the Manager is installed for Codex as a
      loadable role, model and model_reasoning_effort, its resolved Codex
      model and effort, in the block at the head of the file. Every plain
      codex session in the home then starts on them. A file that sets
      either key itself gets neither, and the lines to delete are named by
      their numbers. With no Manager to pin, a run takes them out again.

An option changes only its own part: --codex-settings on writes the blocks
and leaves the profile unselected, profile selects it, off takes the blocks
out where they still hold what setup wrote; --worktree-root alone changes
the root of an item that is on, and is an error while the item is off. The
file is backed up before it is changed, under ~/.agents/workflow-setup/
backups/. A file that is not valid TOML is refused by the position of the
fault alone. A block edited by hand is kept and reported, with exit code 3.
"setup.py --check --only codex-settings" says, without writing, what a run would do now.

Options:

    DIR                     the project (optional)
    --yes                   apply the plan with no question; the only way to
                            apply without a terminal
    --dry-run               print the plan, change nothing
    --json                  print one JSON object: "schema_version",
                            "settings" (every setting with its value, layer
                            and file, and "install": the list of each layer
                            that gives one) and "install" (the report: "clone",
                            "clone_warning", "roles", "providers",
                            "definitions", "entry_points", "project",
                            "stale", "plan", "errors", "counts", "summary",
                            "exit_code"). Needs --yes or --dry-run
    --provider NAME         install for NAME (claude-code or codex) although
                            its program and home are not there yet: its home
                            is created. May be repeated; adds to the
                            providers setup finds
    --overwrite-edited      replace a generated file, a key or a block that
                            was edited by hand since setup wrote it, after a
                            backup of the file. Without it such a thing is
                            kept and reported, with exit code 3;
                            on the screen each one is asked about instead
    --home DIR              use DIR in place of the user's home directory
                            (for trial runs): the providers' homes are then
                            DIR/.claude and DIR/.codex
    --follow-config-symlinks
                            write through a config path that is a link, or
                            lies under one, where the link leads to a place
                            inside the home or the project
    --allow-unlisted        keep a mapped model that the provider's own list
                            does not hold, instead of refusing it
    --rewrite-settings      with --yes: also rewrite a settings file that was
                            written or edited by hand, after a backup of it
    --install NAME...       what is installed: the whole list, replacing the
                            file's (`roles` is the role definitions and entry
                            points); give it after DIR, not before
    --reset KEY             take KEY out of the file, so that it follows the
                            layer below again: a setting, `install`, any other
                            key the file holds, or a provider's tier, effort or
                            role model (not a tier or effort in the home's
                            file, which holds them in full). May be repeated
    --tier PROVIDER:TIER=MODEL, --effort PROVIDER:NAME=VALUE,
    --role-model PROVIDER:ROLE=MODEL
                            the model of a tier, the provider's value for an
                            effort name, a model for one role definition (an
                            empty MODEL takes the entry out). May be repeated
    --docs-dir DIR, --questions HOW, --recommend/--no-recommend,
    --high-stakes/--no-high-stakes, --max-parallel-coders N, --memory-dir DIR
                            process.docs_dir, process.questions,
                            process.recommend, roles.high_stakes,
                            roles.max_parallel_coders, memory.dir
    --manager-default/--no-manager-default
                            roles.manager_default: a session in the project
                            starts as the Manager. With DIR only
    --codex-settings off|on|profile
                            the Codex config item of this machine (see
                            above). Without it a run keeps what the blocks
                            of ~/.codex/config.toml hold
    --worktree-root DIR     the directory your git worktrees are made under,
                            made writable by the profile; for an item that
                            is on
    --no-versions, --codex-probe, --no-collab
                            options of --check

Exit code 0 when the plan was applied or there was nothing to do; 2 when the
run cannot do what was asked, with the reason on stderr and nothing written
where the plan was refused; 3 when the rest was done and a generated file,
key or block that was edited by hand was kept, or a path was skipped that
--follow-config-symlinks would write; 130 when interrupted, and 128 plus the
signal's number when told to end by a signal; 141 when the reader of the
output went away.

--check. Check an install: the clone's sources, what setup wrote in the homes and,
with DIR, in a project, and the providers themselves. Only the options below
are taken with it: --yes, --dry-run and the options that give a value are
refused.

    setup.py --check [DIR] [--json] [--home DIR]
             [--only NAME]... [--skip NAME]...
             [--no-versions] [--no-collab] [--codex-probe]

Setup itself writes nothing, anywhere: no file of a home, a project or the
clone, no install record, no state directory. A credentials file is never
opened.

Four checks start a program of a provider, and such a program may write
state of its own into its own home when it starts (Codex: its databases, an
installation id, its bundled skills). They are models, versions, discovery
and collaboration-skill, left out with --skip models, --no-versions,
--skip discovery and --no-collab; with all four the run starts no program.
With --home DIR every program is pointed at DIR and its provider homes, and
never reads or writes the real ones. The first line of the output says
which of the four ran.

Each check has a name and gives findings, each with a severity and one line:

    error     something is wrong and needs doing; the exit code is 1
    warning   something to look at; the exit code stays 0
    info      a fact, or why a check could not be made (a provider that is
              not installed, a home setup never ran on)
    ok        the check found nothing

The checks, in the order they run:

    sources              the clone's sources, as `validate.py` checks them: each
                         problem is an error. Role sizes are info.
    drift                a generated file (a role definition, a loaded role,
                         a Codex profile; in a project its definitions, the
                         starting role's keys, "agent" and "effortLevel" in
                         .claude/settings.json, and its block; its links and
                         rule copies whose unit left the project's list)
                         made from other sources or settings than today's,
                         and one that the install would no longer make:
                         warnings. Run setup.py. Also, as warnings and in
                         a project only, what you are to do by hand: setup's
                         old block in the project's .gitignore, its old
                         block in a .codex/config.toml that git tracks,
                         and that setup writes nothing into a tracked
                         .codex/config.toml, so that Codex sessions in the
                         project will not start as the Manager.
    hand-edits           a generated file whose content is not what setup
                         wrote, and a block or a key setup wrote that was
                         changed since: warnings. The install keeps such a thing
                         and reports it; `setup.py --overwrite-edited` backs
                         it up and replaces it.
    missing              what the install record lists and is gone from
                         disk: an error. What the install would create now and
                         the record does not list: a warning, and info on a
                         home (or a project) that was never installed, and
                         for the generated files of a home whose `install`
                         lacks `roles`. Roles left out of the home's
                         `install` are an info line that names the file:
                         nothing of them is then missing, and what an
                         earlier run generated is reported by drift as
                         the install would no longer make it.
                         Something at a path where the install would
                         install, which setup did not make: an error, since
                         the install stops on it. With DIR: a unit of the
                         project's list (install, and the units it
                         needs) that is in neither the project nor the home:
                         a warning, as for any other thing the install would
                         create now; and the faults of the project's lists,
                         with their file.
    links                a link the record lists that is missing, is no
                         longer a link, leads elsewhere than setup pointed
                         it, leads to something that does not exist (a moved
                         or removed clone), or resolves outside the clone:
                         errors. A project's link is told by where it
                         leads, as the install tells it: the other side's link
                         with its own text or form, and one made by hand
                         that the install took over, are not reported.
    duplicate-skills     a skill name setup installs that is also in another
                         skill location of the same provider, with both
                         paths: a warning. For Codex the deprecated
                         <codex home>/skills, which it still reads, and it
                         does not merge two skills of one name; with
                         a DIR the project's .claude/skills and
                         .agents/skills. A project's link the record holds
                         is not reported here: `links` and `drift` judge it.
    other-clones         a link in a skills or rules directory, or in the
                         record, that leads into another clone of this
                         repository, and a clone inside a skills directory:
                         warnings. The collaboration skill linked from
                         another clone is info: it runs from the development
                         clone by intent. A clone is told by what it holds
                         (tools/setup/setup.py and roles/); git is
                         not run.
    clone                whether both sides of the machine can read the clone
                         this runs from: a warning, with one line, where the
                         Windows side cannot read it; not asked with --home
                         on WSL or on a Linux with no Windows side. On
                         Windows, a clone off a local drive is the same
                         warning, with --home as well.
    models               each installed provider's own model list beside its
                         mapping: an effort a definition resolves to that
                         the list does not give its model is an error; a
                         mapped model that is not in the list, or listed as
                         hidden, or with other efforts than the dictionary
                         has, a warning; a list that cannot be read, a
                         warning with the reason. Claude Code has no list:
                         info. This starts the provider's list command
                         (`codex debug models`); --skip models leaves the
                         check out.
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
                         whether the blocks `setup.py --codex-settings`
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
                         no dictionary): warnings. A key of a settings file
                         that setup no longer reads, with the key that
                         replaces it: a warning. A profile that does not
                         resolve: an error.
    interrupted-run      an earlier run of setup that was stopped half way:
                         a warning with the changes found made and those
                         dropped; the temporary files its record lists, its
                         lock and what its start left (the next run that
                         writes removes these); a lock setup cannot judge;
                         backups under a state directory that no record
                         lists (setup never removes them by itself;
                         `setup.py --uninstall --discard-backups` does). A file that
                         is only named like a temporary of setup's is info:
                         it is left alone.
    loaded-skill-size    a loaded role whose skill is estimated over what
                         Claude Code keeps of a skill after a compaction: a
                         warning. Codex documents no such cut and its
                         dictionary names no figure: its sizes are info.
    instruction-files    with DIR, whether both providers load
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
                         Unproven items are info, all in one line with the
                         reason for each.
                         A file the provider could not load (a definition
                         that does not parse or lacks a required key, a
                         skill with no SKILL.md) is an error. No session
                         with a model is started: Codex's skills, loaded
                         roles and starting role, by `codex debug
                         prompt-input`, the same with `--profile <role>`,
                         and the `skills/list` request of `codex
                         app-server` (experimental in Codex).
                         Codex's role definitions and everything on Claude
                         Code are unproven.
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
starts a session with a model.

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

--uninstall. Take back what setup installed, in this machine's homes or in one
project.

    setup.py --uninstall [DIR] [--home DIR] [--dry-run] [--json]
             [--follow-config-symlinks] [--keep-settings]
    setup.py --uninstall --discard-backups [--yes] [DIR] [--home DIR] [--dry-run]
             [--follow-config-symlinks]

Only the options above are taken with it; --keep-settings and
--discard-backups are for --uninstall alone, and --yes only confirms
--discard-backups.

What is undone
    Without DIR: what setup did at the user level, in the providers'
    homes and in ~/.agents. With DIR: what setup did in that
    project, and nothing else; the homes stay installed. So one project can
    be taken out of the framework, and a whole install is taken back by
    `setup.py --uninstall DIR` for each project and then `setup.py --uninstall`.

    Only what the install record lists is touched, and each entry only
    while it is still as setup left it:

      - a link is removed if it still points where setup pointed it;
      - a generated file is removed if it still holds what setup wrote;
        a Codex profile that also holds what Codex or you added after
        setup's part (Codex writes your answer to "trust this project?"
        and flags of its interface there) loses setup's keys and is left
        holding the rest, as yours;
      - a file of yours that setup edited gets back, byte for byte, what it
        held before, if nothing changed it since. If it was changed, setup's
        blocks and keys are taken out, the lines setup removed are put back
        where they were, and the rest of the file is left as it is;
      - what an earlier setup removed and recorded is put back: a file from
        its backup, a link with its own text and form (one into the clone is
        put back below where the clone is now), a directory;
      - setup's block of the repository's exclude file (info/exclude in the
        git directory) goes with the project's record, while it is as setup
        wrote it;
      - a directory setup created is removed once it is empty;
      - the settings file setup wrote (see "The settings file" below).

    A project's skill links (relative ones included, as one side or the
    other made them) and its rule copy are removed with the rest of its
    record, and a link the record lists that is already gone is dropped
    from the record without a fault. A link you made by hand that setup
    took over (`setup.py DIR`) stays where it is, and is yours: the
    output lists it as left. Taking the skill off the project's list
    removes it; `setup.py --uninstall DIR` does not.

    Nothing else is removed: not the collaboration skill's links, not a
    settings file you wrote yourself, not a project's own settings file
    that setup found and did not change.

The settings file
    No value you set in a settings file is removed by `--uninstall`. The file
    setup wrote (~/.agents/workflow.toml, or with DIR
    DIR/.agents/workflow.toml) is

      - removed, when setup created it and it holds exactly what setup
        wrote from its own answers, with nothing else in it;
      - replaced, byte for byte, by the file that was there before the
        first run of setup, when nothing but setup has written it since;
      - left as it is, and yours from then on, in every other case: you
        edited it since setup wrote it, or setup rewrote a version you
        had edited (`--rewrite-settings`, or the same confirmed on
        the screen), so that it holds values you set. The backups of its
        earlier versions go with the record, as all backups do: copy one
        first if you want its comments back.

    A file that is left does not keep the uninstall from finishing. With
    --keep-settings the file is left in every case. --dry-run says which
    of the three it would be, and names --keep-settings on the line that
    would remove or replace the file.

What you had `--overwrite-edited` replace
    Text of yours between setup's markers, and a value of yours at a key
    setup sets, that `--overwrite-edited` replaced, is put back
    where it was when setup's block or key goes: your text takes the place
    of setup's block, and your value the place of setup's, and the file
    stays. Where that cannot be done exactly, the backup that holds your
    text is never removed, its path is printed, and the exit code is 3:

      - a block you edited again is kept as it is, like any edited block,
        with its record and that backup, until you deal with the block;
      - where the block or the key is gone, the key has another value
        again, or setup replaced text of yours at the same place more
        than once, the backup is taken out of the record and stays in
        the state directory. See "Backups setup does not remove" for how
        to clear it once you have what you need from it.

What is kept
    An entry that was changed since setup made it is kept, with the reason
    and what to do about it: a link that points elsewhere now, a generated
    file or a block that was edited by hand, a path where something is
    again that setup removed (its backup is kept, and its path is printed).
    A path that is, or lies under, a link is kept unless
    --follow-config-symlinks is given; where the link leads out of the
    home (or, for a project, out of the project) or into a clone, it is
    kept with the option too, since setup writes there under no option.
    A path of a home whose real place is on the other side of the machine
    (Windows and WSL) is always kept: this side never writes there.
    Everything else is still undone.

    Left to you, and no longer setup's to answer for: a directory setup
    created that holds something of yours, a key of a settings file whose
    value you changed since setup set it, and the settings file of setup
    once it holds values you set (above). None of them keeps the uninstall
    from finishing.

The state
    Setup keeps its state where the record belongs: in
    ~/.agents/workflow-setup for the user level, and in
    DIR/.agents/workflow-setup for a project, each with its record
    (manifest.json), the backups of the files it replaced or removed
    (backups/<time of the run>/) and, while a run writes, its lock. A
    project's state is in the project, whole: undoing a project touches
    nothing of the home, and undoing the home nothing of a project.

    When every entry was removed or restored, the state goes too: the
    backups the record lists, the record, and the directories that held
    them. Nothing of setup's is then left.

    While an entry is kept the state stays, with the record of what was
    kept and the backups it still needs. Do what the output says for each
    kept entry (put it back as setup wrote it, or remove it) and run
    `setup.py --uninstall` again: it finishes the job. The last resort, when an entry
    cannot be dealt with, is to remove the state directory by hand. What
    is kept is then yours.

Backups setup does not remove
    Setup removes a backup only together with the record that lists it. A
    file under a backups directory that no record lists (the record was
    removed by hand, or the file was put there by something else) is never
    removed by a run: it may be the only copy of a file of yours.
    `--uninstall` then leaves the state directory, names the files, and ends
    with 3. Look at them, and when you need none of them:

        setup.py --uninstall --discard-backups [DIR]

    lists the backups that no record lists and removes them after you
    confirm (or with --yes; --dry-run only lists). It removes nothing a
    record lists and undoes nothing.

--dry-run prints what would be removed, restored, left and kept, and
changes nothing. A second `--uninstall` finds no record, says that there is
nothing to do, and ends with 0. An interrupted run is
completed in the record first, as every run is, and then undone.

The whole way back is checked before the first change, so one that is
refused changes nothing. It is not atomic: if a change fails part way, what
was undone before it stays undone and the record holds the rest; the error
says how many changes were made, and running `--uninstall` again goes on. A
run that fails before its first change (a state directory that cannot be
written) says that nothing was changed.

The backups are full copies of your files as they were, with everything
they hold; the ones a record lists are removed with that record.

Known limit. The guards on where setup writes and removes (never inside
the clone, at a credentials file, or outside the home and the project) hold
against the disk as the run finds it, not against another program that
changes the same directories while the run is under way.

One run writes to a home at a time, and one to a project: a second one ends
at once with exit code 2 and names the run that holds the lock. A run that
was killed leaves its lock, its unfinished changes and perhaps a file under
a temporary name that its record lists; the next run that writes clears the
lock where that process is provably gone (else the message says how),
settles the changes from the disk, removes those temporary files, and says
so. A lock taken on another system (a project on a Windows drive, used from
Windows and from WSL) is never cleared from here: the message names the
file to remove once no setup run is using the project.

The output: the home or the project, the record, what was removed, what was
restored, what was left to you, what was kept (each with what it is, why,
the backup that belongs to it and how to finish), the state, and one line
that sums it up. With --json one object with the same facts ("scope",
"removed", "restored", "forgotten", "left", "kept", "plan", "notes",
"state", "errors", "summary", "exit_code").

Exit code 0 when everything was undone, or there was nothing to do; 3 when
the rest was done (or, with --dry-run, would be) and something stays that
you have to deal with: an entry was kept, or the state directory stays for
backups that no record lists or for something else in it that setup did
not put there (the output names it); 2 on an error, printed to stderr; 130
when interrupted with Ctrl-C, and 128 plus the signal's number when told to end by a signal (143
for SIGTERM): what was undone until then stays undone, and the next run goes
on; 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from . import codexsettings, doctor, fileops, gitrepo, homes, locations, paths, render, schema, screen, settings, settingsfile, uninstall, validate
from .errors import SetupError

PROG = "setup.py"
PROVIDER_OPTION = "--provider"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    # ``dest="project"``: ``locations.from_args`` reads the project from there.
    parser.add_argument("project", metavar="DIR", nargs="?", help="the project to set up as well as the homes")
    parser.add_argument("--yes", action="store_true", help="apply the plan with no question (without it, on a terminal, a screen asks)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be changed, and change nothing")
    parser.add_argument("--json", action="store_true", help="print one JSON object; needs --yes or --dry-run")
    parser.add_argument(
        PROVIDER_OPTION, metavar="NAME", action="append", choices=[homes.CLAUDE_CODE, homes.CODEX], default=[],
        help="install for this provider although its program and home are not there yet (claude-code or codex); "
        "may be repeated",
    )
    parser.add_argument(
        render.OVERWRITE_OPTION, action="store_true",
        help="replace a generated file, a key or a block that was edited by hand since setup wrote it, after a "
        "backup of the file. Without it such a thing is kept and reported, with exit code 3; on the screen "
        "each one is asked about instead",
    )
    parser.add_argument(
        "--home", metavar="DIR",
        help="use DIR in place of the user's home directory (for trial runs). The providers' homes are then "
        "DIR/.claude and DIR/.codex, and the environment variables CLAUDE_CONFIG_DIR and CODEX_HOME are ignored",
    )
    parser.add_argument(
        "--follow-config-symlinks", action="store_true",
        help="write through a config path that is a link, or lies under one, where the link leads to a place "
        "inside the home or the project",
    )
    parser.add_argument(
        "--allow-unlisted", action="store_true",
        help="keep a mapped model that the provider's own list does not hold, instead of refusing it",
    )
    settingsfile.add_arguments(parser)
    codexsettings.configure(parser)
    parser.add_argument(
        "--check", action="store_true",
        help="check the clone's sources, what setup installed and the providers, and write nothing; exit code 1 "
        "on an error. With DIR, the project's checks too. The checks: " + ", ".join(doctor.names()),
    )
    parser.add_argument(
        "--only", action="append", default=[], metavar="NAME",
        help="for --check: run this check and no other; may be given more than once",
    )
    parser.add_argument(
        "--skip", action="append", default=[], metavar="NAME",
        help="for --check: leave this check out; may be given more than once",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="take back what setup installed in this machine's homes, or with DIR in that project; only what is "
        "still as setup left it. Takes --dry-run, --json, --home, --follow-config-symlinks, --keep-settings and "
        "--discard-backups",
    )
    parser.add_argument(
        uninstall.KEEP_SETTINGS_OPTION, action="store_true",
        help="for --uninstall: leave the settings file setup wrote as it is, in every case; it is yours from then "
        "on. Without it the file is removed, or replaced by the one that was there before setup, only while it "
        "holds exactly what setup wrote and setup never rewrote a version you had edited; else it is left as well",
    )
    parser.add_argument(
        uninstall.DISCARD_OPTION, action="store_true",
        help="for --uninstall: undo nothing; list the backups under the state directory that no record lists, and "
        "remove them after a confirmation (--yes gives it). Setup never removes such a file by itself: it may be "
        "the only copy of a file of yours",
    )
    parser.add_argument("--no-versions", action="store_true", help="for --check: do not start `<program> --version`")
    parser.add_argument("--codex-probe", action="store_true", help="for --check: add the Codex probe steps")
    parser.add_argument("--no-collab", action="store_true", help="for --check: leave out the collaboration skill's check")
    return parser


def main(argv: list[str]) -> int:
    """Parse ``argv`` and run; the runner ``cli.main`` is given."""
    return run(build_parser().parse_args(argv))


def _with_named_providers(found: homes.Homes, names: list[str]) -> homes.Homes:
    """``found``, with each provider in ``names`` counted as installed: its
    home is created by the plan (R7.3)."""
    if not names:
        return found
    providers = tuple(
        dataclasses.replace(provider, home_exists=True) if provider.name in names else provider
        for provider in found.providers
    )
    return dataclasses.replace(found, providers=providers)


def _old_keys(where: locations.Locations) -> None:
    held = settings.old_keys(where)
    if held:
        raise SetupError(*[
            f"{file}: {key} is an old key; use {replacement}. Change the file, nothing was written"
            for file, key, replacement in held
        ])


def _refused(args: argparse.Namespace, taken: set[str]) -> list[str]:
    """The options given that a mode does not take, as they were spelled:
    ``--no-x`` for an option with a negative form that was given false."""
    parser = build_parser()
    defaults = vars(parser.parse_args([]))
    names = []
    for name, value in vars(args).items():
        if name in taken or value == defaults[name]:
            continue
        spelled = "--" + name.replace("_", "-")
        for action in parser._actions:
            if action.dest == name and isinstance(action, argparse.BooleanOptionalAction):
                spelled = next(o for o in action.option_strings if o.startswith("--no-") == (value is False))
        names.append(spelled)
    return sorted(names)


# What a --check run takes; any other option given with it is refused.
CHECK_OPTIONS = {"project", "check", "json", "home", "only", "skip", "no_versions", "codex_probe", "no_collab"}


def _check(args: argparse.Namespace) -> int:
    """``--check``: the checks of ``doctor.CHECKS``, which write nothing."""
    refused = _refused(args, CHECK_OPTIONS)
    if refused:
        raise SetupError(f"--check writes nothing and takes no {', '.join(refused)}")
    chosen, left_out = doctor.select(args, only=args.only, skip=args.skip)
    where = locations.from_args(args, writes=False, project_label="DIR")
    context = doctor.Context(where, args)
    found = doctor.report(context, doctor.run(context, chosen), left_out)
    if args.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
    else:
        for line in doctor.report_lines(found):
            print(line)
    return found["exit_code"]


# What an --uninstall run takes; any other option given with it is refused.
UNINSTALL_OPTIONS = {
    "project", "uninstall", "json", "home", "dry_run", "follow_config_symlinks", "keep_settings",
    "discard_backups", "yes",
}


def _uninstall(args: argparse.Namespace) -> int:
    """``--uninstall``: take back what setup installed, in the homes or in one project."""
    refused = _refused(args, UNINSTALL_OPTIONS)
    if refused:
        raise SetupError(f"--uninstall takes back what setup installed and takes no {', '.join(refused)}")
    where = locations.from_args(args, project_label="DIR")
    found = homes.resolve(where)
    project = where.project is not None
    if args.discard_backups:
        return _discard(args, found, project)
    if args.yes:
        raise SetupError(f"--yes: only confirms {uninstall.DISCARD_OPTION}; an uninstall asks nothing")
    outcome = uninstall.execute(
        found, project=project, dry_run=args.dry_run, follow=args.follow_config_symlinks,
        keep_settings=args.keep_settings,
    )
    if args.json:
        print(json.dumps(outcome.report, indent=2, ensure_ascii=False))
    else:
        for line in uninstall.report_lines(outcome.report):
            print(line)
    if outcome.errors:
        raise SetupError(*outcome.errors)
    return outcome.code


def _discard(args: argparse.Namespace, found: homes.Homes, project: bool) -> int:
    """``--uninstall --discard-backups``: name the backups no record lists and remove them once confirmed."""
    for name in ("keep_settings", "json"):
        if getattr(args, name):
            raise SetupError(
                f"{uninstall.DISCARD_OPTION}: is a command of its own; give it without --{name.replace('_', '-')}"
            )

    def confirm(listed: list[Path]) -> bool:
        if args.yes:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            raise SetupError(
                f"{uninstall.DISCARD_OPTION}: needs a confirmation: nothing was removed. Give --yes to remove what "
                "is listed above"
            )
        try:
            what = "this backup" if len(listed) == 1 else f"these {len(listed)} backups"
            return input(f"Remove {what} for good? [y/N] (--yes): ").strip().lower() in ("y", "yes")
        except EOFError:
            return False

    where = found.project if project else found.home
    listed = fileops.unlisted_backups(found.roots(), project)
    if not listed:
        print(f"nothing to do: no backup under {found.roots().state_dir_of(project)} is unlisted; nothing was changed")
        return 0
    print(f"backups of {where} that no record of setup's lists:")
    for path in listed:
        print(f"  {path}")
    if args.dry_run:
        print("dry run: nothing was removed")
        return 0
    removed, done = uninstall.discard(found, project=project, follow=args.follow_config_symlinks, confirm=confirm)
    print(f"removed: {len(removed)} backup{'' if len(removed) == 1 else 's'}" if done else "nothing was removed")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.check:
        return _check(args)
    if args.uninstall:
        return _uninstall(args)
    if args.keep_settings or args.discard_backups:
        raise SetupError("--keep-settings and --discard-backups are for --uninstall")
    if args.only or args.skip or args.no_versions or args.codex_probe or args.no_collab:
        raise SetupError("--only, --skip, --no-versions, --codex-probe and --no-collab are for --check")
    if args.json and not (args.yes or args.dry_run):
        raise SetupError("--json needs --yes or --dry-run: a run that asks questions has no JSON output")
    where = locations.from_args(args, project_label="DIR")
    if where.project is not None:
        # One spelling of the project for both sides of the run, the settings
        # file and the install: absolute, no link followed (as homes.resolve).
        where = dataclasses.replace(where, project=paths.absolute(where.project))
    sources = validate.require(where)
    if args.yes or args.dry_run:
        # An old key stops an unattended run (R10.2).
        _old_keys(where)
        return _apply(args, where, sources)
    if not screen.terminal():
        _old_keys(where)
        raise SetupError(
            "nothing is applied without --yes, and standard input is not a terminal, so the screen that asks "
            "is not shown: pass --yes to apply the plan, or --dry-run to see it"
        )
    found = _found(args, where)
    return screen.run(
        args, where, found, lambda given, edited=None: _apply(given, where, sources, drop_old=True, edited=edited),
        sources.skills,
    )


def _found(args: argparse.Namespace, where: locations.Locations) -> homes.Homes:
    found = _with_named_providers(homes.resolve(where), args.provider)
    if not found.installed():
        raise SetupError(
            "no provider to install for: neither claude nor codex is on PATH and neither home exists. "
            f"Name one with {PROVIDER_OPTION} claude-code or {PROVIDER_OPTION} codex"
        )
    return found


def _apply(
    args: argparse.Namespace, where: locations.Locations, sources: Any, *, drop_old: bool = False,
    edited: list[tuple[str, str]] | None = None,
) -> int:
    """Plan and apply (or, with --dry-run, show) the run. ``drop_old``: the
    screen's, which names an old key and writes the settings file without it.
    ``edited``: the screen's list, which gets each item kept for an edit of
    the user's, as ``(id, text)``, and a settings file written by hand that the
    plan would rewrite (``settingsfile.HAND_ID``, R4.3); ``args.overwrite_edited`` may be the set of
    ids to replace."""
    found = _found(args, where)
    homes.require_linkable_clone(found)
    codexsettings.preflight(found, args)
    # One run holds the lock of the home, and of the project, throughout: the
    # settings file is written first, and the install plan is made after it,
    # on the file as it then is. A dry run writes neither and shows both: the
    # install plan is made as if the settings file were written.
    held = (
        contextlib.nullcontext() if args.dry_run
        else fileops.locked(
            found.roots(), home=True, project=found.project is not None, follow=args.follow_config_symlinks
        )
    )
    with held:
        prepared = settingsfile.prepare(where, found, args, dry_run=args.dry_run, drop_old=drop_old)
        content = {prepared.target: prepared.data} if prepared.data is not None else {}
        by_hand = [(settingsfile.HAND_ID + str(prepared.target), str(prepared.target))] if prepared.by_hand else []
        options = dict(
            follow=args.follow_config_symlinks, overwrite_edited=args.overwrite_edited,
            clone_warning=homes.clone_warning(found),
            # The project's keys in .claude/settings.json move only with
            # its settings file (R6.1); a dry run shows the write it plans.
            project_changed=found.project is not None and not prepared.kept
            and (prepared.changed or args.manager_default is not None),
        )
        if not args.dry_run:
            # The install plan is made and checked on the settings as they
            # will be, before either is written: a plan that is refused
            # writes nothing, the settings file included.
            with settings.pending(content):
                refused = render.execute(found, sources, args, dry_run=True, **options)
            if refused.errors:
                refused.report["dry_run"] = False      # it was the check of a run, not a dry run
                if args.json:
                    print(json.dumps(_json(where, refused.report), indent=2, ensure_ascii=False))
                else:
                    for line in prepared.lines:
                        print(line)
                    print()
                    for line in render.report_lines(refused.report):
                        print(line)
                raise SetupError(*refused.errors)
        lines = prepared.lines if args.dry_run else [*prepared.lines, *prepared.apply()]
        if not args.json:
            for line in lines:
                print(line)
        with settings.pending(content if args.dry_run else {}):
            outcome = render.execute(found, sources, args, dry_run=args.dry_run, **options)
            if prepared.kept and outcome.report["summary"].startswith(fileops.UP_TO_DATE):
                # A settings file was kept: not everything is up to date.
                outcome.report["plan_empty"] = NOTHING_ELSE
                outcome.report["summary"] = outcome.report["summary"].replace(
                    fileops.UP_TO_DATE, NOTHING_ELSE, 1
                ) + "; the settings file was kept as written or edited by hand"
            if edited is not None:
                edited[:] = [*by_hand, *outcome.edited]
            if args.json:
                print(json.dumps(_json(where, outcome.report), indent=2, ensure_ascii=False))
            else:
                print()
                for line in render.report_lines(outcome.report):
                    print(line)
                if not args.dry_run and not outcome.errors:
                    for line in _after(found, where, prepared, outcome):
                        print(line)
    if outcome.errors:
        raise SetupError(*outcome.errors)
    return render.EXIT_NEEDS_FLAG if prepared.kept and not outcome.code else outcome.code


NOTHING_ELSE = "nothing else to do: the rest is up to date"
COMMIT_MESSAGE = "Set the project's workflow settings"


def _quoted(text: str, windows: bool) -> str:
    if windows:
        return f'"{text}"' if " " in text else text
    return shlex.quote(text)


def _after(found: homes.Homes, where: locations.Locations, prepared: Any, outcome: render.Outcome) -> list[str]:
    """What follows an applied run: the git lines for the project's files
    this run wrote (R6.2) and the command for the other side of a Windows
    and WSL machine (R2.3). Nothing is run, and nothing is committed."""
    lines: list[str] = []
    project = found.project
    if project is not None:
        files = []
        if prepared.changed and prepared.target == where.project_file:
            files.append(prepared.target)
        files.extend(outcome.written)
        # A file this run took out again (a settings file it had made) is
        # listed only where git tracks it: git add would refuse the others.
        files = [
            path for path in files
            if os.path.lexists(path) or gitrepo.tracked(project, path.relative_to(project).as_posix()) is True
        ]
        names = [shlex.quote(path.relative_to(project).as_posix()) for path in files]
        if names:
            listed = " ".join(names)
            lines += [
                "", f"setup commits nothing; to commit these files, from {project}:",
                f"  git add -- {listed}",
                f'  git commit -m "{COMMIT_MESSAGE}" -- {listed}',
            ]
    side = found.host.other
    # The command is of use only where the other side reads this same clone,
    # and it names no scratch home; a refused run gets none.
    if (
        side is not None and found.clone is not None and not outcome.errors
        and not found.scratch and homes.clone_standing(found).shared is True
    ):
        script = "tools/setup/setup.py"
        if side == homes.WINDOWS:
            clone = render._windows_path(str(found.clone)).rstrip("\\")
            target = None if project is None else render._windows_path(str(project))
            if target is not None and target.startswith("/"):
                target = None   # in the Linux file system: Windows reads it by no path formed here
            program = clone + "\\" + script.replace("/", "\\")
            command = [f"py -3 {_quoted(program, True)}"]
            command += [] if target is None else [_quoted(target, True)]
        else:
            clone = render._wsl_path(str(found.clone)).rstrip("/")
            target = None if project is None else render._wsl_path(str(project))
            command = [f"python3 {_quoted(clone + '/' + script, False)}"]
            command += [] if target is None else [_quoted(target, False)]
        lines += ["", f"for {side}, run: {' '.join(command)}"]
    return lines


def _json(where: locations.Locations, install: dict[str, Any]) -> dict[str, Any]:
    held = {
        key: {"value": entry.value, "layer": entry.layer, "file": str(entry.file)}
        for key, entry in settings.resolve(where).items()
    }
    # ``install`` is no setting of a group: each layer's list, as the
    # settings reader resolves it, in the order the layers apply.
    held["install"] = [
        {"value": entry.value, "layer": entry.layer, "file": str(entry.file)} for entry in settings.install(where)
    ]
    return {"schema_version": schema.SCHEMA_VERSION, "settings": held, "install": install}
