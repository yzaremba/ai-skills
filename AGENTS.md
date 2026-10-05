# AI Skills: repository guide

Skills, roles, rules and tools for AI coding agents, written once and installed for
both Claude Code and Codex. There is no `CLAUDE.md`: both providers read this file.

## Layout

```text
AGENTS.md  README.md  LICENSE.txt  .gitattributes  .gitignore
csv-tools/  json-tools/  self-reflection/   shared skills
usage-cost/                                 skill, Claude Code only
multiagent-collab/                          skill with its own setup; see below
roles/      README.md  _shared/  <role>/ROLE.md  <role>/role.toml
rules/      avoid-bash-injection-heuristics/    rule, Claude Code only
providers/  claude-code/  codex/                what differs between providers
tools/      session-profile/                    session-record reader and its tests
docs/       agent-roles-framework.md and the v1 slide
```

`prd-implementation.md`, `epic-implementation.md` and `agents/sprint-coder.md` at the
root are the v1 process. They stay until the skills that replace them exist.

## One directory per logical unit

- A skill is a directory at the repository root holding `SKILL.md`. The root is the
  skills root.
- A role is a directory under `roles/`, a rule a directory under `rules/`, a tool a
  directory under `tools/`, and a provider's own material a directory under
  `providers/`.
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
python multiagent-collab/tests/test_multiagent_collab.py
python -m unittest discover -s tools/session-profile/tests
python -m unittest discover -s tools/setup/tests
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
  modules only. Every path to the skill's own files is relative to the skill.
