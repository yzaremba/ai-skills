"""Tests for ``doctor``: each check, clean and with each kind of finding.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

The homes are scratch directories built by running ``render``, then
disturbed. No real provider is started (R6.8): ``codex`` and ``claude`` are
``provider_stub.StubProgram``, and the collaboration skill's doctor is a
stub script in the fixture clone, found through a link in a scratch skills
directory as the real one is.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import provider_stub
import support
from fileops_support import POSIX
from provider_stub import BUNDLED, LIVE, VERSION
from test_entry import DEFAULT_ON, OVERRIDE, EntryCase
from test_fileops import Crash
from wfsetup import doctor, entry, fileops, fsio, homes, render
from wfsetup.locations import Locations
from wfsetup.manifest import Manifest

SECRET = "sk-doctor-must-never-print-this-0123456789"

COLLAB_STUB = r'''import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "answer.json"), encoding="utf-8") as handle:
    answer = json.load(handle)
time.sleep(answer["sleep"])
text = answer["stdout"]
if text is None:
    text = json.dumps({"ok": False, "checks": [
        {"name": "argv", "ok": False, "severity": "warning", "detail": " ".join(sys.argv[1:])},
    ]})
sys.stdout.write(text)
sys.exit(answer["code"])
'''


def snapshot(root: Path) -> dict[str, tuple]:
    """Every path below ``root``: a link with its text (not entered), a
    directory, or a file with its bytes and permission bits."""
    found: dict[str, tuple] = {}
    for directory, inner, files in os.walk(root):
        keep = []
        for name in [*inner, *files]:
            path = Path(directory) / name
            seen = fsio.look(path)
            relative = path.relative_to(root).as_posix()
            if seen.kind == fsio.LINK:
                found[relative] = ("link", os.path.normcase(seen.target or ""))
            elif seen.kind == fsio.DIRECTORY:
                found[relative] = ("directory",)
                keep.append(name)
            else:
                found[relative] = ("file", path.read_bytes(), seen.mode)
        inner[:] = [name for name in inner if name in keep]
    return found


class DoctorCase(EntryCase):
    """The fixture clone of ``test_entry`` (two loaded roles, one of them
    the starting role), both providers installed by their homes, and an
    empty PATH: no program is found unless a test gives a stub."""

    def setUp(self) -> None:
        super().setUp()
        self.stubs = self.root / "stubs"

    # --- Running -------------------------------------------------------------

    def run_doctor(self, *argv: str, host: homes.Host | None = None) -> tuple[int, str, str]:
        host = host or self.host
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            return support.run("doctor", *argv, "--home", str(self.home))

    def doctor(self, *argv: str, host: homes.Host | None = None) -> tuple[int, dict]:
        code, out, err = self.run_doctor("--json", *argv, host=host)
        self.assertEqual(err, "", out)
        report = json.loads(out)
        self.assertEqual(report["exit_code"], code)
        return code, report

    def only(self, name: str, *argv: str, host: homes.Host | None = None) -> tuple[int, list[dict]]:
        code, report = self.doctor("--only", name, *argv, host=host)
        self.assertEqual([check["name"] for check in report["checks"]], [name])
        return code, report["checks"][0]["findings"]

    def details(self, findings: list[dict], severity: str) -> list[str]:
        return [found["detail"] for found in findings if found["severity"] == severity]

    def assertFinding(self, findings: list[dict], severity: str, *words: str) -> str:
        for detail in self.details(findings, severity):
            if all(word in detail for word in words):
                return detail
        self.fail(f"no {severity} finding with {words} in {json.dumps(findings, indent=1)}")

    def assertQuiet(self, findings: list[dict]) -> None:
        loud = [found for found in findings if found["severity"] in (doctor.ERROR, doctor.WARNING)]
        self.assertEqual(loud, [])

    # --- Building ------------------------------------------------------------

    def rendered(self, project: bool = False) -> None:
        if project:
            self.write(self.project_file, DEFAULT_ON + OVERRIDE)
            self.with_project()
        else:
            self.ok()

    def link(self, link: Path, target: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        fsio.make_link(str(target), link, directory=True)

    def stub(self, name: str) -> provider_stub.StubProgram:
        return provider_stub.StubProgram(self.stubs / name, name)

    def stub_host(self, *stubs: provider_stub.StubProgram) -> homes.Host:
        search = os.pathsep.join(str(one.bin) for one in stubs)
        return homes.Host(self.host.side, {**os.environ, "PATH": search}, ())

    def collab(self, stdout: str | None = "", code: int = 0, sleep: float = 0, providers=("claude", "codex"),
               clone: Path | None = None) -> Path:
        """The collaboration skill's doctor as a stub in ``clone``, linked
        from the skills place of each of ``providers``."""
        skill = (clone or self.clone) / "multiagent-collab"
        script = skill / "scripts" / "multiagent_collab.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(COLLAB_STUB, encoding="utf-8", newline="\n")
        (script.parent / "answer.json").write_text(
            json.dumps({"stdout": stdout, "code": code, "sleep": sleep}), encoding="utf-8"
        )
        places = {"claude": self.claude_skills, "codex": self.codex_skills}
        for provider in providers:
            if fsio.look(places[provider] / "multiagent-collab").kind == fsio.ABSENT:
                self.link(places[provider] / "multiagent-collab", skill)
        return script

    def collab_report(self, *checks: tuple[str, bool, str, str]) -> str:
        listed = [{"name": name, "ok": ok, "severity": severity, "detail": detail}
                  for name, ok, severity, detail in checks]
        failed = [item for item in listed if not item["ok"] and item["severity"] == "error"]
        return json.dumps({"ok": not failed, "checks": listed})


class CleanCase(DoctorCase):
    def test_a_rendered_home_has_no_error_and_no_warning(self) -> None:
        self.rendered()
        code, report = self.doctor()
        self.assertEqual(code, 0)
        self.assertEqual((report["counts"]["error"], report["counts"]["warning"]), (0, 0), report)
        self.assertEqual([check["name"] for check in report["checks"]], doctor.names())
        self.assertEqual(report["not_run"], [])

    def test_a_rendered_project_has_no_error_and_no_warning(self) -> None:
        self.rendered(project=True)
        code, report = self.doctor(*self.project_arg)
        self.assertEqual(code, 0)
        self.assertEqual((report["counts"]["error"], report["counts"]["warning"]), (0, 0), report)
        self.assertEqual(report["project"], str(self.project))

    def test_a_home_never_rendered_is_info_and_not_an_error(self) -> None:
        code, report = self.doctor()
        self.assertEqual(code, 0)
        self.assertEqual((report["counts"]["error"], report["counts"]["warning"]), (0, 0), report)
        by_name = {check["name"]: check["findings"] for check in report["checks"]}
        self.assertFinding(by_name["missing"], doctor.INFO, "not rendered yet")
        for name in ("drift", "hand-edits", "links"):
            self.assertFinding(by_name[name], doctor.INFO, "no run of setup has written")


class OutputCase(DoctorCase):
    def test_the_text_holds_what_the_json_holds(self) -> None:
        self.rendered()
        (self.claude_agents / "worker.md").write_bytes(b"mine\n")
        os.remove(self.codex_agents / "quick.toml")
        code, report = self.doctor()
        text_code, out, err = self.run_doctor()
        self.assertEqual((code, text_code, err), (1, 1, ""))
        lines = out.splitlines()
        self.assertEqual(lines[-1], f"summary: {report['summary']}")
        # The file that is gone (`missing`), and the edited one, which no longer
        # has the frontmatter an agent file needs (`discovery`).
        self.assertIn("2 errors", report["summary"])
        shown = 0
        for check in report["checks"]:
            self.assertIn(f"{check['name']}: {check['severity']}", lines)
            for found in check["findings"]:
                self.assertIn(f"  {found['severity']}: {found['detail']}", lines)
                shown += 1
        self.assertEqual(sum(1 for line in lines if line.startswith("  ")), shown)
        self.assertEqual(sum(report["counts"].values()), shown)

    def test_only_and_skip_choose_the_checks(self) -> None:
        code, report = self.doctor("--only", "clone", "--only", "sources")
        self.assertEqual([check["name"] for check in report["checks"]], ["sources", "clone"])
        self.assertNotIn("clone", report["not_run"])
        code, report = self.doctor("--skip", "sources", "--skip", "profiles")
        names = [check["name"] for check in report["checks"]]
        self.assertNotIn("sources", names)
        self.assertNotIn("profiles", names)
        self.assertEqual(report["not_run"], ["sources", "profiles"])
        _, out, _ = self.run_doctor("--skip", "sources")
        self.assertIn("not run: sources", out.splitlines())

    def test_the_switches_leave_their_checks_out(self) -> None:
        _, report = self.doctor("--no-model-list", "--no-versions", "--no-collab")
        self.assertEqual(report["not_run"], ["models", "versions", "collaboration-skill"])
        _, report = self.doctor("--only", "versions", "--only", "clone", "--no-versions")
        self.assertEqual([check["name"] for check in report["checks"]], ["clone"])

    def test_a_name_that_is_no_check_is_the_commands_own_failure(self) -> None:
        for option in ("--only", "--skip"):
            code, out, err = self.run_doctor(option, "nothing")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("error: nothing: not a check; the checks are: sources, drift", err)

    def test_a_check_that_raises_is_reported_and_the_others_run(self) -> None:
        def boom(context):
            raise RuntimeError("the check\nitself broke")

        def refused(context):
            raise doctor.SetupError("first line", "second line")

        checks = (doctor.Check("boom", boom, "fine"), doctor.Check("refused", refused, "fine"), *doctor.CHECKS)
        with mock.patch.object(doctor, "CHECKS", checks):
            code, report = self.doctor()
            text_code, out, err = self.run_doctor()
        self.assertEqual((code, text_code, err), (1, 1, ""))
        self.assertNotIn("Traceback", out)
        by_name = {check["name"]: check["findings"] for check in report["checks"]}
        self.assertEqual(self.details(by_name["boom"], doctor.ERROR),
                         ["the check boom failed: RuntimeError: the check itself broke"])
        self.assertEqual(self.details(by_name["refused"], doctor.ERROR), [
            "the check refused could not be made: first line", "the check refused could not be made: second line",
        ])
        self.assertEqual(list(by_name), ["boom", "refused", *doctor.names()])
        self.assertEqual(report["counts"]["error"], 3)

    def test_a_check_added_to_the_registry_gets_its_option_and_runs_on_request(self) -> None:
        def configure(parser):
            parser.add_argument("--prove", action="store_true")

        extra = doctor.Check("extra", lambda context: [doctor.warning("looked")], "fine", default=False,
                             switch="prove", configure=configure)
        with mock.patch.object(doctor, "CHECKS", (*doctor.CHECKS, extra)):
            _, report = self.doctor()
            self.assertEqual(report["not_run"], ["extra"])
            _, report = self.doctor("--prove")
            self.assertEqual(report["checks"][-1]["findings"][0]["detail"], "looked")
            _, findings = self.only("extra")
            self.assertEqual(self.details(findings, doctor.WARNING), ["looked"])

    def test_an_unreadable_record_is_an_error_of_each_check_that_needs_it(self) -> None:
        self.rendered()
        self.manifest_file.write_bytes(b"{ not json")
        code, report = self.doctor()
        self.assertEqual(code, 1)
        by_name = {check["name"]: check["findings"] for check in report["checks"]}
        self.assertFinding(by_name["links"], doctor.ERROR, "the check links could not be made", "is not a setup record")
        self.assertQuiet(by_name["sources"])
        self.assertEqual(self.manifest_file.read_bytes(), b"{ not json")


class SourcesCase(DoctorCase):
    def test_a_source_fault_is_an_error(self) -> None:
        self.rendered()
        (self.clone / "alpha" / "SKILL.md").write_bytes(b"no frontmatter\n")
        code, findings = self.only("sources")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "alpha/SKILL.md")
        # The checks that need render's planning say why they were not made.
        _, findings = self.only("drift")
        self.assertFinding(findings, doctor.INFO, "the clone's sources have problems")

    def test_role_sizes_are_info(self) -> None:
        code, findings = self.only("sources")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.OK, "the sources have no problem")
        self.assertFinding(findings, doctor.INFO, "role texts", "lead ", "worker ")


class DriftCase(DoctorCase):
    def drifted(self, *argv: str) -> list[str]:
        code, findings = self.only("drift", *argv)
        self.assertEqual(code, 0)
        self.assertEqual(self.details(findings, doctor.ERROR), [])
        return sorted(found["subject"] for found in findings if found["severity"] == doctor.WARNING)

    def test_a_clean_home_has_none(self) -> None:
        self.rendered()
        self.assertEqual(self.drifted(), [])

    def test_a_changed_role_file(self) -> None:
        self.rendered()
        (self.clone / "roles" / "quick" / "ROLE.md").write_bytes(b"# Quick\n\nChanged.\n")
        self.assertEqual(self.drifted(), [
            "home:.agents/skills/quick/SKILL.md", "home:.claude/agents/quick.md",
            "home:.claude/skills/quick/SKILL.md", "home:.codex/agents/quick.toml",
        ])
        code, findings = self.only("drift")
        self.assertFinding(findings, doctor.WARNING, "home:.claude/agents/quick.md", "run render")
        self.ok()
        self.assertEqual(self.drifted(), [])

    def test_a_changed_include(self) -> None:
        self.rendered()
        (self.clone / "roles" / "_shared" / "gates.md").write_bytes(b"## Gates\n\nHold every gate.\n")
        found = self.drifted()
        self.assertIn("home:.claude/agents/lead.md", found)
        self.assertIn("home:.codex/lead.config.toml", found)
        self.assertIn("home:.codex/agents/reviewer.toml", found)
        self.assertNotIn("home:.claude/agents/worker.md", found)

    def test_a_changed_binding_row(self) -> None:
        self.rendered()
        table = self.clone / "roles" / "bindings.toml"
        table.write_bytes(table.read_bytes().replace(b"writes nothing", b"writes nothing at all"))
        found = self.drifted()
        self.assertIn("home:.claude/agents/lead.md", found)
        self.assertNotIn("home:.claude/agents/quick.md", found)

    def test_a_changed_setting(self) -> None:
        self.rendered()
        self.write(self.user_file, '[roles.quick]\neffort = "high"\n')
        # On Claude Code the role's model takes no effort setting, so its
        # files are made from the same inputs as before.
        self.assertEqual(self.drifted(), ["home:.agents/skills/quick/SKILL.md", "home:.codex/agents/quick.toml"])
        self.write(self.user_file, '[roles.quick]\ntier = "deep"\n')
        self.assertEqual(self.drifted(), [
            "home:.agents/skills/quick/SKILL.md", "home:.claude/agents/quick.md",
            "home:.claude/skills/quick/SKILL.md", "home:.codex/agents/quick.toml",
        ])

    def test_a_role_that_left_the_clone(self) -> None:
        self.rendered()
        shutil.rmtree(self.clone / "roles" / "runner")
        found = self.drifted()
        self.assertEqual(found, ["home:.claude/agents/runner.md", "home:.codex/agents/runner.toml"])

    def test_a_project_definition_its_block_and_its_key(self) -> None:
        self.rendered(project=True)
        self.assertEqual(self.drifted(*self.project_arg), [])
        (self.clone / "roles" / "worker" / "ROLE.md").write_bytes(b"# Worker\n\nChanged.\n")
        found = self.drifted(*self.project_arg)
        self.assertIn("project:.claude/agents/worker.md", found)
        self.assertIn("project:.codex/agents/worker.toml", found)
        self.assertNotIn("project:.codex/config.toml: block starting-role", found)
        # The starting role's text is the block's.
        (self.clone / "roles" / "lead" / "ROLE.md").write_bytes(b"# Lead\n\nChanged.\n")
        self.assertIn("project:.codex/config.toml: block starting-role", self.drifted(*self.project_arg))
        # Another starting role is another value of the key.
        self.source(self.clone, "lead", load="true", start="false", dispatch="false")
        self.source(self.clone, "quick", tier="fast", load="true", start="true")
        found = self.drifted(*self.project_arg)
        self.assertIn("project:.claude/settings.json: key agent", found)
        self.assertIn("project:.codex/config.toml: block starting-role", found)

    def test_a_default_turned_off_is_what_render_would_remove(self) -> None:
        self.rendered(project=True)
        self.write(self.project_file, OVERRIDE)
        found = self.drifted(*self.project_arg)
        self.assertIn("project:.claude/settings.json: key agent", found)
        self.assertIn("project:.codex/config.toml: block starting-role", found)


class HandEditCase(DoctorCase):
    def test_an_edited_generated_file(self) -> None:
        self.rendered()
        file = self.claude_agents / "worker.md"
        file.write_bytes(file.read_bytes() + b"\nMy own line.\n")
        code, findings = self.only("hand-edits")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 1)
        self.assertFinding(findings, doctor.WARNING, "home:.claude/agents/worker.md", "edited by hand",
                           "render keeps it", "--overwrite-edited")
        # It is no drift: its sources did not change.
        _, findings = self.only("drift")
        self.assertQuiet(findings)

    def test_a_clean_home_has_none(self) -> None:
        self.rendered(project=True)
        code, findings = self.only("hand-edits", *self.project_arg)
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_an_edited_block_and_an_edited_key(self) -> None:
        self.rendered(project=True)
        config = self.project / ".codex" / "config.toml"
        config.write_bytes(config.read_bytes().replace(b'model = "', b'model = "mine-'))
        settings = self.project / ".claude" / "settings.json"
        settings.write_bytes(settings.read_bytes().replace(b'"lead"', b'"quick"'))
        code, findings = self.only("hand-edits", *self.project_arg)
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "project:.codex/config.toml: block starting-role",
                           "changed by hand", "--overwrite-edited")
        self.assertFinding(findings, doctor.WARNING, "project:.claude/settings.json: key agent",
                           'setup set it to "lead"', "--overwrite-edited")
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)

    def test_a_user_settings_file_is_not_a_generated_file(self) -> None:
        self.rendered()
        self.write(self.user_file, '[roles.quick]\neffort = "high"\n')
        _, findings = self.only("hand-edits")
        self.assertQuiet(findings)


class MissingCase(DoctorCase):
    def test_a_removed_generated_file_is_an_error(self) -> None:
        self.rendered()
        os.remove(self.claude_agents / "worker.md")
        shutil.rmtree(self.codex_skills / "lead")
        code, findings = self.only("missing")
        self.assertEqual(code, 1)
        self.assertEqual(sorted(found["subject"] for found in findings if found["severity"] == doctor.ERROR), [
            "home:.agents/skills/lead/SKILL.md", "home:.agents/skills/lead/agents/openai.yaml",
            "home:.claude/agents/worker.md",
        ])
        self.assertFinding(findings, doctor.ERROR, "home:.claude/agents/worker.md", "is gone", "run render")
        self.assertEqual(self.details(findings, doctor.WARNING), [])
        self.ok()
        code, findings = self.only("missing")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_removed_block_and_a_removed_key_are_errors(self) -> None:
        self.rendered(project=True)
        os.remove(self.project / ".codex" / "config.toml")
        (self.project / ".claude" / "settings.json").write_bytes(b"{}\n")
        code, findings = self.only("missing", *self.project_arg)
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "project:.codex/config.toml: block starting-role", "gone")
        self.assertFinding(findings, doctor.ERROR, "project:.claude/settings.json: key agent", "no longer in the file")

    def test_what_the_clone_gained_since_the_last_render_is_a_warning(self) -> None:
        self.rendered()
        shutil.copytree(self.clone / "beta", self.clone / "gamma")
        skill = self.clone / "gamma" / "SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(b"beta", b"gamma"))
        self.source(self.clone, "extra")
        code, findings = self.only("missing")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(found["subject"] for found in findings if found["severity"] == doctor.WARNING), [
            "home:.agents/skills/gamma", "home:.claude/agents/extra.md", "home:.claude/skills/gamma",
            "home:.codex/agents/extra.toml",
        ])
        self.assertFinding(findings, doctor.WARNING, "home:.claude/skills/gamma", "not installed", "run render")

    def test_a_home_rendered_without_roles_is_info(self) -> None:
        self.ok("--no-roles")
        code, findings = self.only("missing")
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "no role definition or entry point is installed", "--no-roles")

    def test_a_project_never_rendered_is_info(self) -> None:
        self.rendered()
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        code, findings = self.only("missing", *self.project_arg)
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "not rendered in the project yet",
                           "project:.claude/settings.json: key agent")

    def test_something_in_the_way_is_an_error(self) -> None:
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        code, findings = self.only("missing")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, str(self.claude_skills / "alpha"), "setup did not make it",
                           "render stops on it")

    def test_a_removed_file_render_would_no_longer_make_is_info(self) -> None:
        self.rendered()
        shutil.rmtree(self.clone / "roles" / "runner")
        os.remove(self.claude_agents / "runner.md")
        code, findings = self.only("missing")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.INFO, "home:.claude/agents/runner.md", "would no longer make it")


class LinksCase(DoctorCase):
    def test_clean_links(self) -> None:
        self.rendered()
        code, findings = self.only("links")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_removed_link(self) -> None:
        self.rendered()
        fsio.remove_link(self.claude_skills / "alpha")
        code, findings = self.only("links")
        self.assertEqual(code, 1)
        self.assertEqual([found["subject"] for found in findings], ["home:.claude/skills/alpha"])
        self.assertFinding(findings, doctor.ERROR, "the link is missing", str(self.clone / "alpha"))
        # Said once: the check `missing` leaves a link to this one.
        _, findings = self.only("missing")
        self.assertQuiet(findings)

    def test_a_link_that_became_a_directory(self) -> None:
        self.rendered()
        fsio.remove_link(self.claude_skills / "alpha")
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        code, findings = self.only("links")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "home:.claude/skills/alpha", "no longer a link: a directory")

    def test_a_retargeted_link(self) -> None:
        self.rendered()
        elsewhere = self.root / "elsewhere" / "alpha"
        elsewhere.mkdir(parents=True)
        fsio.remove_link(self.codex_skills / "alpha")
        self.link(self.codex_skills / "alpha", elsewhere)
        code, findings = self.only("links")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "home:.agents/skills/alpha", "outside the clone",
                           "setup made it a link to", "changed since")
        # Inside the clone, to another place than recorded.
        fsio.remove_link(self.codex_skills / "alpha")
        self.link(self.codex_skills / "alpha", self.clone / "beta")
        _, findings = self.only("links")
        detail = self.assertFinding(findings, doctor.ERROR, "home:.agents/skills/alpha", "the link now leads to")
        self.assertNotIn("outside the clone", detail)

    def test_a_link_whose_target_was_removed(self) -> None:
        self.rendered()
        shutil.rmtree(self.clone / "rules" / "sample")
        code, findings = self.only("links")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "home:.claude/rules/sample", "target does not exist",
                           "moved or removed clone")


class DuplicateCase(DoctorCase):
    def test_none(self) -> None:
        self.rendered()
        code, findings = self.only("duplicate-skills", *self.project_arg)
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_skill_in_the_deprecated_codex_directory(self) -> None:
        self.rendered()
        self.keep(self.codex / "skills" / "alpha" / "SKILL.md")
        self.keep(self.codex / "skills" / "lead" / "SKILL.md")      # a loaded role is a skill too
        self.keep(self.codex / "skills" / "solo" / "SKILL.md")      # not installed for Codex
        self.keep(self.codex / "skills" / "beta" / "notes.md")      # not a skill
        code, findings = self.only("duplicate-skills")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)
        detail = self.assertFinding(findings, doctor.WARNING, "codex: the skill alpha",
                                    str(self.codex_skills / "alpha"), str(self.codex / "skills" / "alpha"))
        self.assertIn("does not merge two skills of one name and lists both", detail)
        self.assertFinding(findings, doctor.WARNING, "codex: the skill lead", str(self.codex / "skills" / "lead"))

    def test_a_skill_in_the_project(self) -> None:
        self.rendered()
        self.keep(self.project / ".claude" / "skills" / "solo" / "SKILL.md")
        self.keep(self.project / ".agents" / "skills" / "beta" / "SKILL.md")
        code, findings = self.only("duplicate-skills")
        self.assertQuiet(findings)  # without --project the project is not looked at
        code, findings = self.only("duplicate-skills", *self.project_arg)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)
        self.assertFinding(findings, doctor.WARNING, "claude-code: the skill solo",
                           str(self.claude_skills / "solo"), str(self.project / ".claude" / "skills" / "solo"))
        self.assertFinding(findings, doctor.WARNING, "codex: the skill beta",
                           str(self.project / ".agents" / "skills" / "beta"))


class OtherCloneCase(DoctorCase):
    def other_clone(self) -> Path:
        other = self.root / "other-clone"
        self.write(other / "tools" / "setup" / "workflow_setup.py", "# the tool\n")
        (other / "roles").mkdir()
        for name in ("gamma", "multiagent-collab"):
            self.write(other / name / "SKILL.md", "---\nname: x\n---\n")
        return other

    def test_none(self) -> None:
        self.rendered()
        self.collab()  # linked from this clone
        code, findings = self.only("other-clones")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_link_into_another_clone_is_a_warning(self) -> None:
        self.rendered()
        other = self.other_clone()
        self.link(self.claude_skills / "gamma", other / "gamma")
        self.link(self.codex / "skills" / "gamma", other / "gamma")
        elsewhere = self.root / "elsewhere" / "delta"
        elsewhere.mkdir(parents=True)
        self.link(self.claude_skills / "delta", elsewhere)   # a link, and to no clone
        code, findings = self.only("other-clones")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)
        detail = self.assertFinding(findings, doctor.WARNING, str(self.claude_skills / "gamma"), str(other))
        self.assertIn("another clone of this repository", detail)
        self.assertFinding(findings, doctor.WARNING, str(self.codex / "skills" / "gamma"))

    def test_the_collaboration_skill_from_another_clone_is_info(self) -> None:
        self.rendered()
        other = self.other_clone()
        self.link(self.claude_skills / "multiagent-collab", other / "multiagent-collab")
        self.link(self.codex_skills / "multiagent-collab", other / "multiagent-collab")
        code, findings = self.only("other-clones")
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertEqual(len(self.details(findings, doctor.INFO)), 2)
        self.assertFinding(findings, doctor.INFO, "the collaboration skill runs from another clone", str(other),
                           "as intended")

    def test_a_clone_inside_a_skills_directory_is_a_warning(self) -> None:
        self.rendered()
        old = self.claude_skills / "ai-skills"
        self.write(old / ".git" / "HEAD", "ref: refs/heads/main\n")
        self.write(old / "alpha" / "SKILL.md", "---\nname: alpha\n---\n")
        self.keep(self.claude_skills / "mine" / "SKILL.md")  # a skill of the user's own
        code, findings = self.only("other-clones")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 1)
        self.assertFinding(findings, doctor.WARNING, str(old), "another clone of this repository", "never removes")


class CloneVerdictCase(DoctorCase):
    def test_a_scratch_home_is_not_asked(self) -> None:
        code, findings = self.only("clone")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.INFO, "not asked: a scratch home")

    def verdict(self, mounts: tuple[str, ...], allow: bool = False) -> list[doctor.Finding]:
        where = Locations(home=self.home, clone=self.clone, real_home=True)
        host = homes.Host(homes.WSL, {"PATH": ""}, mounts)
        context = doctor.Context(where, argparse.Namespace(allow_unshared_clone=allow), host)
        return list(doctor.check_clone(context))

    @unittest.skipUnless(POSIX, "a WSL host is made by hand from POSIX paths")
    def test_a_clone_both_sides_read_is_ok(self) -> None:
        (found,) = self.verdict((str(self.root),))
        self.assertEqual(found.severity, doctor.OK)
        self.assertIn("on a Windows drive, which both sides read", found.detail)

    @unittest.skipUnless(POSIX, "a WSL host is made by hand from POSIX paths")
    def test_a_clone_one_side_reads_is_an_error_and_a_warning_when_allowed(self) -> None:
        (found,) = self.verdict(("/mnt/c",))
        self.assertEqual(found.severity, doctor.ERROR)
        self.assertIn("inside WSL", found.detail)
        self.assertIn("--allow-unshared-clone", found.detail)
        (found,) = self.verdict(("/mnt/c",), allow=True)
        self.assertEqual(found.severity, doctor.WARNING)
        self.assertIn("allowed for this run", found.detail)


class ModelsCase(DoctorCase):
    """The three fixture lists of R8.1, and a list that cannot be read."""

    def setUp(self) -> None:
        super().setUp()
        self.codex_stub = self.stub("codex")
        self.at = self.stub_host(self.codex_stub)

    def models(self, *argv: str) -> tuple[int, list[dict]]:
        return self.only("models", *argv, host=self.at)

    def test_a_list_equal_to_the_dictionary(self) -> None:
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-equal.json"))
        code, findings = self.models()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, "codex: checked against the list of `codex debug models`",
                           "every mapped model is offered")
        self.assertEqual(self.codex_stub.calls(), [["debug", "models"]])

    def test_a_provider_with_no_list(self) -> None:
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-equal.json"))
        _, findings = self.models()
        self.assertFinding(findings, doctor.INFO, "claude-code: no model list",
                           "no command that lists models without starting a session", "the dictionary alone is used")

    def test_a_list_missing_a_mapped_model(self) -> None:
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-missing-mapped.json"))
        code, findings = self.models()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.details(findings, doctor.ERROR)), 1)
        self.assertFinding(findings, doctor.ERROR, 'codex: tiers.frontier = "gpt-6-astra"',
                           "the model is not in the provider's list")

    def test_the_mapping_checked_is_the_one_in_effect(self) -> None:
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-missing-mapped.json"))
        self.write(self.user_file, '[providers.codex.tiers]\nfrontier = "gpt-6-sol"\n')
        code, findings = self.models()
        self.assertEqual((code, self.details(findings, doctor.ERROR)), (0, []))
        self.write(self.user_file, '[providers.codex.role_models]\nworker = "gpt-reserve"\n')
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-equal.json"))
        code, findings = self.models()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, 'codex: role_models.worker = "gpt-reserve"', "hidden entry")

    def test_a_list_with_a_new_model(self) -> None:
        self.codex_stub.answer(LIVE, provider_stub.fixture("model-list-new-model.json"))
        code, findings = self.models()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "in the list and not in the dictionary: gpt-7-nova",
                           "the dictionary may be stale")
        self.assertFinding(findings, doctor.INFO, "hidden entries and not in the dictionary: gpt-internal")

    def test_an_effort_the_list_does_not_give_a_mapped_model(self) -> None:
        listed = json.loads(provider_stub.fixture("model-list-equal.json"))
        for model in listed["models"]:
            if model["slug"] == "gpt-6.1-sol":
                model["supported_reasoning_levels"] = [{"effort": "low"}]
        self.codex_stub.answer(LIVE, json.dumps(listed))
        code, findings = self.models()
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.WARNING, "codex: gpt-6.1-sol: the dictionary has the efforts",
                           "the list has low", "a mapped model")
        self.assertFinding(findings, doctor.ERROR, "the definition worker resolves to the model gpt-6.1-sol",
                           "effort medium")

    def test_a_list_that_cannot_be_read_is_a_warning_with_the_reason(self) -> None:
        self.codex_stub.answer(LIVE, "", code=1, stderr="error: not logged in\n")
        self.codex_stub.answer(BUNDLED, "this is not a list")
        code, findings = self.models()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 1)
        # The first line of standard error follows the code. Started from a
        # network path, the Windows command interpreter puts a line of its
        # own before the program's, so the program's is looked for on POSIX.
        self.assertFinding(findings, doctor.WARNING, "codex: no model list", "exited with code 1: ",
                           "error: not logged in" if POSIX else "",
                           "printed what is not a model list", "the dictionary alone is used")

    def test_the_shipped_list_is_said_when_the_live_one_fails(self) -> None:
        self.codex_stub.answer(LIVE, "", code=1)
        self.codex_stub.answer(BUNDLED, provider_stub.fixture("model-list-equal.json"))
        code, findings = self.models()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "the list shipped with the program")

    def test_a_program_that_is_not_on_path_is_info(self) -> None:
        code, findings = self.only("models")
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "codex: the program `codex` is not on PATH")

    def test_no_model_list_starts_nothing(self) -> None:
        _, report = self.doctor("--no-model-list", "--no-versions", host=self.at)
        self.assertEqual(self.codex_stub.calls(), [])
        self.assertIn("models", report["not_run"])


class VersionsCase(DoctorCase):
    def setUp(self) -> None:
        super().setUp()
        self.codex_stub = self.stub("codex")
        self.claude_stub = self.stub("claude")
        self.at = self.stub_host(self.codex_stub, self.claude_stub)

    def versions(self, codex: str = "codex-cli 0.160.0\n", claude: str = "2.1.289 (Claude Code)\n", **how
                 ) -> tuple[int, list[dict]]:
        self.codex_stub.answer(VERSION, codex, **how)
        self.claude_stub.answer(VERSION, claude)
        return self.only("versions", host=self.at)

    def test_the_checked_versions_are_ok(self) -> None:
        code, findings = self.versions()
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK, doctor.OK]))
        self.assertFinding(findings, doctor.OK, "claude-code: version 2.1.289")
        self.assertFinding(findings, doctor.OK, "codex: version 0.160.0")
        self.assertEqual((self.codex_stub.calls(), self.claude_stub.calls()), ([["--version"]], [["--version"]]))

    def test_a_version_between_the_oldest_and_the_checked_is_ok(self) -> None:
        code, findings = self.versions(claude="2.1.281 (Claude Code)\n")
        self.assertQuiet(findings)

    def test_a_newer_version_is_a_warning(self) -> None:
        code, findings = self.versions(codex="codex-cli 0.161.0-alpha.2\n", claude="2.2.0 (Claude Code)\n")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "codex: version 0.161.0 is newer than 0.160.0",
                           "the dictionary may be stale")
        self.assertFinding(findings, doctor.WARNING, "claude-code: version 2.2.0 is newer than 2.1.289")

    def test_an_older_version_is_a_warning_that_says_what_does_not_work(self) -> None:
        code, findings = self.versions(claude="2.1.276 (Claude Code)\n", codex="codex-cli 0.150.0\n")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "claude-code: version 2.1.276 is older than 2.1.281",
                           "do not read a repository's AGENTS.md")
        # The fixture Codex dictionary names no oldest version.
        self.assertFinding(findings, doctor.OK, "codex: version 0.150.0")

    def test_a_version_that_cannot_be_read_is_a_warning(self) -> None:
        code, findings = self.versions(codex="no number here\n")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "codex: the version cannot be read", "printed no version")
        code, findings = self.versions(codex="", code=3, stderr="boom\n")
        self.assertFinding(findings, doctor.WARNING, "codex: the version cannot be read",
                           "exited with code 3: boom" if POSIX else "exited with code 3")
        with mock.patch.object(doctor, "VERSION_TIMEOUT", 0.5):
            code, findings = self.versions(sleep=30)
        self.assertFinding(findings, doctor.WARNING, "codex: the version cannot be read", "did not finish within 0.5")

    def test_a_program_that_is_not_on_path_is_info(self) -> None:
        code, findings = self.only("versions")
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertEqual(len(self.details(findings, doctor.INFO)), 2)


class CodexSettingsCase(DoctorCase):
    def config(self, text: str | bytes) -> Path:
        file = self.codex / "config.toml"
        file.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return file

    def settings(self) -> tuple[int, list[dict]]:
        return self.only("codex-settings")

    def test_no_file_is_every_key_unset(self) -> None:
        code, findings = self.settings()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "config.toml: no such file")
        self.assertFinding(findings, doctor.INFO, "agents.max_concurrent_threads_per_session: unset",
                           "Codex chooses the default", "needs 8 or more")
        self.assertFinding(findings, doctor.INFO, "sandbox_mode: unset")
        self.assertFinding(findings, doctor.INFO, "default_permissions: unset")

    def test_each_key_set(self) -> None:
        self.config('sandbox_mode = "workspace-write"\ndefault_permissions = ":workspace"\n\n'
                    "[agents]\nmax_concurrent_threads_per_session = 12\n")
        code, findings = self.settings()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, "agents.max_concurrent_threads_per_session = 12")
        self.assertFinding(findings, doctor.INFO, 'sandbox_mode = "workspace-write"',
                           "Codex uses the older sandbox settings instead of default_permissions",
                           "setup never changes or removes the key")
        self.assertFinding(findings, doctor.INFO, 'default_permissions = ":workspace"',
                           "not used while sandbox_mode is set")

    def test_a_permission_profile_without_a_sandbox_mode(self) -> None:
        self.config('default_permissions = "mine"\n')
        _, findings = self.settings()
        detail = self.assertFinding(findings, doctor.INFO, 'default_permissions = "mine"')
        self.assertNotIn("not used", detail)

    def test_a_thread_limit_below_eight_is_a_warning(self) -> None:
        self.config("[agents]\nmax_concurrent_threads_per_session = 6\n")
        code, findings = self.settings()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "agents.max_concurrent_threads_per_session = 6: below 8",
                           "three Coders")
        self.config("[agents]\nmax_concurrent_threads_per_session = 8\n")
        self.assertQuiet(self.settings()[1])
        self.config('[agents]\nmax_concurrent_threads_per_session = "many"\n')
        self.assertFinding(self.settings()[1], doctor.WARNING, "not a whole number")

    def test_no_other_keys_value_is_printed(self) -> None:
        self.config(
            f'model = "{SECRET}-model"\nsandbox_mode = "read-only"\napi_key = "{SECRET}"\n\n'
            f'[agents]\nmax_threads = 2\ntoken = "{SECRET}"\n\n'
            f'[mcp_servers.one.env]\nTOKEN = "{SECRET}"\n\n[default_permissions_extra]\nx = "{SECRET}"\n'
        )
        for argv in (("--json",), ()):
            code, out, err = self.run_doctor(*argv)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("read-only", out)
            self.assertNotIn(SECRET, out)
            self.assertNotIn("sk-doctor", out)

    def test_a_value_of_a_named_key_that_is_no_scalar_is_not_printed(self) -> None:
        self.config(f'[sandbox_mode]\ninner = "{SECRET}"\n')
        code, out, err = self.run_doctor("--only", "codex-settings")
        self.assertEqual(code, 0)
        self.assertIn("sandbox_mode = set to a dict, which is not a value this key takes", out)
        self.assertNotIn(SECRET, out)

    def test_a_broken_file_is_a_warning_that_names_only_the_fault(self) -> None:
        self.config(f'api_key = "{SECRET}"\nsandbox_mode = {SECRET}\n')
        for argv in (("--json",), ()):
            code, out, err = self.run_doctor("--only", "codex-settings", *argv)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("is not valid TOML (line 2, column", out)
            self.assertIn("warning", out)
            self.assertNotIn(SECRET, out)
        self.config(b"\xff\xfe not text")
        code, findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, "config.toml", "is not UTF-8 text")

    def test_the_function_gives_the_values_for_a_step_that_extends_the_check(self) -> None:
        self.config('sandbox_mode = "read-only"\n')
        context = doctor.Context(Locations(home=self.home, clone=self.clone), None, self.host)
        found = doctor.codex_settings(context)
        self.assertEqual(found.values[doctor.SANDBOX_KEY], "read-only")
        self.assertIs(found.values[doctor.THREADS_KEY], doctor.UNSET)
        self.assertEqual(set(found.values), set(doctor.CODEX_KEYS))

    def test_codex_not_installed_is_info(self) -> None:
        shutil.rmtree(self.codex)
        code, findings = self.settings()
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.INFO]))
        self.assertFinding(findings, doctor.INFO, "codex: not installed")


class ProfilesCase(DoctorCase):
    def test_a_note_of_the_resolver_is_a_warning(self) -> None:
        self.write(self.user_file, '[roles.nobody]\ntier = "deep"\n\n[providers.nowhere.tiers]\nfast = "a"\n')
        code, findings = self.only("profiles")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)
        self.assertFinding(findings, doctor.WARNING, "roles.nobody: no role definition has the id nobody")
        self.assertFinding(findings, doctor.WARNING, "providers.nowhere: no provider of this name has a dictionary")

    def test_a_profile_that_does_not_resolve_is_an_error(self) -> None:
        self.write(self.user_file, '[providers.codex.efforts]\nmedium = "ultra"\n')
        code, findings = self.only("profiles")
        self.assertEqual(code, 1)
        self.assertTrue(self.details(findings, doctor.ERROR))
        self.assertFinding(findings, doctor.ERROR, "ultra")

    def test_clean(self) -> None:
        code, findings = self.only("profiles")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))


class InterruptedCase(DoctorCase):
    def test_none(self) -> None:
        self.rendered()
        code, findings = self.only("interrupted-run")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_run_stopped_half_way_is_a_warning_with_what_was_made_and_what_was_not(self) -> None:
        self.rendered()
        real = Manifest.save
        saved: set[Path] = set()

        def save(manifest: Manifest) -> None:
            # Saved once, with its pending list; the process is gone before
            # the closing save.
            if manifest.file in saved:
                raise Crash()
            saved.add(manifest.file)
            real(manifest)

        plan = fileops.Plan(self.roots())
        made, undone = self.claude_agents / "made.md", self.claude_agents / "undone.md"
        plan.write_file(made, "one\n", inputs="render:test")
        plan.write_file(undone, "two\n", inputs="render:test")
        with mock.patch.object(Manifest, "save", autospec=True, side_effect=save):
            with self.assertRaises(Crash):
                plan.apply()
        os.remove(undone)  # as if the run had stopped before it
        before = self.manifest_file.read_bytes()
        self.assertIn(b'"pending"', before)

        code, findings = self.only("interrupted-run")
        self.assertEqual(code, 0)
        (detail,) = self.details(findings, doctor.WARNING)
        self.assertIn("1 of its changes were made and are taken as installed: home:.claude/agents/made.md", detail)
        self.assertIn("1 were not made and are dropped: home:.claude/agents/undone.md", detail)
        # The record is as the interrupted run left it: doctor settles it in
        # memory only.
        self.assertEqual(self.manifest_file.read_bytes(), before)


class LoadedSizeCase(DoctorCase):
    def test_the_fixture_roles_are_short(self) -> None:
        code, findings = self.only("loaded-skill-size")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))

    def test_a_loaded_role_over_the_limit_is_a_warning(self) -> None:
        with mock.patch.object(entry, "COMPACTION_TOKENS", 100):
            code, findings = self.only("loaded-skill-size")
        self.assertEqual(code, 0)
        # Claude Code is the provider that cuts; each of its two loaded roles.
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)
        self.assertFinding(findings, doctor.WARNING, "claude-code: the loaded role lead", "first 100 tokens",
                           "likely to be cut")


class CollaborationCase(DoctorCase):
    def test_not_installed_is_info(self) -> None:
        self.rendered()
        code, findings = self.only("collaboration-skill")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.INFO]))
        self.assertFinding(findings, doctor.INFO, "not installed", str(self.claude_skills / "multiagent-collab"))

    def test_every_check_passing_is_ok(self) -> None:
        self.collab(self.collab_report(("packaged_protocol", True, "error", "x"), ("claude_hooks", True, "error", "y")))
        code, findings = self.only("collaboration-skill")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))
        self.assertFinding(findings, doctor.OK, "--agent both", "all 2 checks pass")

    def test_it_is_started_with_this_home_and_its_json_flag(self) -> None:
        self.collab(None)
        code, findings = self.only("collaboration-skill")
        self.assertFinding(findings, doctor.WARNING, f"argv: doctor --agent both --home {self.home} --json")

    def test_installed_for_one_provider_it_is_asked_about_that_one(self) -> None:
        self.collab(None, providers=("codex",))
        _, findings = self.only("collaboration-skill")
        self.assertFinding(findings, doctor.WARNING, "argv: doctor --agent codex --home")

    def test_its_warnings_are_warnings(self) -> None:
        self.collab(self.collab_report(
            ("packaged_protocol", True, "error", "x"),
            ("codex_binding", False, "warning", "session=None pid=None"),
            ("codex_hook_trust", False, "warning", "probe unavailable"),
        ))
        code, findings = self.only("collaboration-skill")
        self.assertEqual(code, 0)
        self.assertEqual(self.details(findings, doctor.WARNING),
                         ["codex_binding: session=None pid=None", "codex_hook_trust: probe unavailable"])
        self.assertFinding(findings, doctor.INFO, "no check failed, 2 of 3 warn")

    def test_its_errors_are_errors(self) -> None:
        self.collab(self.collab_report(
            ("installed_protocol", False, "error", "/somewhere/PROTOCOL.md"),
            ("codex_wake", False, "warning", "mode=None"),
        ), code=1)
        code, findings = self.only("collaboration-skill")
        self.assertEqual(code, 1)
        self.assertEqual(self.details(findings, doctor.ERROR), ["installed_protocol: /somewhere/PROTOCOL.md"])
        self.assertEqual(self.details(findings, doctor.WARNING), ["codex_wake: mode=None"])

    def test_a_doctor_that_cannot_be_read_is_a_warning(self) -> None:
        self.collab("Traceback (most recent call last):\n", code=1)
        code, findings = self.only("collaboration-skill")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "exited with code 1", "not its JSON report",
                           "nothing is known about the skill's state")

    def test_a_doctor_that_does_not_finish_is_a_warning(self) -> None:
        self.collab(self.collab_report(), sleep=30)
        with mock.patch.object(doctor, "COLLAB_TIMEOUT", 0.5):
            code, findings = self.only("collaboration-skill")
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "did not finish within 0.5 seconds")

    def test_no_collab_does_not_start_it(self) -> None:
        self.collab("not json", code=7)
        _, report = self.doctor("--no-collab")
        self.assertIn("collaboration-skill", report["not_run"])


class ReadOnlyCase(DoctorCase):
    def everything(self) -> tuple[homes.Host, provider_stub.StubProgram, provider_stub.StubProgram]:
        """Stubs for every program doctor starts, each with an answer."""
        codex, claude = self.stub("codex"), self.stub("claude")
        codex.answer(LIVE, provider_stub.fixture("model-list-new-model.json"))
        codex.answer(VERSION, "codex-cli 0.161.0\n")
        claude.answer(VERSION, "2.1.289 (Claude Code)\n")
        self.collab(self.collab_report(("codex_binding", False, "warning", "none")))
        return self.stub_host(codex, claude), codex, claude

    def places(self) -> dict[str, dict]:
        return {name: snapshot(path) for name, path in
                (("home", self.home), ("project", self.project), ("clone", self.clone))}

    def test_a_full_run_changes_no_path_link_byte_or_mode(self) -> None:
        self.rendered(project=True)
        self.write(self.codex / "config.toml", 'sandbox_mode = "read-only"\n')
        if POSIX:
            os.chmod(self.codex / "config.toml", 0o600)
        # Something of every kind for the checks to find.
        (self.claude_agents / "worker.md").write_bytes(b"mine\n")
        os.remove(self.codex_agents / "quick.toml")
        fsio.remove_link(self.claude_skills / "beta")
        self.keep(self.codex / "skills" / "alpha" / "SKILL.md")
        (self.clone / "roles" / "quick" / "ROLE.md").write_bytes(b"# Quick\n\nChanged.\n")
        host, codex, claude = self.everything()
        before = self.places()
        for argv in ((), ("--json",)):
            code, out, err = self.run_doctor(*self.project_arg, *argv, host=host)
            self.assertEqual((code, err), (1, ""), out)
            self.assertEqual(self.places(), before)
        self.assertFalse(any("__pycache__" in name for name in before["clone"]))
        # Every check ran, the ones that start a program among them.
        report = json.loads(out)
        self.assertEqual([check["name"] for check in report["checks"]], doctor.names())
        self.assertEqual(report["not_run"], [])
        # The check `discovery` starts its offline commands and no session.
        offline = [["debug", "prompt-input", "workflow setup discovery check"], ["app-server", "--listen", "stdio://"],
                   ["--profile", "lead", "debug", "prompt-input", "workflow setup discovery check"]]
        self.assertEqual(codex.calls(), [["debug", "models"], ["--version"], *offline] * 2)
        self.assertEqual(claude.calls(), [["--version"]] * 2)

    def test_a_home_with_no_state_directory_gets_none(self) -> None:
        host, _, _ = self.everything()
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        before = self.places()
        code, out, err = self.run_doctor(*self.project_arg, host=host)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.places(), before)
        self.assertEqual(fsio.look(self.home / ".agents" / "workflow-setup").kind, fsio.ABSENT)
        self.assertEqual(fsio.look(self.project / ".agents" / "workflow-setup").kind, fsio.ABSENT)

    def test_a_record_with_a_pending_list_is_not_settled_on_disk(self) -> None:
        self.rendered()
        record = json.loads(self.manifest_file.read_bytes())
        record["pending"] = [{"path": "home:.claude/agents/never.md", "after": {"kind": "file", "sha256": "0"},
                              "set": True, "entry": {"kind": "file"}, "backup": None}]
        self.manifest_file.write_bytes(json.dumps(record).encode("utf-8"))
        before = snapshot(self.home)
        code, report = self.doctor()
        self.assertEqual(snapshot(self.home), before)
        by_name = {check["name"]: check["findings"] for check in report["checks"]}
        self.assertFinding(by_name["interrupted-run"], doctor.WARNING, "home:.claude/agents/never.md")


class RepositoryCase(DoctorCase):
    def test_the_command_is_listed_and_its_help_names_every_check(self) -> None:
        code, out, _ = support.run("--help")
        self.assertIn("doctor", out)
        code, out, _ = support.run("doctor", "--help")
        self.assertEqual(code, 0)
        for name in doctor.names():
            self.assertIn(name, out)
        for option in ("--only", "--skip", "--no-model-list", "--no-versions", "--no-collab", "--json",
                       "--allow-unshared-clone", "--project", "--home"):
            self.assertIn(option, out)

    def test_every_check_has_a_name_of_its_own(self) -> None:
        self.assertEqual(len(set(doctor.names())), len(doctor.CHECKS))
        self.assertEqual(render.GENERATED_PREFIX, "render:")


if __name__ == "__main__":
    unittest.main()
