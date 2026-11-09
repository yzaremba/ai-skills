# Run the Windows suite in every phase that changes cross-platform code

**Recorded:** 2026-11-09, sprint 06
**Roles:** all (whoever plans or runs a phase; the Coder, the build lead)

## What

A phase that changes code meant to run on Linux and on Windows runs the suite on Windows as well, in that phase, not only at the end of the sprint. Use a scratch clone of the repository and a Windows Python; the commands are in "Tests" in `AGENTS.md`.

## Why

Sprint 06 first ran the suite on Windows at P6.5. Windows-only breaks made from P2 to P6.1 surfaced only then, after the code that caused them had been built on.

## When it applies

Planning or finishing any phase that touches the setup tool, scripts, path handling, file writes, child processes or line endings.
