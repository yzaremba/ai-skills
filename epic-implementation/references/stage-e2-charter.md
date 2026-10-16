# Stage E2 — EPIC PRD (charter)

Read [conventions.md](conventions.md) before creating the file. This stage starts only after the user has confirmed that the brainstorm is ready to become a charter.

After confirmation, create `EPICXX-PRD-<Description>.md` from THOUGHTS (and verbal direction). Cross-link THOUGHTS ↔ PRD in headers. Those links are within the epic's set; a sprint's doc or any other doc the charter refers to is named by its file name in backticks, never linked ("Links and names" in [conventions.md](conventions.md)). The charter stays **high-altitude** — sections:

- **Vision / problem** — why this epic exists and the outcome it drives.
- **Success criteria** — measurable; this is the epic's **definition of done** (how you know the whole effort is complete).
- **In scope** — the major capabilities/features included.
- **Non-goals** — explicit out-of-scope items, to limit creep across the whole effort.
- **Risks / assumptions / dependencies** — for a multi-sprint effort these matter; note cross-sprint ordering constraints.
- **Rough sequencing** — narrative of the intended phasing, referring to sprints by **slug / feature name, not number** (numbers aren't assigned until each sprint is created, so a number written here would go stale). The detailed sprint table belongs in the ROADMAP, not here.

**Promote, don't copy — trim EPIC THOUGHTS as the charter absorbs the defining substance.** Moving to the charter is a *migration*: the vision, success criteria, scope, and sequencing that **define** the epic go into the PRD. In the same change, edit EPIC THOUGHTS down to only its **defining points** (the core problem and the decisive framing that justified an epic in the first place). The candidate-sprint breakdown becomes **short ROADMAP rows** — the ROADMAP is the epic's TASKS-equivalent tracker, so rows carry only slug / feature / dependency / status, never narrative. The **detailed** per-sprint thinking and implementation hunches belong in neither the thin charter nor those terse rows — they migrate into the individual sprint docs as each sprint is planned (don't fold them into the charter or the ROADMAP just to preserve them). EPIC THOUGHTS should end up a short, high-signal record of *why this epic exists and what defines it* — not a parallel charter.

**Critical pass (default).** Once the draft charter exists, **take a critical pass over it by default** (no need to ask first) — testing each piece for **efficacy** (do the success criteria and in-scope capabilities actually drive the vision/outcome?), **consistency** (no internal contradictions; aligns with EPIC THOUGHTS), and **need** (genuinely required vs. scope creep across the whole effort). **Fold minutia automatically** (wording, redundant or overlapping bullets, tightening, obvious small gaps) and **bubble up the material findings** — questionable or unneeded scope, conflicts, missing pieces, things worth cutting — to the user for a decision rather than changing them silently, put as "Questions to the user" in [conventions.md](conventions.md) says. This is a quality check on the charter itself, distinct from the user's own review below; skip it only if the user explicitly opts out.

The user reviews and edits until satisfied. **Gate:** Do **not** create the ROADMAP until the user signals the charter is final (e.g. "charter is good" / "generate the roadmap").

Next: [stage-e3-roadmap.md](stage-e3-roadmap.md), once the user has given that signal.
