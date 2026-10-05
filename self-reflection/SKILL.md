---
name: self-reflection
description: Critically reflect on the current conversation and surface only observations that would materially change future work. Use only when the user explicitly asks for self-reflection, lessons learned, what went right or wrong, or consequential recommendations from a completed session.
compatibility: claude-code, codex
disable-model-invocation: true
---

# Self Reflection

Review the current conversation and share a self-reflection only when something genuinely critical or thoughtful should be said.

Maintain a high bar. Include no nitpicks, mild advice, filler, generic process guidance, or recommendations manufactured to make the response look complete. Prefer `Nothing critical to flag.` over padded observations.

Apply two accountability checks before including an observation:

1. Explain what concrete moment or decision in this conversation supports it.
2. For advice to the user, ask whether the user could reasonably have acted on it with information available at the time. Do not convert the agent's own missed context, shifting standards, or hindsight into recommendations for the user.

Use only the sections that contain material observations; omit empty sections and do not force all three:

- **Lessons learned** — Identify wrong assumptions that cost real effort, patterns that clearly paid off, or decision points that should have gone differently. Cite specifics.
- **Worth remembering** — Propose memory candidates grouped by kind: about the user, feedback on how to work, project facts, or references. For each, state why it would change future behavior and when it applies. Do not save anything.
- **Recommendations for the user** — Include only workflow, tooling, or briefing changes that would have materially improved this session and were reasonably available to the user at the time. Do not use this section to shift responsibility for an agent failure.

Conclude without a recommendation section when no material user action qualifies.
