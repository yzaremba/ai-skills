# Both providers load `AGENTS.md`

The index is in the project's `AGENTS.md`, so a lesson reaches a session only where the provider loads that file. Codex always does. Claude Code does unless a `CLAUDE.md` is in its way. Read this when the index is first created in a project, when a `CLAUDE.md` of any kind is added to it, and when a session does not know a lesson the index holds.

What is said of the providers here is from their documentation as read on 2026-10-12: Claude Code's page on memory, and Codex's pages on `AGENTS.md` and on configuration.

## Codex

- **Codex loads `AGENTS.md` when it starts**, once for the session: one file from its own home, then one from each directory from the project root down to the directory it was started in. Start it at the project root, or below it.
- **It takes one file from a directory, and `AGENTS.override.md` comes first.** An `AGENTS.override.md` in the project root that is not empty replaces the `AGENTS.md` beside it: the index is not loaded while that file is there. Do not keep one in the project root. If the project needs one, the index block has to be in it as well, which this skill does not maintain.
- **It stops adding files at a size limit**: 32 KiB by default, counted over the files together, the one in its home included; `project_doc_max_bytes` in its `config.toml` changes it. What is past the limit is not loaded, and the index is at the end of `AGENTS.md`. Keep the file well below the limit.

## Claude Code

- **Claude Code reads `AGENTS.md` directly from version 2.1.277, and in every kind of session from 2.1.281.** Before 2.1.281 some sessions read `CLAUDE.md` files only.
- **It does so only when none of three files exists** in the directory the session starts in or in any directory above it:

  ```text
  CLAUDE.md
  .claude/CLAUDE.md
  CLAUDE.local.md
  ```

  Where one does, Claude Code reads the `CLAUDE.md` files and not `AGENTS.md`. The user's own `CLAUDE.md`, the one in the Claude Code home (`~/.claude` unless `CLAUDE_CONFIG_DIR` names another), does not count: it loads beside `AGENTS.md`. A `CLAUDE.md` in the project that is a link to it is the project's, and counts.
- **`CLAUDE.local.md` counts too**, though it is git-ignored and personal: one user adding it stops the index loading for that user alone.
- It reads no `AGENTS.override.md`, and skips an instruction file over 4 MiB: an import in a `CLAUDE.md` of that size is not read, and an `AGENTS.md` of that size is not loaded.

### The two remedies

A project that has one of the three files needs one of these. Without either, sessions on Claude Code do not see the index.

1. **An import.** Put the line `@AGENTS.md` into one of the three files, on a line of its own that is not indented, outside a code block, outside backticks and outside an HTML comment. The path is relative to the file that holds the line: `@AGENTS.md` in `CLAUDE.md` or `CLAUDE.local.md` beside it, `@../AGENTS.md` in `.claude/CLAUDE.md`. In a committed `CLAUDE.md` it holds for everyone who uses the project, so prefer it. A sentence that tells the session to read `AGENTS.md` is not an import.
2. **The user-level setting.** In the user's own Claude Code settings file, `~/.claude/settings.json`:

   ```json
   {
     "pluginConfigs": {
       "agents-md@builtin": {
         "options": { "instructionFiles": "claude-md-and-agents-md" }
       }
     }
   }
   ```

   Claude Code then reads both the `CLAUDE.md` files and `AGENTS.md`. It holds for that user in every project, and for nobody else. **Claude Code ignores this setting in a project's settings files**, `.claude/settings.json` and `.claude/settings.local.json`: it cannot be committed for a team. From 2.1.285 the same entry may also be written under the id `cc-plugin-agents-md@builtin`, which an older version ignores; `agents-md@builtin` is read by all of them, so write it under that one. Written under both, the two must hold the same value.

Both are changes to a file of the user's or of the project: propose the one that fits, and make it only on the user's word. Creating a `CLAUDE.md` in a project that has none is never the remedy: without one, `AGENTS.md` is read directly.

## Checking a project

Where the setup tool of this skill's repository is at hand, its `doctor --project <project root>` reports all of this without changing anything: an error where one of the three files is there with neither remedy, a warning for an `AGENTS.override.md` in the project root that is not empty, and a warning when the instruction files a provider loads are over three quarters of its limit.

In a session, the provider shows what it loaded: on Claude Code `/memory` lists the instruction files of the session, `AGENTS.md` among them; on Codex `codex debug prompt-input`, run in the project root, prints the instructions a session would get and starts none.
