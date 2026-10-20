"""``init``: the settings file it writes, its questions and flags, the
model list it checks the mapping against, and running it again.

Every run has a scratch home, project and clone. The provider's program is
``provider_stub``: ``PATH`` holds its directory and nothing else, so the
command finds and starts it the way it finds and starts the real one, and
Claude Code counts as installed because its scratch home exists.
"""
from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import provider_stub
import support
from fileops_support import SYMLINKS, snapshot
from provider_stub import BUNDLED, LIVE
from wfsetup import commands, fileops, homes, modellist, settings, tomlio
from wfsetup.commands import init
from wfsetup.locations import Locations
from wfsetup.manifest import Roots

EQUAL = "model-list-equal.json"
MISSING = "model-list-missing-mapped.json"
NEW = "model-list-new-model.json"

CLAUDE_TIERS = {"fast": "haiku", "standard": "sonnet", "deep": "opus", "frontier": "fable"}
CODEX_TIERS = {"fast": "gpt-6-luna", "standard": "gpt-6.1-sol", "deep": "gpt-6.1-sol", "frontier": "gpt-6-astra"}
EFFORTS = {"low": "low", "medium": "medium", "high": "high", "max": "max"}
PINNED = {
    "claude-code": {"tiers": CLAUDE_TIERS, "efforts": EFFORTS},
    "codex": {"tiers": CODEX_TIERS, "efforts": EFFORTS},
}

# Every question answered by a flag, with the proposals as the answers.
ALL_MAPPINGS = [
    argument
    for provider, tiers in (("claude-code", CLAUDE_TIERS), ("codex", CODEX_TIERS))
    for flag, table in (("--tier", tiers), ("--effort", EFFORTS))
    for name, value in table.items()
    for argument in (flag, f"{provider}:{name}={value}")
]
ALL_SETTINGS = [
    "--docs-dir", "docs", "--questions", "all-together", "--recommend", "--roles", "--no-manager-default",
    "--no-high-stakes", "--max-parallel-coders", "3", "--memory-dir", "docs/memory",
]


class InitCase(support.ScratchCase):
    CLAUDE = True

    def setUp(self) -> None:
        super().setUp()
        # Outside the scratch root, so that the stub's log is in no snapshot.
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.stub = provider_stub.StubProgram(Path(scratch.name).resolve() / "stub")
        self.stub.answer(LIVE, provider_stub.fixture(EQUAL))
        if self.CLAUDE:
            (self.home / ".claude").mkdir()
        for patch in (
            mock.patch.dict(os.environ, {"PATH": str(self.stub.bin)}),
            mock.patch.object(init, "_terminal", return_value=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.backups = self.home / ".agents" / "workflow-setup" / "backups"

    def init(self, *argv: str, project: bool = False) -> tuple[int, str, str]:
        places = ["--home", str(self.home)]
        if project:
            places += ["--project", str(self.project)]
        return support.run("init", *places, *argv)

    def ok(self, *argv: str, project: bool = False) -> str:
        code, out, err = self.init(*argv, project=project)
        self.assertEqual((code, err), (0, ""), out)
        return out

    def refused(self, *argv: str, project: bool = False) -> str:
        """The run fails, says why on stderr, and changes nothing."""
        before = self.tree()
        code, out, err = self.init(*argv, project=project)
        self.assertEqual(code, 2, out + err)
        self.assertEqual(self.tree(), before)
        return err

    def tree(self) -> tuple[dict, dict]:
        return snapshot(self.home), snapshot(self.project)

    def data(self, file: Path | None = None) -> dict:
        return tomllib.loads((file or self.user_file).read_text(encoding="utf-8"))

    def answers(self, *lines: str):
        """Standard input as a terminal on which ``lines`` are typed."""
        init._terminal.return_value = True
        asked = mock.patch.object(builtins, "input", side_effect=list(lines))
        self.addCleanup(asked.stop)
        return asked.start()


class ProposalTests(InitCase):
    def test_yes_writes_the_proposals(self) -> None:
        out = self.ok("--yes")
        self.assertEqual(self.data(), {"schema_version": 1, "providers": PINNED})
        self.assertIn(f"written: {self.user_file}", out)
        self.assertIn("create file home:.agents/workflow.toml", out)
        self.assertEqual(self.stub.calls(), [["debug", "models"]])

    def test_user_is_the_default_and_may_be_said(self) -> None:
        self.ok("--yes", "--user")
        self.assertTrue(self.user_file.exists())
        self.assertFalse(self.project_file.exists())

    def test_user_and_project_together_are_refused(self) -> None:
        err = self.refused("--yes", "--user", project=True)
        self.assertEqual(err, "error: --user and --project: give one; they name two different files\n")

    def test_the_file_says_what_it_is_and_how_to_change_it(self) -> None:
        self.ok("--yes")
        text = self.user_file.read_text(encoding="utf-8")
        header = [line for line in text.splitlines() if line.startswith("#")]
        self.assertEqual(header[0], "# Workflow settings: the user layer (~/.agents/workflow.toml).")
        self.assertIn("# Written by `workflow_setup.py init`.", header)
        joined = " ".join(line[1:].strip() for line in header)
        self.assertIn("run `init` again with a flag", joined)
        self.assertIn("or edit this file", joined)
        self.assertIn("a key that is not here has the value of the layer below", joined)
        self.assertIn("an update of the clone does not change them", joined)
        self.assertNotIn("\r", text)
        self.assertNotIn(str(self.home), text)
        self.assertTrue(text.index("schema_version = 1") > text.index(header[-1]))

    def test_the_written_file_loads_and_show_names_the_layer(self) -> None:
        self.ok("--yes", "--docs-dir", "sprints", "--tier", "codex:deep=gpt-6-astra")
        entries = settings.resolve(Locations(home=self.home, clone=self.clone))
        self.assertEqual(entries["process.docs_dir"].value, "sprints")
        self.assertEqual(entries["process.docs_dir"].layer, "user")
        self.assertEqual(entries["providers.codex.tiers.deep"].value, "gpt-6-astra")
        self.assertEqual(entries["providers.codex.tiers.deep"].layer, "user")
        self.assertEqual(entries["providers.codex.tiers.fast"].layer, "user")
        self.assertEqual(entries["process.recommend"].layer, "shipped")
        code, out, err = self.show(project=False)
        self.assertEqual((code, err), (0, ""))
        self.assertIn('process.docs_dir = "sprints"  (user)\n', out)
        self.assertIn('process.questions = "all-together"  (shipped)\n', out)
        self.assertIn('providers.codex.tiers.deep = "gpt-6-astra"  (user)\n', out)
        self.assertIn('providers.claude-code.efforts.max = "max"  (user)\n', out)
        code, out, err = self.show("roles", project=False)
        self.assertEqual(code, 0, err)
        self.assertIn('coder-hard @ codex: model = "gpt-6-astra"  (user: ', out)

    def test_the_mapping_is_shown_as_a_table(self) -> None:
        out = self.ok("--yes", "--dry-run")
        self.assertIn(
            "codex: the mapping\n"
            "  tier      model        efforts the model accepts\n"
            "  fast      gpt-6-luna   low, medium, high, xhigh, max\n"
            "  standard  gpt-6.1-sol  low, medium, high, xhigh, max, ultra\n"
            "  deep      gpt-6.1-sol  low, medium, high, xhigh, max, ultra\n"
            "  frontier  gpt-6-astra  low, medium, high, xhigh, max, ultra\n"
            "  effort names: low = low, medium = medium, high = high, max = max\n",
            out,
        )
        self.assertIn("  fast      haiku   none: the model takes no effort setting\n", out)

    def test_the_output_ends_with_what_to_run_next(self) -> None:
        with mock.patch.object(commands, "names", return_value={"init": "init", "render": "render"}):
            out = self.ok("--yes")
        self.assertEqual(
            out.splitlines()[-1],
            "next: `workflow_setup.py render` installs the skills and the role definitions with these "
            "settings, then `workflow_setup.py doctor` (not in this clone yet) checks the result",
        )
        with mock.patch.object(commands, "names", return_value={"doctor": "doctor", "init": "init", "render": "render"}):
            out = self.ok("--yes")
        self.assertNotIn("not in this clone yet", out)
        self.assertTrue(out.splitlines()[-1].startswith("next: "))


class FlagTests(InitCase):
    def test_each_flag_sets_its_key(self) -> None:
        self.ok(
            "--yes",
            "--tier", "codex:deep=gpt-6-astra", "--tier", "claude-code:standard=opus",
            "--effort", "codex:max=ultra", "--effort", "claude-code:high=xhigh",
            "--role-model", "codex:coder-hard=gpt-6-sol",
            "--docs-dir", "../planning/docs", "--questions", "one-at-a-time", "--no-recommend",
            "--manager-default", "--high-stakes", "--max-parallel-coders", "5", "--memory-dir", "notes/memory",
            "--tier", "codex:fast=gpt-6-sol",
        )
        self.assertEqual(self.data(), {
            "schema_version": 1,
            "process": {"docs_dir": "../planning/docs", "questions": "one-at-a-time", "recommend": False},
            "roles": {"manager_default": True, "high_stakes": True, "max_parallel_coders": 5},
            "memory": {"dir": "notes/memory"},
            "providers": {
                "claude-code": {"tiers": {**CLAUDE_TIERS, "standard": "opus"}, "efforts": {**EFFORTS, "high": "xhigh"}},
                "codex": {
                    "tiers": {**CODEX_TIERS, "deep": "gpt-6-astra", "fast": "gpt-6-sol"},
                    "efforts": {**EFFORTS, "max": "ultra"},
                    "role_models": {"coder-hard": "gpt-6-sol"},
                },
            },
        })

    def test_an_answer_equal_to_the_default_is_not_written(self) -> None:
        self.ok("--yes", *ALL_SETTINGS)
        self.assertEqual(self.data(), {"schema_version": 1, "providers": PINNED})

    def test_flags_for_every_question_need_only_the_confirmation(self) -> None:
        err = self.refused(*ALL_MAPPINGS, *ALL_SETTINGS)
        self.assertIn("error: the confirmation to write: not answered.", err)
        self.assertIn("Give --yes, or --yes", err)
        self.ok(*ALL_MAPPINGS, *ALL_SETTINGS, "--yes")
        self.assertEqual(self.data(), {"schema_version": 1, "providers": PINNED})

    def test_a_bad_value_is_refused_with_the_schemas_message(self) -> None:
        for argv, message in (
            (["--questions", "sometimes"],
             '--questions: process.questions: "sometimes" is not allowed; allowed values: one-at-a-time, all-together'),
            (["--docs-dir", ""], "--docs-dir: process.docs_dir: must not be empty"),
            (["--memory-dir", "  "], "--memory-dir: memory.dir: must not be blank; it holds only white space"),
            (["--max-parallel-coders", "0"],
             "--max-parallel-coders: roles.max_parallel_coders: 0 is too small; the least allowed is 1"),
            (["--max-parallel-coders", "many"],
             "--max-parallel-coders: roles.max_parallel_coders: expected an integer, got a string"),
            (["--tier", "codex:huge=gpt-6-sol"],
             "--tier codex:huge=gpt-6-sol: providers.codex.tiers.huge: unknown key; known here: fast, standard, "
             "deep, frontier"),
            (["--tier", "codex:deep="], "--tier codex:deep=: providers.codex.tiers.deep: must not be empty"),
            (["--effort", "codex:extreme=max"],
             "--effort codex:extreme=max: providers.codex.efforts.extreme: unknown key; known here: low, medium, "
             "high, max"),
            (["--role-model", "codex:Not_A_Role=gpt-6-sol"],
             "--role-model codex:Not_A_Role=gpt-6-sol: providers.codex.role_models.Not_A_Role: unknown key; "
             "known here: <role id>"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.refused("--yes", *argv), f"error: {message}\n")

    def test_a_mapping_flag_of_another_shape_is_refused(self) -> None:
        for argv, message in (
            (["--tier", "deep=gpt-6-sol"], "--tier deep=gpt-6-sol: expected PROVIDER:TIER=MODEL, such as"),
            (["--effort", "codex:max"], "--effort codex:max: expected PROVIDER:NAME=VALUE, such as"),
            (["--role-model", ":coder=x"], "--role-model :coder=x: expected PROVIDER:ROLE=MODEL, such as"),
            (["--tier", "codex:deep=gpt-6-sol", "--tier", "codex:deep=gpt-6-astra"],
             "--tier: codex:deep is given twice, with different values"),
            (["--tier", "acme:deep=a-mid"],
             "--tier acme:deep=a-mid: acme is not a provider this run sets up; installed here, with a "
             "dictionary: claude-code, codex"),
        ):
            with self.subTest(argv=argv):
                self.assertIn(f"error: {message}", self.refused("--yes", *argv))

    def test_a_role_model_is_taken_out_with_an_empty_model(self) -> None:
        self.ok("--yes", "--role-model", "codex:coder=gpt-6-sol")
        self.assertEqual(self.data()["providers"]["codex"]["role_models"], {"coder": "gpt-6-sol"})
        self.ok("--yes")
        self.assertEqual(self.data()["providers"]["codex"]["role_models"], {"coder": "gpt-6-sol"})
        out = self.ok("--yes", "--role-model", "codex:coder=")
        self.assertNotIn("role_models", self.data()["providers"]["codex"])
        self.assertIn('providers.codex.role_models.coder: "gpt-6-sol" -> (taken out; the value is then nothing)', out)

    def test_a_role_model_for_no_role_is_noted(self) -> None:
        out = self.ok("--yes", "--role-model", "codex:reviewer=gpt-6-sol")
        self.assertIn("providers.codex.role_models.reviewer: no role definition has the id reviewer", out)


UNSHARED_WHY = "inside WSL, where the Windows side's links cannot lead"


class RememberedChoiceTests(InitCase):
    """``--roles`` / ``--no-roles`` and ``--allow-unshared-clone``: the two
    choices `render` and `doctor` would otherwise need on every run."""

    def unshared(self, shared: bool | None = False) -> None:
        """The clone as one the other side cannot read (a scratch home is
        never asked, so the standing is given by hand)."""
        why = UNSHARED_WHY if shared is False else "not asked: a scratch home (--home)"
        standing = homes.CloneStanding(self.clone, self.clone, shared, why)
        patch = mock.patch.object(homes, "clone_standing", return_value=standing)
        patch.start()
        self.addCleanup(patch.stop)

    def test_no_roles_is_written_once_and_roles_takes_it_out(self) -> None:
        out = self.ok("--yes", "--no-roles")
        self.assertEqual(self.data()["roles"], {"enabled": False})
        self.assertIn("  roles.enabled = false  (in this file)", out.splitlines())
        out = self.ok("--yes", "--roles")
        self.assertNotIn("roles", self.data())  # equal to the layer below: taken out
        self.assertIn("  roles.enabled: false -> (taken out; the value is then true from the shipped layer)", out)

    def test_a_project_may_turn_its_roles_off(self) -> None:
        self.ok("--yes", "--no-roles", project=True)
        self.assertEqual(self.data(self.project_file)["roles"], {"enabled": False})
        self.assertFalse(self.user_file.exists())

    def test_the_clone_question_is_not_asked_where_it_does_not_apply(self) -> None:
        out = self.ok("--yes")
        self.assertNotIn("setup", self.data())
        self.assertIn("  setup.allow_unshared_clone = false  (shipped; not written; not asked: the clone needs no "
                      "such permission here (a scratch home (--home)))", out.splitlines())
        # No terminal and no --yes: every other question is answered, and this one is not asked.
        self.ok(*ALL_MAPPINGS, *ALL_SETTINGS, "--yes")
        code, out, err = self.init(*ALL_MAPPINGS, *ALL_SETTINGS)
        self.assertNotIn("allow_unshared_clone", err)

    def test_where_it_applies_it_is_asked_and_proposes_a_shared_clone(self) -> None:
        self.unshared()
        asked = self.answers(*[""] * 13, "y")
        out = self.ok()
        prompts = [call.args[0] for call in asked.call_args_list]
        self.assertEqual(len(prompts), 14)
        self.assertEqual(prompts[12], "setup.allow_unshared_clone [false] (--allow-unshared-clone or "
                                      "--no-allow-unshared-clone): ")
        self.assertIn(f"the clone {self.clone} is {UNSHARED_WHY}: render and doctor refuse it unless "
                      "--allow-unshared-clone is given on each run, or setup.allow_unshared_clone is true", out)
        self.assertIn("does not install from this clone (", out)
        self.assertNotIn("nothing on the other side", out)
        self.assertNotIn("setup", self.data())
        # Answered true, it is written; the next proposal is what the file holds.
        self.answers(*[""] * 12, "y", "y")
        self.ok()
        self.assertEqual(self.data()["setup"], {"allow_unshared_clone": True})
        asked = self.answers(*[""] * 13)
        self.ok("--dry-run")
        self.assertEqual(asked.call_args_list[12].args[0], "setup.allow_unshared_clone [true] "
                         "(--allow-unshared-clone or --no-allow-unshared-clone): ")

    def test_where_it_applies_yes_keeps_the_safe_proposal_and_the_flag_answers(self) -> None:
        self.unshared()
        self.ok("--yes")
        self.assertNotIn("setup", self.data())
        err = self.refused(*ALL_MAPPINGS, *ALL_SETTINGS)
        self.assertIn("error: setup.allow_unshared_clone: not answered", err)
        self.assertIn("Give --allow-unshared-clone or --no-allow-unshared-clone, or --yes", err)
        self.ok("--yes", "--allow-unshared-clone")
        self.assertEqual(self.data()["setup"], {"allow_unshared_clone": True})
        self.ok("--yes")  # the value in effect is proposed, and kept
        self.assertEqual(self.data()["setup"], {"allow_unshared_clone": True})
        self.ok("--yes", "--no-allow-unshared-clone")
        self.assertNotIn("setup", self.data())

    def test_the_flag_sets_it_where_it_is_not_asked(self) -> None:
        self.ok("--yes", "--allow-unshared-clone")
        self.assertEqual(self.data()["setup"], {"allow_unshared_clone": True})
        out = self.ok("--yes")  # not asked here, and the file's value stays
        self.assertEqual(self.data()["setup"], {"allow_unshared_clone": True})
        self.assertIn("  setup.allow_unshared_clone = true  (in this file; not asked: the clone needs no such "
                      "permission here (a scratch home (--home)))", out.splitlines())

    def test_a_project_neither_asks_nor_takes_it(self) -> None:
        self.unshared()
        err = self.refused("--yes", "--allow-unshared-clone", project=True)
        self.assertEqual(err, "error: --allow-unshared-clone: setup.allow_unshared_clone is read from the user's file "
                              "alone (~/.agents/workflow.toml): it is a fact of this machine, not of a project. Give "
                              "it to `init` without --project\n")
        err = self.refused("--yes", "--no-allow-unshared-clone", project=True)
        self.assertTrue(err.startswith("error: --no-allow-unshared-clone: setup.allow_unshared_clone is read"), err)
        out = self.ok("--yes", project=True)
        self.assertNotIn("allow_unshared_clone", out)
        self.assertFalse(self.project_file.exists() and "setup" in self.data(self.project_file))
        # A project's file that holds the group is a fault init does not write over.
        self.write(self.project_file, "[setup]\nallow_unshared_clone = true\n")
        err = self.refused("--yes", project=True)
        self.assertIn(f"{self.project_file}: setup: read from the user's settings file alone", err)
        self.assertIn("init changes nothing while a settings file has a fault", err)

    def test_render_and_doctor_read_what_init_wrote(self) -> None:
        self.ok("--yes", "--no-roles", "--allow-unshared-clone")
        entries = settings.resolve(Locations(home=self.home, clone=self.clone), ("roles", "setup"))
        self.assertEqual((entries["roles.enabled"].value, entries["roles.enabled"].layer), (False, "user"))
        found = entries["setup.allow_unshared_clone"]
        self.assertEqual((found.value, found.layer, found.file), (True, "user", self.user_file))
        allowance = homes.clone_allowance(Locations(home=self.home, clone=self.clone))
        self.assertEqual((allowance.allowed, allowance.by), (True, homes.BY_SETTING))


class NoTerminalTests(InitCase):
    def test_without_yes_a_question_with_no_flag_is_an_error_naming_the_flag(self) -> None:
        err = self.refused()
        self.assertTrue(err.startswith("error: claude-code: the tier mapping: not answered. Standard input is not a terminal"), err)
        self.assertIn(
            "Give --tier claude-code:fast=MODEL, --tier claude-code:standard=MODEL, --tier claude-code:deep=MODEL, "
            "--tier claude-code:frontier=MODEL, or --yes to accept what is proposed",
            err,
        )

    def test_only_the_unanswered_names_are_named(self) -> None:
        given = [
            argument
            for tier, model in CLAUDE_TIERS.items() if tier != "deep"
            for argument in ("--tier", f"claude-code:{tier}={model}")
        ]
        err = self.refused(*given)
        self.assertIn("Give --tier claude-code:deep=MODEL, or --yes", err)

    def test_each_kind_of_question_names_its_flag(self) -> None:
        err = self.refused(*ALL_MAPPINGS[:8])
        self.assertIn("claude-code: the effort mapping: not answered", err)
        self.assertIn("--effort claude-code:low=VALUE", err)
        err = self.refused(*ALL_MAPPINGS)
        self.assertIn("error: process.docs_dir: not answered", err)
        self.assertIn("Give --docs-dir, or --yes", err)
        err = self.refused(*ALL_MAPPINGS, "--docs-dir", "docs", "--questions", "all-together")
        self.assertIn("error: process.recommend: not answered", err)
        self.assertIn("Give --recommend or --no-recommend, or --yes", err)

    def test_a_child_process_with_no_terminal_does_not_wait(self) -> None:
        script = self.install_tool()
        environment = {**support.child_environment(), "PATH": str(self.stub.bin)}
        argv = [sys.executable, "-B", str(script), "init", "--home", str(self.home)]
        done = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            env=environment, timeout=120,
        )
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("error: claude-code: the tier mapping: not answered", done.stderr)
        self.assertIn("--tier claude-code:fast=MODEL", done.stderr)
        self.assertFalse(self.user_file.exists())
        done = subprocess.run(
            [*argv, "--yes"], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            env=environment, timeout=120,
        )
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stdout)
        self.assertEqual(self.data(), {"schema_version": 1, "providers": PINNED})


class TerminalTests(InitCase):
    def test_enter_accepts_every_proposal_and_y_writes(self) -> None:
        asked = self.answers(*[""] * 12, "y")
        self.ok()
        self.assertEqual(self.data(), {"schema_version": 1, "providers": PINNED})
        prompts = [call.args[0] for call in asked.call_args_list]
        self.assertEqual(len(prompts), 13)
        self.assertIn("(--tier claude-code:...)", prompts[0])
        self.assertIn("(--effort claude-code:...)", prompts[1])
        self.assertIn("(--tier codex:...)", prompts[2])
        self.assertEqual(prompts[4], 'process.docs_dir ["docs"] (--docs-dir): ')
        self.assertEqual(prompts[6], "process.recommend [true] (--recommend or --no-recommend): ")
        self.assertEqual(prompts[7], "roles.enabled [true] (--roles or --no-roles): ")
        self.assertEqual(prompts[12], "Write these settings? [y/N] (--yes): ")
        # A scratch home: the clone's question does not apply, and is not asked.
        self.assertFalse(any("allow_unshared_clone" in prompt for prompt in prompts))

    def test_anything_but_yes_writes_nothing(self) -> None:
        self.answers(*[""] * 12, "")
        before = self.tree()
        code, out, err = self.init()
        self.assertEqual((code, err), (1, ""))
        self.assertIn("nothing was written", out)
        self.assertEqual(self.tree(), before)

    def test_a_flag_is_not_asked_again_and_yes_asks_nothing(self) -> None:
        asked = self.answers(*[""] * 10, "yes")
        self.ok("--docs-dir", "sprints", *ALL_MAPPINGS[:8])
        self.assertEqual(asked.call_count, 11)
        self.assertEqual(self.data()["process"], {"docs_dir": "sprints"})
        asked = self.answers()
        self.ok("--yes", "--docs-dir", "other")
        self.assertEqual(asked.call_count, 0)

    def test_answers_change_the_values(self) -> None:
        asked = self.answers(
            "deep=fable", "", "deep=gpt-6-astra fast=gpt-6-sol", "max=ultra",
            "sprints", "one-at-a-time", "n", "", "y", "", "4", "", "y",
        )
        out = self.ok()
        self.assertEqual(asked.call_count, 13)
        data = self.data()
        self.assertEqual(data["providers"]["claude-code"]["tiers"]["deep"], "fable")
        self.assertEqual(data["providers"]["codex"]["tiers"], {**CODEX_TIERS, "deep": "gpt-6-astra", "fast": "gpt-6-sol"})
        self.assertEqual(data["providers"]["codex"]["efforts"]["max"], "ultra")
        self.assertEqual(data["process"], {"docs_dir": "sprints", "questions": "one-at-a-time", "recommend": False})
        self.assertEqual(data["roles"], {"manager_default": True, "max_parallel_coders": 4})
        self.assertNotIn("memory", data)
        # The choices are the offered entries: the hidden one is not among them.
        self.assertIn("  models: gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-6-luna, gpt-5.5\n", out)
        self.assertNotIn("gpt-reserve", out)

    def test_a_bad_answer_is_asked_again(self) -> None:
        asked = self.answers(
            "deep", "huge=opus", "", "", "", "",
            "", "sometimes", "", "", "", "", "", "none", "2", "", "y",
        )
        out = self.ok()
        self.assertEqual(asked.call_count, 17)
        self.assertIn("  deep: expected tier=MODEL\n", out)
        self.assertIn("  answer: providers.claude-code.tiers.huge: unknown key; known here: fast, standard, deep, frontier\n", out)
        self.assertIn('  answer: process.questions: "sometimes" is not allowed; allowed values: one-at-a-time, all-together\n', out)
        self.assertIn("  answer: roles.max_parallel_coders: expected an integer, got a string\n", out)
        self.assertEqual(self.data()["roles"], {"max_parallel_coders": 2})

    def test_a_missing_model_must_be_replaced_at_the_prompt(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(MISSING))
        asked = self.answers("", "", "", "frontier=gpt-9", "frontier=gpt-6-sol", *[""] * 9, "y")
        out = self.ok()
        self.assertEqual(asked.call_count, 15)
        self.assertIn('providers.codex.tiers.frontier: the model "gpt-6-astra" is not in codex\'s own list', out)
        self.assertIn('providers.codex.tiers.frontier: the model "gpt-9" is not in codex\'s own list', out)
        self.assertEqual(self.data()["providers"]["codex"]["tiers"]["frontier"], "gpt-6-sol")

    def test_input_that_ends_is_an_error(self) -> None:
        self.answers()
        builtins.input.side_effect = EOFError
        self.assertEqual(
            self.refused(), "error: standard input ended before every question was answered\n"
        )

    def test_a_dry_run_asks_the_questions_and_not_the_confirmation(self) -> None:
        asked = self.answers(*[""] * 12)
        before = self.tree()
        out = self.ok("--dry-run")
        self.assertEqual(asked.call_count, 12)
        self.assertIn("dry run: nothing was written", out)
        self.assertEqual(self.tree(), before)


class ModelListTests(InitCase):
    def test_a_provider_with_no_list_uses_the_dictionary_and_says_so(self) -> None:
        out = self.ok("--yes")
        self.assertIn(
            "claude-code: no model list: claude-code has no command that lists models without starting a "
            "session; the dictionary alone is used\n",
            out,
        )
        self.assertIn("codex: checked against the list of `codex debug models` (6 models, 1 of them hidden)\n", out)
        self.assertEqual(self.data()["providers"]["claude-code"]["tiers"], CLAUDE_TIERS)

    def test_a_missing_mapped_model_is_an_error_with_yes(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(MISSING))
        err = self.refused("--yes")
        self.assertEqual(
            err,
            'error: providers.codex.tiers.frontier: the model "gpt-6-astra" is not in codex\'s own list and '
            "must be replaced: give --tier codex:frontier=MODEL (listed: gpt-6.1-sol, gpt-6-sol, gpt-6-luna, "
            "gpt-5.5), or --allow-unlisted to keep it\n",
        )

    def test_a_missing_mapped_model_is_shown_and_replaced_by_a_flag(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(MISSING))
        out = self.ok("--yes", "--tier", "codex:frontier=gpt-6-sol")
        self.assertIn("  in the dictionary and not in the list: gpt-6-astra\n", out)
        self.assertEqual(self.data()["providers"]["codex"]["tiers"], {**CODEX_TIERS, "frontier": "gpt-6-sol"})

    def test_a_flag_that_names_a_missing_model_is_refused_too(self) -> None:
        err = self.refused("--yes", "--tier", "codex:deep=gpt-9")
        self.assertIn('providers.codex.tiers.deep: the model "gpt-9" is not in codex\'s own list', err)
        err = self.refused("--yes", "--role-model", "codex:coder=gpt-9")
        self.assertIn('providers.codex.role_models.coder: the model "gpt-9" is not in codex\'s own list', err)
        self.assertIn("--role-model codex:coder=MODEL", err)

    def test_allow_unlisted_keeps_a_missing_model_and_says_so(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(MISSING))
        out = self.ok("--yes", "--allow-unlisted")
        self.assertIn(
            '  note: providers.codex.tiers.frontier: "gpt-6-astra" is not in codex\'s own list; kept, as '
            "--allow-unlisted says\n",
            out,
        )
        self.assertEqual(self.data()["providers"]["codex"]["tiers"], CODEX_TIERS)

    def test_a_new_model_is_named_and_can_be_chosen(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(NEW))
        out = self.ok("--yes", "--tier", "codex:frontier=gpt-7-nova", "--effort", "codex:max=turbo")
        self.assertIn("  in the list and not in the dictionary: gpt-7-nova\n", out)
        self.assertIn("  frontier  gpt-7-nova   low, medium, high, max, turbo\n", out)
        self.assertEqual(self.data()["providers"]["codex"]["tiers"]["frontier"], "gpt-7-nova")

    def test_a_new_model_is_offered_at_the_prompt_and_a_hidden_one_is_not(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(NEW))
        self.answers("", "", "deep=gpt-7-nova", *[""] * 9, "y")
        out = self.ok()
        self.assertIn(
            "  models: gpt-7-nova (new: not in the dictionary), gpt-6.1-sol, gpt-6-astra, gpt-6-sol, "
            "gpt-6-luna, gpt-5.5\n",
            out,
        )
        self.assertEqual(self.data()["providers"]["codex"]["tiers"]["deep"], "gpt-7-nova")

    def test_a_hidden_model_named_by_a_flag_stays_with_a_note(self) -> None:
        out = self.ok("--yes", "--tier", "codex:fast=gpt-reserve")
        self.assertIn(
            '  note: providers.codex.tiers.fast: "gpt-reserve" is a hidden entry of codex\'s list '
            '(visibility "hide"); it is not offered, and stays because it is named\n',
            out,
        )

    def test_a_failed_refresh_uses_the_bundled_list(self) -> None:
        self.stub.answer(LIVE, "", code=3, stderr="network unreachable\n")
        self.stub.answer(BUNDLED, provider_stub.fixture(MISSING))
        err = self.refused("--yes")
        self.assertIn('the model "gpt-6-astra" is not in codex\'s own list', err)
        self.assertEqual(self.stub.calls()[-2:], [["debug", "models"], ["debug", "models", "--bundled"]])
        out = self.ok("--yes", "--tier", "codex:frontier=gpt-6-sol")
        self.assertIn("codex: checked against the list of `codex debug models --bundled` (5 models, 1 of them hidden)", out)
        self.assertIn("this is the list shipped with the program, read because `codex debug models` exited with code 3", out)

    def test_a_list_that_cannot_be_read_falls_back_to_the_dictionary(self) -> None:
        for name, answer in (
            ("not json", {"stdout": "Usage: codex debug <COMMAND>\n"}),
            ("empty", {"stdout": '{"models": []}'}),
            ("failing", {"code": 1}),
            ("slow", {"sleep": 60}),
        ):
            with self.subTest(name=name):
                self.stub.answer(LIVE, **answer)
                self.stub.answer(BUNDLED, **answer)
                with mock.patch.object(modellist, "DEFAULT_TIMEOUT", 1):
                    out = self.ok("--yes", "--dry-run")
                self.assertIn("codex: no model list: `codex debug models` ", out)
                self.assertIn("; the dictionary alone is used\n", out)
                self.assertIn("  frontier  gpt-6-astra  low, medium, high, xhigh, max, ultra\n", out)

    def test_with_no_list_a_model_outside_the_dictionary_is_noted(self) -> None:
        out = self.ok("--yes", "--tier", "claude-code:deep=claude-opus-5-5")
        self.assertIn(
            '  note: providers.claude-code.tiers.deep: "claude-opus-5-5" is not in the claude-code dictionary, '
            "and no list was read; nothing is known about the efforts it accepts\n",
            out,
        )
        self.assertIn("  deep      claude-opus-5-5  unknown: the model is not listed\n", out)

    def test_a_codex_that_is_not_on_path_but_has_a_home_uses_the_dictionary(self) -> None:
        (self.home / ".codex").mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(self.root / "nowhere")}):
            out = self.ok("--yes")
        self.assertIn("codex: no model list: the program `codex` is not on PATH; the dictionary alone is used\n", out)
        self.assertEqual(self.data()["providers"]["codex"]["tiers"], CODEX_TIERS)
        self.assertEqual(self.stub.calls(), [])


class EffortTests(InitCase):
    def test_a_value_no_model_accepts_is_refused(self) -> None:
        self.assertEqual(
            self.refused("--yes", "--effort", "claude-code:high=ultra"),
            'error: providers.claude-code.efforts.high: no model of claude-code accepts "ultra"; accepted '
            "values: low, medium, high, xhigh, max\n",
        )

    def test_an_effort_the_model_of_a_role_does_not_accept_is_refused(self) -> None:
        err = self.refused("--yes", "--tier", "codex:deep=gpt-6-luna", "--effort", "codex:high=ultra")
        self.assertIn(
            'error: role coder-hard, provider codex: the model "gpt-6-luna" does not accept the effort "ultra"; '
            "it accepts: low, medium, high, xhigh, max.",
            err,
        )
        self.assertIn("error: role product-manager, provider codex:", err)
        # The same value is fine where no role meets a model that refuses it.
        self.ok("--yes", "--effort", "codex:high=ultra")

    def test_where_there_is_a_list_the_list_decides(self) -> None:
        data = json.loads(provider_stub.fixture(EQUAL))
        data["models"][0]["supported_reasoning_levels"] = [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]
        self.stub.answer(LIVE, json.dumps(data))
        err = self.refused("--yes", "--effort", "codex:high=ultra")
        self.assertIn(
            'role coder-hard, provider codex: the model "gpt-6.1-sol" does not accept the effort "ultra"; '
            "it accepts: low, medium, high.",
            err,
        )
        out = self.ok("--yes")
        self.assertIn("gpt-6.1-sol: the dictionary has the efforts low, medium, high, xhigh, max, ultra; the list has low, medium, high", out)

    def test_the_list_may_accept_what_the_dictionary_does_not_know(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(NEW))
        self.ok("--yes", "--tier", "codex:deep=gpt-7-nova", "--effort", "codex:high=turbo")
        self.assertEqual(self.data()["providers"]["codex"]["efforts"]["high"], "turbo")

    def test_a_role_override_in_the_file_counts(self) -> None:
        self.write(self.user_file, '[roles.manager]\ntier = "fast"\neffort = "max"\n')
        err = self.refused("--yes", "--effort", "codex:max=ultra")
        self.assertIn('role manager, provider codex: the model "gpt-6-luna" does not accept the effort "ultra"', err)


class AgainTests(InitCase):
    def test_the_same_answers_write_nothing(self) -> None:
        argv = ["--yes", "--docs-dir", "sprints", "--tier", "codex:deep=gpt-6-astra", "--no-recommend"]
        self.ok(*argv)
        before = self.tree()
        out = self.ok(*argv)
        self.assertIn(f"nothing to write: {self.user_file} already holds these settings\n", out)
        self.assertEqual(self.tree(), before)
        # What was answered before is now what is proposed.
        out = self.ok("--yes")
        self.assertIn("nothing to write", out)
        self.assertEqual(self.tree(), before)

    def test_other_answers_show_the_difference_back_up_and_rewrite(self) -> None:
        self.ok("--yes", "--docs-dir", "sprints", "--no-recommend")
        was = self.user_file.read_bytes()
        out = self.ok("--yes", "--docs-dir", "plans", "--recommend", "--tier", "codex:deep=gpt-6-astra", "--high-stakes")
        self.assertIn(
            f"changes to {self.user_file}:\n"
            '  process.docs_dir: "sprints" -> "plans"\n'
            "  process.recommend: false -> (taken out; the value is then true from the shipped layer)\n"
            "  roles.high_stakes: (not set; false from the shipped layer) -> true\n"
            '  providers.codex.tiers.deep: "gpt-6.1-sol" -> "gpt-6-astra"\n'
            "replace file home:.agents/workflow.toml (backup)\n",
            out,
        )
        self.assertNotIn("edited outside `init`", out)
        data = self.data()
        self.assertEqual(data["process"], {"docs_dir": "plans"})
        self.assertEqual(data["roles"], {"high_stakes": True})
        (saved,) = list(self.backups.glob("*/home/.agents/workflow.toml"))
        self.assertEqual(saved.read_bytes(), was)
        self.assertIn(f"the file as it was is in {saved.parents[2]}\n", out)

    def test_on_a_terminal_the_rewrite_is_confirmed_and_says_what_is_kept(self) -> None:
        self.ok("--yes")
        asked = self.answers("y")
        self.ok("--docs-dir", "plans", *ALL_MAPPINGS, *ALL_SETTINGS[2:])
        (question,) = [call.args[0] for call in asked.call_args_list]
        self.assertIn("is rewritten from the values above: every key is kept, comments and layout are not", question)
        self.assertIn("The file as it is now is copied to the backup directory first.", question)
        self.assertTrue(question.endswith("Replace it? [y/N] (--yes): "))
        self.assertEqual(self.data()["process"], {"docs_dir": "plans"})
        # Declined, the file stays.
        was = self.tree()
        self.answers("n")
        code, out, _ = self.init("--docs-dir", "other", *ALL_MAPPINGS, *ALL_SETTINGS[2:])
        self.assertEqual(code, 1)
        self.assertEqual(self.tree(), was)

    def test_a_dry_run_shows_the_change_and_writes_nothing(self) -> None:
        self.ok("--yes")
        before = self.tree()
        out = self.ok("--yes", "--dry-run", "--docs-dir", "plans")
        self.assertIn('  process.docs_dir: (not set; "docs" from the shipped layer) -> "plans"\n', out)
        self.assertIn("replace file home:.agents/workflow.toml (backup)\ndry run: nothing was written\n", out)
        self.assertEqual(self.tree(), before)

    def test_a_first_dry_run_shows_the_file_and_writes_nothing(self) -> None:
        before = self.tree()
        out = self.ok("--yes", "--dry-run")
        self.assertIn(f"{self.user_file}, as it would be written:\n    # Workflow settings: the user layer", out)
        self.assertIn('\n    [providers.codex.tiers]\n    fast = "gpt-6-luna"\n', out)
        self.assertIn("create file home:.agents/workflow.toml\ndry run: nothing was written\n", out)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.stub.calls(), [["debug", "models"]])

    def test_a_hand_edited_file_keeps_its_keys(self) -> None:
        self.write(
            self.user_file,
            "# my own notes\n"
            "[process]\n"
            'docs_dir = "sprints"   # where we keep them\n'
            'questions = "one-at-a-time"\n'
            "\n[roles.coder]\n"
            'tier = "deep"\n'
            "\n[providers.acme.tiers]\n"
            'fast = "a-small"\n'
            "\n[providers.codex.tiers]\n"
            'deep = "gpt-6-astra"\n'
            "\n[providers.codex.role_models]\n"
            'manager = "gpt-6-sol"\n',
        )
        was = self.user_file.read_bytes()
        out = self.ok("--yes", "--rewrite-settings", "--memory-dir", "notes")
        self.assertIn("  the file was edited outside `init`: its keys are kept, its comments and layout are not\n", out)
        self.assertIn('  memory.dir: (not set; "docs/memory" from the shipped layer) -> "notes"\n', out)
        self.assertNotIn("process.docs_dir:", out.split("changes to")[1])
        self.assertEqual(self.data(), {
            "schema_version": 1,
            # A value that equals the default stays where the user wrote it.
            "process": {"docs_dir": "sprints", "questions": "one-at-a-time"},
            "roles": {"coder": {"tier": "deep"}},
            "memory": {"dir": "notes"},
            "providers": {
                "acme": {"tiers": {"fast": "a-small"}},
                "claude-code": PINNED["claude-code"],
                "codex": {
                    "tiers": {**CODEX_TIERS, "deep": "gpt-6-astra"}, "efforts": EFFORTS,
                    "role_models": {"manager": "gpt-6-sol"},
                },
            },
        })
        (saved,) = list(self.backups.glob("*/home/.agents/workflow.toml"))
        self.assertEqual(saved.read_bytes(), was)

    def test_a_file_whose_values_do_not_change_keeps_its_comments(self) -> None:
        self.ok("--yes", "--docs-dir", "sprints")
        text = self.user_file.read_text(encoding="utf-8").replace(
            'docs_dir = "sprints"', 'docs_dir = "sprints"  # the planning repository'
        )
        self.write(self.user_file, text + "\n# a note at the end\n")
        before = self.tree()
        out = self.ok("--yes", "--docs-dir", "sprints")
        self.assertIn("nothing to write", out)
        self.assertEqual(self.tree(), before)

    def test_a_file_with_a_fault_is_not_rewritten(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "sometimes"\ncolour = "red"\n')
        err = self.refused("--yes")
        self.assertIn(f'error: {self.user_file}: process.questions: "sometimes" is not allowed', err)
        self.assertIn(f"error: {self.user_file}: process.colour: unknown key", err)
        self.assertIn("error: init changes nothing while a settings file has a fault; correct the file first\n", err)
        self.write(self.user_file, "schema_version = 2\n")
        self.assertIn("is newer than this tool reads", self.refused("--yes"))
        self.write(self.user_file, "not toml [")
        self.assertIn("is not valid TOML", self.refused("--yes"))

    HAND_WRITTEN = "# my own notes, kept by hand\n[process]\n# where the docs are\ndocs_dir = \"sprints\"\n"

    def test_yes_alone_does_not_rewrite_a_file_written_by_hand(self) -> None:
        # Review finding S17: --yes rewrote it, and its comments were gone.
        self.write(self.user_file, self.HAND_WRITTEN)
        err = self.refused("--yes", "--memory-dir", "notes")
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        for words in (str(self.user_file), "written or edited by hand", "comments and layout are not",
                      "Give --rewrite-settings with --yes", str(self.home / ".agents" / "workflow-setup" / "backups"),
                      "Nothing was written"):
            self.assertIn(words, err)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), self.HAND_WRITTEN)
        self.assertFalse((self.home / ".agents" / "workflow-setup").exists())

    def test_with_the_option_it_is_rewritten_after_a_backup(self) -> None:
        self.write(self.user_file, self.HAND_WRITTEN)
        out = self.ok("--yes", "--rewrite-settings", "--memory-dir", "notes")
        self.assertIn(f"written: {self.user_file}", out)
        self.assertNotIn("# my own notes", self.user_file.read_text(encoding="utf-8"))
        self.assertEqual(self.data()["process"], {"docs_dir": "sprints"})
        backups = list((self.home / ".agents" / "workflow-setup" / "backups").rglob("workflow.toml"))
        self.assertEqual([file.read_text(encoding="utf-8") for file in backups], [self.HAND_WRITTEN])

    def test_a_file_init_wrote_needs_no_more_than_yes_until_it_is_edited(self) -> None:
        self.ok("--yes", "--memory-dir", "notes")
        self.ok("--yes", "--memory-dir", "memory")             # as init left it
        with open(self.user_file, "ab") as handle:
            handle.write(b"\n# a note of mine\n")
        before = self.user_file.read_bytes()
        err = self.refused("--yes", "--memory-dir", "notes")   # edited since
        self.assertIn("--rewrite-settings", err)
        self.assertEqual(self.user_file.read_bytes(), before)
        self.ok("--yes", "--rewrite-settings", "--memory-dir", "notes")
        self.assertEqual(self.data()["memory"], {"dir": "notes"})

    def test_a_hand_written_file_that_the_answers_do_not_change_is_left_alone(self) -> None:
        self.ok("--yes")
        text = self.user_file.read_text(encoding="utf-8") + "\n# a note of mine\n"
        self.write(self.user_file, text)
        out = self.ok("--yes")      # nothing to rewrite, so nothing to confirm
        self.assertIn("nothing to write", out)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), text)

    def test_the_dry_run_and_a_missing_confirmation_name_the_option(self) -> None:
        self.write(self.user_file, self.HAND_WRITTEN)
        out = self.ok("--yes", "--dry-run", "--memory-dir", "notes")
        self.assertIn("was written or edited by hand; without a terminal the run itself needs --yes --rewrite-settings", out)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), self.HAND_WRITTEN)

    @unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
    def test_a_linked_settings_file_is_refused_unless_told(self) -> None:
        real = self.write(self.home / "dotfiles" / "workflow.toml", "")   # in the home, where a run may write
        (self.home / ".agents").mkdir()
        os.symlink(real, self.user_file)
        err = self.refused("--yes", "--rewrite-settings")
        self.assertIn("--follow-config-symlinks", err)
        self.ok("--yes", "--rewrite-settings", "--follow-config-symlinks")
        self.assertTrue(os.path.islink(self.user_file))
        self.assertEqual(self.data(real), {"schema_version": 1, "providers": PINNED})

    @unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
    def test_a_settings_file_linked_out_of_the_home_is_refused_whatever_is_told(self) -> None:
        real = self.write(self.root / "elsewhere" / "workflow.toml", "# another home's\n")
        (self.home / ".agents").mkdir()
        os.symlink(real, self.user_file)
        err = self.refused("--yes", "--rewrite-settings")
        self.assertIn("--follow-config-symlinks", err)
        for more in ((), ("--dry-run",)):
            err = self.refused("--yes", "--rewrite-settings", "--follow-config-symlinks", *more)
            self.assertIn(f"{real}: its real place, {real}, is outside the directories this run may write to", err)
            self.assertEqual(real.read_bytes(), b"# another home's\n")
            self.assertEqual(os.listdir(real.parent), ["workflow.toml"])
            self.assertEqual(os.listdir(self.home / ".agents"), ["workflow.toml"])   # no state was made for it
        self.assertTrue(os.path.islink(self.user_file))


class ProjectTests(InitCase):
    def test_the_project_file_and_the_ignore_entry(self) -> None:
        out = self.ok("--yes", "--docs-dir", "../planning/docs", "--manager-default", project=True)
        self.assertEqual(self.data(self.project_file), {
            "schema_version": 1,
            "process": {"docs_dir": "../planning/docs"},
            "roles": {"manager_default": True},
        })
        self.assertFalse(self.user_file.exists())
        ignore = (self.project / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("\n.agents/workflow.local.toml\n", ignore)
        self.assertIn("workflow-setup:start", ignore)
        self.assertIn("create file project:.agents/workflow.toml", out)
        self.assertIn("project:.gitignore", out)
        text = self.project_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Workflow settings: the project layer (.agents/workflow.toml in the project).\n"))
        self.assertIn("# Only what this project sets differently is here", text)
        code, shown, _ = self.show("process.docs_dir", "roles.manager_default")
        self.assertEqual(code, 0)
        self.assertEqual(
            shown, 'process.docs_dir = "../planning/docs"  (project)\nroles.manager_default = true  (project)\n'
        )

    def test_a_project_file_holds_differences_from_the_users_file(self) -> None:
        self.ok("--yes", "--tier", "codex:deep=gpt-6-astra", "--docs-dir", "sprints")
        self.ok("--yes", "--tier", "codex:fast=gpt-6-sol", "--tier", "codex:deep=gpt-6-astra",
                "--docs-dir", "sprints", "--memory-dir", "memory", project=True)
        self.assertEqual(self.data(self.project_file), {
            "schema_version": 1,
            "memory": {"dir": "memory"},
            "providers": {"codex": {"tiers": {"fast": "gpt-6-sol"}}},
        })
        entries = settings.resolve(self.locations())
        self.assertEqual(entries["providers.codex.tiers.fast"].layer, "project")
        self.assertEqual(entries["providers.codex.tiers.deep"].layer, "user")
        self.assertEqual(entries["process.docs_dir"].layer, "user")

    def test_a_second_project_run_writes_nothing(self) -> None:
        self.ok("--yes", "--high-stakes", project=True)
        before = self.tree()
        out = self.ok("--yes", "--high-stakes", project=True)
        self.assertIn(f"nothing to write: {self.project_file} already holds these settings\n", out)
        self.assertEqual(self.tree(), before)

    def test_an_existing_ignore_file_keeps_its_lines(self) -> None:
        self.write(self.project / ".gitignore", "node_modules/\n*.log\n")
        self.ok("--yes", project=True)
        ignore = (self.project / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(ignore.startswith("node_modules/\n*.log\n"))
        self.assertIn(".agents/workflow.local.toml\n", ignore)

    def test_a_project_dry_run_writes_nothing(self) -> None:
        before = self.tree()
        out = self.ok("--yes", "--dry-run", project=True)
        self.assertIn("dry run: nothing was written", out)
        self.assertEqual(self.tree(), before)


class InstalledTests(InitCase):
    CLAUDE = False

    def test_a_provider_that_is_not_installed_is_left_out(self) -> None:
        out = self.ok("--yes")
        self.assertIn("claude-code: not installed (the program `claude` is not on PATH and ", out)
        self.assertEqual(self.data(), {"schema_version": 1, "providers": {"codex": PINNED["codex"]}})
        err = self.refused("--yes", "--tier", "claude-code:deep=opus")
        self.assertIn("claude-code is not a provider this run sets up; installed here, with a dictionary: codex", err)

    def test_with_no_provider_the_other_settings_are_still_written(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(self.root / "nowhere")}):
            out = self.ok("--yes", "--docs-dir", "sprints")
        self.assertIn("no provider is installed here: no provider section is written\n", out)
        self.assertEqual(self.data(), {"schema_version": 1, "process": {"docs_dir": "sprints"}})

    def test_the_users_environment_reaches_the_program(self) -> None:
        with mock.patch.dict(os.environ, {provider_stub.MARK: "mine"}):
            self.ok("--yes", "--dry-run")
        self.assertEqual(self.stub.marks(), ["mine"])


class ReversalTests(InitCase):
    def undo(self, project: bool = False) -> None:
        roots = Roots(self.home, self.project if project else None, self.clone)
        if project:
            fileops.plan_reversal(roots, project=True).run(dry_run=False)
            self.assertTrue(fileops.remove_state(roots, project=True))
        fileops.plan_reversal(roots).run(dry_run=False)
        self.assertTrue(fileops.remove_state(roots))

    def test_a_first_init_is_taken_back_byte_for_byte(self) -> None:
        before = self.tree()
        self.ok("--yes", "--docs-dir", "sprints")
        self.assertNotEqual(self.tree(), before)
        self.undo()
        self.assertEqual(self.tree(), before)

    def test_several_inits_are_taken_back_to_the_start(self) -> None:
        before = self.tree()
        self.ok("--yes")
        self.ok("--yes", "--docs-dir", "sprints", "--tier", "codex:deep=gpt-6-astra")
        self.ok("--yes", "--docs-dir", "plans")
        self.undo()
        self.assertEqual(self.tree(), before)

    def test_a_users_own_file_comes_back_as_it_was(self) -> None:
        self.write(self.user_file, "# mine\r\n[process]\r\ndocs_dir = 'sprints'\r\n")
        before = self.tree()
        self.ok("--yes", "--rewrite-settings", "--memory-dir", "notes")
        self.ok("--yes", "--memory-dir", "memory")   # init's own file by now: --yes is enough
        self.undo()
        self.assertEqual(self.tree(), before)

    def test_a_project_init_is_taken_back_byte_for_byte(self) -> None:
        self.write(self.project / ".gitignore", "node_modules/\n")
        self.write(self.project / "README.md", "# A project\n")
        before = self.tree()
        self.ok("--yes", "--manager-default", project=True)
        self.ok("--yes")
        self.undo(project=True)
        self.assertEqual(self.tree(), before)


class EmitterHeaderTests(unittest.TestCase):
    DATA = {"schema_version": 1, "process": {"docs_dir": 'a "quoted" \\ path'}, "providers": {"x": {"tiers": {"deep": "m"}}}}

    def test_a_header_changes_nothing_that_is_read_back(self) -> None:
        for header in ([], ["one line"], ["", "two", "", "  indented # with a hash", "tab\there", "= not data", "[nor.this]"]):
            with self.subTest(header=header):
                text = tomlio.dumps(self.DATA, header=header)
                self.assertEqual(tomllib.loads(text), self.DATA)
        self.assertEqual(tomlio.dumps(self.DATA, header=[]), tomlio.dumps(self.DATA))

    def test_the_header_is_comment_lines_before_the_data(self) -> None:
        text = tomlio.dumps({"a": 1}, header=["What this is.", "", "How to change it. "])
        self.assertEqual(text, "# What this is.\n#\n# How to change it.\n\na = 1\n")
        self.assertEqual(tomlio.dumps({}, header=["only"]), "# only\n")
        self.assertEqual(tomllib.loads(tomlio.dumps({}, header=["only"])), {})

    def test_a_line_that_could_end_the_comment_is_refused(self) -> None:
        for line in ("two\nlines = 1", "carriage\rreturn", "nul\x00", "escape\x1b", "delete\x7f", "form\ffeed"):
            with self.subTest(line=line):
                with self.assertRaises(tomlio.SetupError) as caught:
                    tomlio.dumps({"a": 1}, header=[line])
                self.assertIn("a comment line: holds the control character", str(caught.exception))
        with self.assertRaises(tomlio.SetupError):
            tomlio.dumps({"a": 1}, header=["lone \ud800 surrogate"])
        with self.assertRaises(tomlio.SetupError):
            tomlio.dumps({"a": 1}, header=[7])


class LayerTests(support.ScratchCase):
    def test_resolve_can_leave_layers_out(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "u"\n')
        self.write(self.project_file, '[process]\ndocs_dir = "p"\nrecommend = false\n')
        where = self.locations()
        self.assertEqual(settings.resolve(where, ("process",))["process.docs_dir"].value, "p")
        below = settings.resolve(where, ("process",), layers=("shipped", "user"))
        self.assertEqual((below["process.docs_dir"].value, below["process.docs_dir"].layer), ("u", "user"))
        self.assertTrue(below["process.recommend"].value)
        shipped = settings.resolve(where, ("process",), layers=("shipped",))
        self.assertEqual(shipped["process.docs_dir"].layer, "shipped")

    def test_a_layer_left_out_is_not_checked(self) -> None:
        self.write(self.project_file, '[process]\ncolour = "red"\n')
        where = self.locations()
        with self.assertRaises(settings.SetupError):
            settings.resolve(where, ("process",))
        self.assertEqual(settings.resolve(where, ("process",), layers=("shipped", "user"))["process.docs_dir"].value, "docs")


if __name__ == "__main__":
    unittest.main()
