"""The ``project-memory`` skill of the repository, and who writes a lesson.

What the skill's text states has to agree with what the check command of
the sprint skill checks (the markers of the index and its two limits), and
the binding table has to give the lessons to roles that may write.
"""
from __future__ import annotations

import importlib.util
import re
import unittest

import support
from wfsetup import definitions, roles, validate
from wfsetup.locations import Locations

CLONE = support.REPOSITORY
SKILL = "project-memory"
DIRECTORY = CLONE / SKILL
SPRINT = CLONE / "prd-implementation"
LESSONS = (SKILL, "lifecycle.md", "lessons")
WRITERS = ("implementation-manager", "product-manager", "architect")


def text_of(*parts: str) -> str:
    return CLONE.joinpath(*parts).read_text(encoding="utf-8")


def check_module():
    """``check.py`` of the sprint skill, loaded by its path. It starts no
    process and reads nothing when it is imported."""
    spec = importlib.util.spec_from_file_location("sprint_check",SPRINT / "scripts" / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheSkill(support.ScratchCase):
    def test_it_is_there_for_both_providers_and_is_no_process_skill(self) -> None:
        where = Locations(home=self.home, clone=CLONE)
        report = validate.check(where)
        self.assertEqual(report.lines(), [])
        self.assertEqual(tuple(report.skills[SKILL].providers), ("claude-code", "codex"))
        self.assertFalse(report.skills[SKILL].invoke_only)
        for name in ("SKILL.md", "references/format.md", "references/lifecycle.md", "references/loading.md",
                     "scripts/settings.py"):
            self.assertTrue((DIRECTORY / name).is_file(), name)
        self.assertIn("\ncompatibility: claude-code, codex\n", text_of(SKILL, "SKILL.md"))
        # No stage file: none of its files needs a row of the binding table.
        run = validate._Run(where)
        validate._find_skills(run)
        self.assertEqual(validate.stage_files(run, run.skills[SKILL].directory), [])

    def test_its_launcher_is_the_sprint_skills(self) -> None:
        mine = (DIRECTORY / "scripts" / "settings.py").read_bytes()
        self.assertEqual(mine, (SPRINT / "scripts" / "settings.py").read_bytes())
        self.assertEqual(mine, (CLONE / "epic-implementation" / "scripts" / "settings.py").read_bytes())

    def test_every_file_it_links_to_exists(self) -> None:
        for name in ("SKILL.md", "references/format.md", "references/lifecycle.md", "references/loading.md"):
            file = DIRECTORY / name
            for target in re.findall(r"\]\(([^)#<]+\.md)\)", file.read_text(encoding="utf-8")):
                with self.subTest(file=name, target=target):
                    if not target.startswith("docs/"):  # a path of the example project
                        self.assertTrue((file.parent / target).is_file())

    def test_the_markers_and_the_limits_are_the_check_commands(self) -> None:
        check = check_module()
        self.assertEqual((check.INDEX_LINES, check.INDEX_LINE_LIMIT), (50, 150))
        form = text_of(SKILL, "references", "format.md")
        for marker in (check.INDEX_START, check.INDEX_END):
            self.assertEqual(form.count(marker + "\n"), 1, marker)
        for name in ("SKILL.md", "references/format.md", "references/lifecycle.md"):
            flat = " ".join(text_of(SKILL, *name.split("/")).replace("*", "").split())
            with self.subTest(file=name):
                self.assertIn("at most 50 lines of at most 150 characters", flat.lower())

    def test_the_example_index_passes_the_check_command(self) -> None:
        check = check_module()
        form = text_of(SKILL, "references", "format.md")
        example = re.search(r"```markdown\n(## Project memory\n.*?)```", form, re.S).group(1)
        lines = example.replace("<memory dir>", "docs/memory").splitlines()
        found: list[tuple] = []
        check.check_index(lines, lambda *fault: found.append(fault))
        self.assertEqual(found, [])
        start, end = lines.index(check.INDEX_START), lines.index(check.INDEX_END)
        block = lines[start + 1:end]
        self.assertEqual(len(block), 2)
        self.assertTrue(all(line.startswith("- ") for line in block))
        # The fixed line is the last one, and names the local index file.
        self.assertIn("docs/memory/local/INDEX.md", block[-1])
        # One line over either limit is reported: the check really ran.
        over = lines[:end] + ["- " + "x" * 149] + lines[end:]
        check.check_index(over, lambda *fault: found.append(fault))
        self.assertEqual([fault[1] for fault in found], ["index-line-too-long"])

    def test_a_lesson_file_states_the_four_things(self) -> None:
        form = text_of(SKILL, "references", "format.md")
        for part in ("\n## What\n", "\n## Why\n", "\n## When it applies\n", "\n**Roles:** "):
            self.assertIn(part, form)
        self.assertIn("`<memory dir>/local/`", form)
        self.assertIn(".gitignore", form)

    def test_the_lifecycle_has_every_stage_and_both_lists(self) -> None:
        life = text_of(SKILL, "references", "lifecycle.md")
        for heading in ("What is worth recording", "What is not", "Propose", "Write", "Correct", "Consolidate", "Remove"):
            self.assertIn(f"\n## {heading}\n", life)
        flat = " ".join(life.split())
        self.assertIn("Nothing is written without the user's approval", flat.replace("*", ""))
        # v1's two lists, carried over.
        for worth in ("the plan and the code drift apart", "Verification commands and their typical runtimes",
                      "surfaces that must move together", "A correction the user had to repeat"):
            self.assertIn(worth, flat)
        for not_worth in ("the process text already says", "the project's instruction file already says",
                          "the code says", "`git log`"):
            self.assertIn(not_worth, flat)


class WhoWritesALesson(support.ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.where = Locations(home=self.home, clone=CLONE)
        self.rows = definitions.bindings(self.where)

    def bound(self) -> dict[str, list]:
        return {role: [row for row in mine if row.skill == SKILL] for role, mine in self.rows.items()
                if any(row.skill == SKILL for row in mine)}

    def test_the_roles_that_write_a_lesson_have_the_row(self) -> None:
        bound = self.bound()
        self.assertEqual(sorted(bound), sorted(WRITERS))
        loaded = roles.load_all(self.where)
        for role, mine in bound.items():
            with self.subTest(role=role):
                self.assertEqual([(row.skill, row.stage, row.part) for row in mine], [LESSONS])
                self.assertTrue(loaded[role].data["limits"]["edits"])
                self.assertLessEqual(len(mine[0].note), 200)
                self.assertRegex(mine[0].note, r"\bthe user(?:'s approval| approved)\b")
        build_lead = bound["implementation-manager"][0].note
        # One rule for when the build lead proposes, and none from a hotfix.
        self.assertIn("only in the report of the brief that writes or deletes the last STATE; a hotfix, none.", build_lead)
        self.assertIn("if any, from STATE's candidates and your own", build_lead)
        for role in ("product-manager", "architect"):
            self.assertIn("in a `ready for the gate` or `stopped` hand-back or, loaded, to the user", bound[role][0].note)

    def test_the_manager_and_the_coder_have_none(self) -> None:
        loaded = roles.load_all(self.where)
        self.assertFalse(loaded["manager"].data["limits"]["edits"])
        self.assertNotIn("manager", self.bound())
        self.assertNotIn("coder", self.bound())

    def test_the_row_reaches_each_role_with_the_skills_place(self) -> None:
        places = {"claude-code": "~/.claude/skills", "codex": "~/.agents/skills"}
        seen = set()
        for found in definitions.materials(self.where, select=lambda role: definitions.PROVIDERS, hard=False):
            if found.role.name not in WRITERS:
                continue
            section = found.body[-2]
            self.assertIn(f"\n\nIn `{places[found.provider]}/{SKILL}/references/`:\n\n- `lifecycle.md`, part `lessons`: ", section)
            seen.add((found.role.name, found.provider))
        self.assertEqual(len(seen), 2 * len(WRITERS))

if __name__ == "__main__":
    unittest.main()
