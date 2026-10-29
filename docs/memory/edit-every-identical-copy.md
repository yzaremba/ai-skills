# Edit every byte-identical copy

**Recorded:** 2026-10-29, after sprint 03 of this repository
**Roles:** the Coder, and whoever writes a PLAN step that edits a file kept identical in several places

## What

A step that edits a file kept byte-identical in several places (the `scripts/settings.py` launchers of the skills, for one) searches the repository for every copy and edits them all; it does not trust the step's file list.

## Why

Sprint 03's P2.1 named two of the three `settings.py` launchers. The third, in `project-memory/scripts/`, was found only because `validate` refuses launchers that differ ("launcher-identical"). Each skill carries its own copy because a skill reaches no path outside its own directory.

## When it applies

Writing or carrying out a step that changes `settings.py` or any other file that `validate` or a test keeps identical across units.
