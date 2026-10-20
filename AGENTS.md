# AI Skills: repository guide

Skills, roles, rules and tools for AI coding agents, written once and installed for
both Claude Code and Codex. There is no `CLAUDE.md`: both providers read this file.

## Layout

```text
AGENTS.md  README.md  LICENSE.txt  .gitattributes  .gitignore
csv-tools/  json-tools/  self-reflection/   shared skills
prd-implementation/  epic-implementation/   shared skills: the sprint and epic process
project-memory/                             shared skill: the lessons a project keeps
usage-cost/                                 skill, Claude Code only
multiagent-collab/                          skill with its own setup; see below
roles/      README.md  SPECIALISTS.md  bindings.toml  _shared/  <role>/ROLE.md  <role>/role.toml
rules/      avoid-bash-injection-heuristics/    rule, Claude Code only
providers/  <name>/dictionary.toml  <name>/actions.md   for claude-code and codex
tools/      setup/            workflow_setup.py  wfsetup/  defaults.toml  tests/
                              manifest-keys.json  v1-known-hashes.json  build_v1_hashes.py
            session-profile/  session-record reader and its tests
docs/       agent-roles-framework.md  v1-to-v2.md
            prd-implementation-slide.html  roles-framework-slide.html   the two slides,
                                                                        each with its -preview.png
            memory/  this repository's lessons, indexed under "Project memory" below
```

## One directory per logical unit

- A skill is a directory at the repository root holding `SKILL.md`. The root is the
  skills root.
- A role is a directory under `roles/`, a rule a directory under `rules/`, a tool a
  directory under `tools/`, and a provider's own material a directory under
  `providers/`. `README.md` shows the same layout: a change here is made there too.
- Nothing new is added as a loose file at the root. A unit keeps its scripts,
  references and tests inside its own directory, and a skill reaches no path outside
  its own.

## `multiagent-collab/` changes only on request

This clone is where that skill is developed, and installed homes point at its path
here. It has its own setup, protocol file, hooks and tests. Work on anything else
does not move, rename or edit a file under it, and no other tool manages it. It
changes only when the user asks for a change to that skill. Its test suite also reads
the root `README.md`: the section headed "`multiagent-collab` for Codex and Claude"
stays as it is, followed by a "Skills" heading.

## Tests

Run each of these from the repository root with Python 3.11 or later. On a machine where
`python` is a project's virtual environment, use a system interpreter instead:

```bash
python -B multiagent-collab/tests/test_multiagent_collab.py
python -B -m unittest discover -s tools/session-profile/tests
python -B -m unittest discover -s tools/setup/tests
python -B -m unittest discover -s prd-implementation/tests
```

The setup suite samples its two longest tests (every kill point of every command, and the
lock race). After a change to the setup tool's write path run them in full as well:

```bash
WFSETUP_TEST_FULL=1 python -B -m unittest discover -s tools/setup/tests -p "test_real_crash.py"
WFSETUP_TEST_FULL=1 python -B -m unittest discover -s tools/setup/tests -p "test_lock_race.py"
```

## Conventions

- **Python.** Standard library only, Python 3.11 or later. The same code runs on
  Linux and on Windows. A child Python process is started with `sys.executable`.
- **Bytes.** Text files are UTF-8 with LF line endings. `.gitattributes` gives LF in
  a fresh clone and in every file a pull touches; a Windows checkout made earlier
  under `core.autocrlf=true` keeps CRLF in the files a pull does not touch. One
  deliberate exception: `json-tools/examples/users.csv` is CRLF, the tool's real
  output, pinned `-text`. A binary file type gets an explicit `binary` line there.
- **Paths.** No file holds an absolute path of one machine: no home directory, no
  user name, no drive letter. Use `~`, a path relative to the unit, or a placeholder.
- **Sources.** `python tools/setup/workflow_setup.py validate` checks every skill, role,
  rule and provider file, a machine path among the faults. Run it after changing one.

### Setup tool

- **Generated files are never edited.** A role definition, a loaded-role skill or a
  Codex profile in a provider home, and what `render --project DIR` wrote in a project, are
  made from `roles/`, `providers/` and the settings. Change the source, then run
  `render`.
- **One write path.** Every change setup makes on a disk goes through
  `tools/setup/wfsetup/fsio.py`; no other module of the package changes the disk, and a
  test reads each module's syntax tree for it.

### Skills

- **Compatibility.** Every `SKILL.md` frontmatter has one `compatibility:` line:
  `<providers>` or `<providers> (<note>)`, where `<providers>` is `claude-code`,
  `codex` or `claude-code, codex`. The value is an unquoted plain scalar with no
  trailing comment, and the note holds no parenthesis, `#` or `:`. Setup matches the
  raw line after `compatibility: ` against
  `^(claude-code|codex|claude-code, codex)( \([^()#:]+\))?$` to decide where a skill
  is installed. Examples: `compatibility: claude-code, codex` and
  `compatibility: claude-code (reads Claude Code's own session logs)`.
- **Provider settings.** A setting only Claude Code reads is a frontmatter key. A
  setting only Codex reads goes in `agents/openai.yaml` in the skill's directory.
- **Invoke only when asked** is declared twice, or not at all:
  `disable-model-invocation: true` in the frontmatter, and
  `policy.allow_implicit_invocation: false` in `agents/openai.yaml`.
- **Shared text.** `SKILL.md` names no provider tool and uses no provider substitution
  such as `${CLAUDE_SKILL_DIR}`. A provider difference goes in
  `references/claude-code.md` or `references/codex.md`. A location is described
  relative to the skill: "`scripts/` in this skill's directory".
- **Scripts.** No third-party dependency: Python standard library only, Node built-in
  modules only. Every path to the skill's own files is relative to the skill. One
  exception to "a skill reaches no path outside its own": a skill's script may read
  the setup tool and its shipped defaults (`tools/setup/`) beside the skill when they
  are there, and must work without them.

## Project memory

Lessons of this project, one line each. Before work a line applies to, read its file.

<!-- project-memory:index:start -->
- [A subagent spawn costs ~40K tokens](docs/memory/subagent-spawn-cost.md): before spawning for small work or writing role text; prefer a follow-up
- [Acceptance as a user](docs/memory/acceptance-as-a-user.md): planning or running an acceptance run; drive it as a user, friction is a finding
- [The outcome, and nothing beyond it](docs/memory/outcome-over-apparatus.md): before adding a check, tool, document, proof or review anywhere; apparatus only when the user asks
- Local lessons, private or of this machine: read `docs/memory/local/INDEX.md` if it exists.
<!-- project-memory:index:end -->
