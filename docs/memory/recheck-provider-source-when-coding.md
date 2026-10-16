# Recheck a cited provider source on the day a step codes against it

**Recorded:** 2026-10-16, sprint 01
**Roles:** the implementer, the build lead

## What

When a step codes against a provider fact its PLAN cites (a setting name, a plugin id, a CLI flag, a file location), reopen the primary source that day instead of trusting the PLAN's copy. If it changed, code to the current fact and record the difference on the step.

## Why

A PLAN is written days or weeks before a step is coded, and Claude Code and Codex ship often. In sprint 01, step P8.2 coded doctor's check of the Claude Code setting that makes it read `AGENTS.md` beside a `CLAUDE.md`; the setting's plugin id had been renamed between the PLAN's check and the step. Coding from the citation would have shipped a check and a remedy naming an id that no longer existed.

## When it applies

Any step that writes code, a provider note (`providers/*/actions.md`, `dictionary.toml`) or a doctor check against a provider's documented or observed behavior.
