"""The one place every change to the disk passes (``fsio.admit``).

Nothing is written, removed or linked inside the clone, at a credentials
name, or outside the roots of a run, whatever the options: one function
decides it, and no module but ``fsio`` changes the disk at all.

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

import support
from fileops_support import POSIX, SYMLINKS, OpsCase
from fileops_support import snapshot as snapshot_of
from wfsetup import fileops, fsio, lock
from wfsetup.errors import SetupError
from wfsetup.manifest import Roots

PACKAGE = support.SETUP / "wfsetup"

# Functions of ``os`` that change a disk, and the methods of a path that do.
OS_CHANGES = {
    "mkdir", "makedirs", "rmdir", "removedirs", "unlink", "remove", "rename", "renames", "replace", "link",
    "symlink", "chmod", "lchmod", "fchmod", "chown", "lchown", "fchown", "truncate", "ftruncate", "utime", "mkfifo",
    "mknod", "open",
    "write", "pwrite", "writev", "sendfile", "copy_file_range", "chflags", "setxattr", "removexattr",
}
PATH_CHANGES = {
    "write_text", "write_bytes", "mkdir", "rmdir", "unlink", "rename", "touch", "symlink_to", "hardlink_to",
    "link_to", "chmod", "lchmod",
}
# Whole modules whose only use is to change a disk.
MODULES = {"shutil": {"which"}, "tempfile": set()}   # the names a module may still use
WRITING = set("wax+")

# The functions of ``fsio`` that may call a changing function of ``os``:
# each asks ``admit`` first. ``null_output`` opens the null device.
CHOKE = {
    "_mkdir", "_rmdir", "_unlink", "_chmod", "_replace_entry", "_rename_entry", "_hard_link", "_symlink", "_create",
    "null_output",
}


def modules() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts)


def _mode_writes(call: ast.Call) -> bool:
    mode: ast.expr | None = call.args[1] if len(call.args) > 1 else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(WRITING & set(mode.value))
    return True  # not a constant: cannot be shown to read only


def changes(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Every call in ``tree`` that can change a disk: its line, what it
    is, and the function it is in."""
    found: list[tuple[int, str, str]] = []

    def visit(node: ast.AST, inside: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside = node.name
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                owner = function.value.id if isinstance(function.value, ast.Name) else None
                name = function.attr
                if owner == "os" and name in OS_CHANGES:
                    found.append((node.lineno, f"os.{name}", inside))
                elif owner in MODULES and name not in MODULES[owner]:
                    found.append((node.lineno, f"{owner}.{name}", inside))
                elif owner not in ("os", "fsio", "blocks", "re", "signal") and name in PATH_CHANGES:
                    found.append((node.lineno, f".{name}()", inside))
                elif name == "replace" and len(node.args) == 1 and not node.keywords and owner != "dataclasses":
                    found.append((node.lineno, ".replace(target)", inside))   # a path's; a string's takes two
                elif name == "open" and owner not in ("os",) and _mode_writes(node):
                    found.append((node.lineno, ".open(for writing)", inside))
            elif isinstance(function, ast.Name) and function.id == "open" and _mode_writes(node):
                found.append((node.lineno, "open(for writing)", inside))
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    visit(tree, "<module>")
    return found


class SyntaxTreeTests(unittest.TestCase):
    """No module but ``fsio`` changes the disk, and ``fsio`` only through
    the functions that ask ``admit``."""

    def test_no_other_module_calls_a_function_that_changes_the_disk(self) -> None:
        offenders = []
        for path in modules():
            if path.name == "fsio.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, what, inside in changes(tree):
                offenders.append(f"{path.relative_to(PACKAGE)}:{line}: {what} in {inside}")
        self.assertEqual(offenders, [], "a change to the disk outside fsio")

    def test_no_other_module_imports_a_function_that_changes_the_disk_by_name(self) -> None:
        offenders = []
        for path in modules():
            if path.name == "fsio.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module in ("os", "shutil", "tempfile", "pathlib"):
                    for alias in node.names:
                        if node.module == "pathlib" and alias.name in ("Path", "PurePath", "PurePosixPath", "PureWindowsPath"):
                            continue
                        offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}: from {node.module} import {alias.name}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ("shutil", "tempfile") and path.name not in ("homes.py", "modellist.py"):
                            offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}: import {alias.name}")
        self.assertEqual(offenders, [])

    def test_in_fsio_the_disk_is_changed_only_by_the_functions_that_ask_first(self) -> None:
        tree = ast.parse((PACKAGE / "fsio.py").read_text(encoding="utf-8"))
        outside = [
            f"fsio.py:{line}: {what} in {inside}" for line, what, inside in changes(tree)
            if inside not in CHOKE and not (inside in ("_sync_directory",) and what == "os.open")
            and not (inside == "scratch_file" and what.startswith("tempfile."))
        ]
        self.assertEqual(outside, [], "a change to the disk that does not pass admit")
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for name in sorted(CHOKE - {"null_output"}):
            body = functions[name]
            calls = [
                node.func.id for node in ast.walk(body)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            ]
            self.assertIn("admit", calls, f"{name} does not ask admit")
            first_change = min(line for line, _, inside in changes(tree) if inside == name)
            first_admit = min(
                node.lineno for node in ast.walk(body)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "admit"
            )
            self.assertLess(first_admit, first_change, f"{name} changes the disk before it asks")

    def test_the_scripts_beside_the_package_and_the_one_deliberate_exception(self) -> None:
        """Every script in ``tools/setup`` is read as well. The command
        line changes no disk by itself. ``build_v1_hashes.py`` does, on
        purpose and outside ``fsio``: a developer's script that writes one
        committed file of the clone, which ``admit`` would refuse. It is
        the one exception, it is exactly that one write, it says so at its
        top, and nothing of the package reaches it."""
        exception = "build_v1_hashes.py"
        scripts = sorted(support.SETUP.glob("*.py"))
        self.assertEqual([path.name for path in scripts], [exception, support.SCRIPT.name])
        found = {
            path.name: [(what, inside) for _, what, inside in changes(ast.parse(path.read_text(encoding="utf-8")))]
            for path in scripts
        }
        self.assertEqual(found[support.SCRIPT.name], [])
        self.assertEqual(found[exception], [(".write_bytes()", "main")])
        text = (support.SETUP / exception).read_text(encoding="utf-8")
        self.assertIn("Outside the choke point, on purpose", text)
        self.assertIn("OUTPUT.write_bytes(to_bytes(found))", text)
        self.assertNotIn("fsio.", text.split('"""', 2)[2].split("import argparse", 1)[1])
        for path in [*modules(), support.SCRIPT]:
            self.assertNotIn("build_v1_hashes", path.read_text(encoding="utf-8"), path.name)

    def test_the_junction_maker_asks_too(self) -> None:
        tree = ast.parse((PACKAGE / "fsio.py").read_text(encoding="utf-8"))
        maker = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_create_junction")
        first = maker.body[1] if isinstance(maker.body[0], ast.Expr) else maker.body[0]
        names = [node.func.id for node in ast.walk(maker) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn("admit", names)
        self.assertIsNotNone(first)

    def test_the_stop_variable_is_read_in_fsio_alone(self) -> None:
        for path in [*modules(), support.SCRIPT]:
            if path.name == "fsio.py":
                continue
            self.assertNotIn(fsio.STOP_VARIABLE, path.read_text(encoding="utf-8"), path.name)


class AdmitCase(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        self.elsewhere = self.root / "elsewhere"
        self.elsewhere.mkdir()

    def refused(self, path: Path, word: str) -> None:
        with self.assertRaises(SetupError) as caught:
            fsio.admit(path)
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn(word, caught.exception.lines[0])


class AdmitTests(AdmitCase):
    def test_without_bounds_nothing_is_admitted(self) -> None:
        saved, fsio._BASE = fsio._BASE, None
        try:
            self.refused(self.home / "x", "no place to write")
            for change in (
                lambda: fsio.atomic_write(self.home / "x", b"1"),
                lambda: fsio.make_directory(self.home / "d"),
                lambda: fsio.write_new(self.home / "n", b"1"),
                lambda: fsio.remove_file(self.put(self.home / "f", "1")),
                lambda: fsio.make_directories(self.home / "a" / "b"),
            ):
                with self.assertRaises(SetupError):
                    change()
        finally:
            fsio._BASE = saved
        self.assertEqual(sorted(os.listdir(self.home)), ["f"])

    def test_inside_a_root_is_admitted_and_outside_is_not(self) -> None:
        with fsio.confined([self.home]):
            self.assertEqual(fsio.admit(self.home / ".claude" / "new" / "deep.md"), str(self.home / ".claude" / "new" / "deep.md"))
            self.refused(self.elsewhere / "x", "outside the directories")
            self.refused(self.project / "x", "outside the directories")
            self.refused(self.home, "outside the directories")   # the root itself is an entry of its parent

    def test_a_barred_directory_inside_a_root(self) -> None:
        inner = self.home / "work" / "project"
        inner.mkdir(parents=True)
        with fsio.confined([self.home], [inner]):
            fsio.admit(self.home / "work" / "x")
            self.refused(inner / "x", "never writes to")
            self.refused(inner / "a" / "b" / "c", "never writes to")

    def test_the_clone_the_tool_runs_from_is_barred_whatever_the_roots(self) -> None:
        with fsio.confined([Path(self.home.anchor), Path(fsio.RUNNING_CLONE.anchor)]):
            self.refused(fsio.RUNNING_CLONE / "docs" / "x", "inside the clone")
            self.refused(fsio.RUNNING_CLONE / "x", "inside the clone")
            self.refused(support.SETUP / "wfsetup" / "new.py", "inside the clone")
            self.assertIsNone(fsio.admits(self.home / "x"))

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_link_anywhere_in_the_chain_does_not_hide_the_place(self) -> None:
        os.symlink(self.clone, self.home / "to-clone", target_is_directory=True)
        os.symlink(self.elsewhere, self.home / "out", target_is_directory=True)
        (self.clone / "docs").mkdir(exist_ok=True)
        os.symlink(self.home / "to-clone" / "docs", self.home / "twice", target_is_directory=True)
        with fsio.confined([self.home], [self.clone]):
            self.refused(self.home / "to-clone" / "x", "never writes to")
            self.refused(self.home / "to-clone" / "new" / "deeper" / "x", "never writes to")
            self.refused(self.home / "twice" / "x", "never writes to")
            self.refused(self.home / "out" / "x", "outside the directories")
            # The links themselves are entries of the home: removing one is admitted.
            fsio.admit(self.home / "to-clone")
            fsio.admit(self.home / "out")

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_second_path_to_the_clone_is_the_clone(self) -> None:
        alias = self.root / "alias"
        os.symlink(self.clone, alias, target_is_directory=True)
        with fsio.confined([self.root], [alias]):          # barred by its other name
            self.refused(self.clone / "x", "never writes to")
        with fsio.confined([self.root], [self.clone]):
            self.refused(alias / "x", "never writes to")

    def test_the_comparison_is_of_directories_not_of_text(self) -> None:
        # The same directory under a name that differs in letter case, where
        # the file system ignores case; elsewhere a different directory.
        other = Path(str(self.clone).upper()) if str(self.clone) != str(self.clone).upper() else None
        if other is None:
            self.skipTest("the path has no letters")
        with fsio.confined([self.root], [self.clone]):
            if os.path.exists(other) and os.path.samefile(other, self.clone):
                self.refused(other / "x", "never writes to")
            else:
                self.assertIsNone(fsio.admits(self.root / "x"))

    def test_a_path_with_dot_dot_is_refused(self) -> None:
        with fsio.confined([self.home]):
            self.refused(self.home / "a" / ".." / "b", "'..'")
            self.refused(Path(str(self.home) + os.sep + ".." + os.sep + "home" + os.sep + "x"), "'..'")

    def test_credentials_names(self) -> None:
        with fsio.confined([self.home]):
            for name in ("auth.json", ".credentials.json", "AUTH.JSON", ".Credentials.Json", "auth.json.", "auth.json ",
                         "auth.json. . ", ".credentials.json..."):
                with self.subTest(name=name):
                    with self.assertRaises(fsio.CredentialsRefused):
                        fsio.admit(self.home / ".codex" / name)
                    self.assertTrue(fsio.is_credentials(self.home / name))
            fsio.admit(self.home / ".codex" / "auth.json.bak")
            fsio.admit(self.home / ".codex" / "my-auth.json")
        self.assertEqual(fsio.is_credentials("auth.json:stream"), True)

    def test_every_changing_function_refuses_a_credentials_name(self) -> None:
        secret = self.home / ".codex" / "auth.json"
        secret.parent.mkdir(parents=True)
        secret.write_bytes(b"SECRET")
        spelled = self.home / ".codex" / "auth.json."
        for change in (
            lambda: fsio.atomic_write(secret, b"x"), lambda: fsio.write_new(secret, b"x"),
            lambda: fsio.remove_file(secret), lambda: fsio.atomic_write(spelled, b"x"),
            lambda: fsio.make_directory(spelled), lambda: fsio.remove_tree(secret),
            lambda: fsio.make_link(str(self.clone), secret, True),
            lambda: fsio.make_link(str(secret), self.home / "link", False),
            lambda: fsio.make_link(str(spelled), self.home / "link", False),
            lambda: fsio.read_bytes(secret),
        ):
            with self.assertRaises(fsio.CredentialsRefused):
                change()
        self.assertEqual(secret.read_bytes(), b"SECRET")
        self.assertFalse(os.path.lexists(self.home / "link"))

    @unittest.skipUnless(POSIX and hasattr(os, "geteuid") and os.geteuid() != 0, "needs permission bits that bind")
    def test_a_directory_that_cannot_be_looked_at_means_refused(self) -> None:
        locked = self.root / "locked"
        (locked / "inner" / "clone").mkdir(parents=True)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o700)
        with fsio.confined([self.home], [locked / "inner" / "clone"]):
            # Whether a place is inside the barred directory cannot be told.
            self.refused(self.home / "x", "cannot be looked at")

    def test_a_block_inside_a_block_has_its_own_bounds(self) -> None:
        with fsio.confined([self.root]):
            fsio.admit(self.project / "x")
            with fsio.confined([self.home]):
                self.refused(self.project / "x", "outside the directories")
            fsio.admit(self.project / "x")

    def test_each_primitive_asks(self) -> None:
        target = self.elsewhere / "t"
        inside = self.put(self.home / "inside", "1")
        with fsio.confined([self.home]):
            for name, change in {
                "atomic_write": lambda: fsio.atomic_write(target, b"x"),
                "write_new": lambda: fsio.write_new(target, b"x"),
                "make_directory": lambda: fsio.make_directory(target),
                "make_directory mode": lambda: fsio.make_directory(target, 0o750),
                "make_directories": lambda: fsio.make_directories(target / "a"),
                "publish_directory": lambda: fsio.publish_directory(target, lambda directory: None),
                "make_link": lambda: fsio.make_link(str(self.home), target, True),
                "remove_file": lambda: fsio.remove_file(self.put(self.elsewhere / "f", "1")),
                "remove_directory": lambda: fsio.remove_directory(self.elsewhere),
                "remove_tree": lambda: fsio.remove_tree(self.elsewhere),
            }.items():
                with self.subTest(name=name):
                    with self.assertRaises(SetupError):
                        change()
            self.assertFalse(fsio.remove_if_empty(self.root / "nothing-here"))
            self.assertFalse(fsio.remove_own_file(self.put(self.elsewhere / "own", "1")))
            self.assertFalse(fsio.discard_temporary(self.put(self.elsewhere / ".wfsetup-abcdabcd.tmp", "1")))
        self.assertEqual(sorted(os.listdir(self.elsewhere)), [".wfsetup-abcdabcd.tmp", "f", "own"])
        self.assertEqual(inside.read_bytes(), b"1")
        self.assertEqual(fsio.temporaries(self.home), [])


class ScopeTests(AdmitCase):
    """What the bounds of a record are: a change of the home is made in no
    project, and a change of a project in the project and nowhere else."""

    def test_the_confinement_of_the_two_scopes(self) -> None:
        roots, barred = self.roots.confinement(False)
        self.assertEqual(roots, [self.home])
        self.assertEqual(barred, [self.clone, self.project])
        roots, barred = self.roots.confinement(True)
        self.assertEqual(roots, [self.project])
        self.assertEqual(barred, [self.clone, self.roots.state_dir])

    def test_a_home_inside_the_project_is_barred_to_the_project(self) -> None:
        inner = self.project / "home"
        inner.mkdir()
        roots, barred = Roots(inner, self.project, self.clone).confinement(True)
        self.assertIn(inner, barred)

    def test_a_plan_for_a_project_that_holds_the_home_is_refused(self) -> None:
        inner = self.project / "home"
        inner.mkdir()
        self.put(inner / ".bashrc", "mine\n")
        plan = fileops.Plan(Roots(inner, self.project, self.clone), stamp=self.stamp())
        plan.write_file(self.project / "x.md", "x\n")
        before = self.snap()
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertIn("holds the home", caught.exception.lines[0])
        self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_project_entry_through_a_link_out_of_the_project_is_refused_whatever_the_flag(self) -> None:
        self.put(self.home / ".ssh" / "authorized_keys", "mine\n")
        os.symlink(self.home / ".ssh", self.project / "vendor", target_is_directory=True)
        for follow in (False, True):
            for name, fill in {
                "write": lambda plan: plan.write_file(self.project / "vendor" / "new.md", "x\n"),
                "remove": lambda plan: plan.remove_file(self.project / "vendor" / "authorized_keys"),
                "directory": lambda plan: plan.create_directory(self.project / "vendor" / "d"),
                "link": lambda plan: plan.create_link(self.project / "vendor" / "l", self.put(self.clone / "s" / "SKILL.md", "s").parent),
            }.items():
                with self.subTest(follow=follow, action=name):
                    plan = self.plan(follow_config_symlinks=follow)
                    fill(plan)
                    before = self.snap()
                    with self.assertRaises(fileops.PlanError):
                        plan.apply()
                    self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_following_a_link_stays_inside_the_home(self) -> None:
        inside = self.home / "dotfiles" / "claude"
        inside.mkdir(parents=True)
        os.symlink(inside, self.home / ".claude", target_is_directory=True)
        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n")
        plan.apply()
        self.assertEqual((inside / "agents" / "coder.md").read_bytes(), b"generated\n")
        self.reversal(follow_config_symlinks=True).apply()
        self.assertFalse((inside / "agents").exists())

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_following_a_link_out_of_the_home_is_refused(self) -> None:
        self.put(self.elsewhere / "CLAUDE.md", "theirs\n")
        (self.home / ".claude").mkdir()
        os.symlink(self.elsewhere, self.home / ".claude" / "shared", target_is_directory=True)
        for name, fill in {
            "write": lambda plan: plan.write_file(self.home / ".claude" / "shared" / "new.md", "x\n"),
            "block": lambda plan: plan.edit_block(self.home / ".claude" / "shared" / "CLAUDE.md", "text\n"),
            "remove": lambda plan: plan.remove_file(self.home / ".claude" / "shared" / "CLAUDE.md"),
        }.items():
            with self.subTest(action=name):
                plan = self.plan(follow_config_symlinks=True)
                fill(plan)
                before = self.snap()
                with self.assertRaises(fileops.PlanError) as caught:
                    plan.apply()
                self.assertIn(fileops.OUTSIDE, caught.exception.codes())
                self.assertEqual(self.snap(), before)
        self.assertIsNotNone(fileops.refusal(self.roots, self.home / ".claude" / "shared" / "x"))
        self.assertIsNone(fileops.refusal(self.roots, self.home / ".claude" / "x"))

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_state_directory_that_leads_into_the_clone_is_refused_before_any_lock(self) -> None:
        docs = self.clone / "docs"
        docs.mkdir(exist_ok=True)
        before_clone = sorted(os.listdir(docs))
        for scope, root in ((False, self.home), (True, self.project)):
            for where in ("agents", "state"):
                with self.subTest(project=scope, link=where):
                    agents = root / ".agents"
                    if where == "agents":
                        os.symlink(docs, agents, target_is_directory=True)
                    else:
                        agents.mkdir()
                        os.symlink(docs, agents / "workflow-setup", target_is_directory=True)
                    try:
                        for follow in (False, True):
                            with self.assertRaises(SetupError):
                                with lock.held(self.roots, project=scope, follow=follow):
                                    self.fail("the lock was taken through a link into the clone")
                            try:
                                # Refused, or nothing to do where no state
                                # directory is there; never a change.
                                fileops.remove_state(self.roots, project=scope, follow_config_symlinks=follow)
                                self.assertEqual(where, "agents")
                            except SetupError:
                                pass
                            plan = self.plan(follow_config_symlinks=follow)
                            plan.write_file(root / "generated.md", "x\n")
                            with self.assertRaises(fileops.PlanError):
                                plan.apply()
                        self.assertEqual(sorted(os.listdir(docs)), before_clone)
                        self.assertFalse((root / "generated.md").exists())
                    finally:
                        if where == "agents":
                            os.unlink(agents)
                        else:
                            os.unlink(agents / "workflow-setup")
                            agents.rmdir()

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_probe_directory_is_judged_where_the_system_finds_it(self) -> None:
        from wfsetup import discovery

        docs = self.clone / "docs"
        docs.mkdir(exist_ok=True)
        links = self.root / "links"
        links.mkdir()
        os.symlink(docs, links / "to-docs", target_is_directory=True)
        before = snapshot_of(self.clone)
        # The text says "links/probe"; the system reads "<clone>/probe".
        # Windows takes ".." out of the text before it follows a link, so
        # there the first form is "links/probe" to the system as well.
        texts = [links / "to-docs" / "probe", links / "to-docs", self.clone / "new"]
        if POSIX:
            texts.insert(0, links / "to-docs" / ".." / "probe")
        for text in texts:
            with self.subTest(text=str(text)):
                with self.assertRaises(SetupError) as caught:
                    discovery.save_directory(str(text), self.clone)
                self.assertIn("inside the clone", caught.exception.lines[0])
        self.assertEqual(snapshot_of(self.clone), before)
        # One that is not there yet, outside the clone, is fine, and is made.
        fresh = self.root / "probes" / "new"
        real = discovery.save_directory(str(fresh), self.clone)
        self.assertEqual(Path(real), Path(os.path.realpath(fresh)))
        self.assertFalse(fresh.exists())

    def test_clone_was_adds_a_place_for_links_and_never_replaces_the_clone(self) -> None:
        import dataclasses

        was = self.root / "where-the-clone-was"
        roots = dataclasses.replace(self.roots, clone_was=was)
        self.assertEqual(roots.clone, self.clone)
        self.assertIn(self.clone, roots.confinement(False)[1])
        self.assertIn(self.clone, roots.confinement(True)[1])
        self.assertEqual(roots.target_texts("clone:json-tools"), [str(self.clone / "json-tools"), str(was / "json-tools")])
        self.assertEqual(roots.target_texts("home:x"), [str(self.home / "x")])
        plan = fileops.Plan(roots, stamp=self.stamp())
        plan.write_file(self.clone / "rules" / "new.md", "x\n")
        with self.assertRaises(fileops.PlanError):
            plan.apply()
        self.assertFalse((self.clone / "rules").exists())

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_link_into_where_the_clone_was_is_setups_to_remove(self) -> None:
        import dataclasses

        skill = self.put(self.clone / "json-tools" / "SKILL.md", "s\n").parent
        plan = self.plan()
        plan.create_link(self.home / ".claude" / "skills" / "json-tools", skill)
        plan.apply()
        link = self.home / ".claude" / "skills" / "json-tools"
        was = self.root / "old-clone"
        (was / "json-tools").mkdir(parents=True)
        os.unlink(link)
        os.symlink(was / "json-tools", link, target_is_directory=True)   # as if the clone had been there
        self.assertEqual([key for key, _ in self.reversal().describe().kept], ["home:.claude/skills/json-tools"])
        roots = dataclasses.replace(self.roots, clone_was=was)
        result = fileops.plan_reversal(roots, stamp=self.stamp()).apply()
        self.assertEqual(result.kept, [])
        self.assertFalse(os.path.lexists(link))
        self.assertTrue((was / "json-tools").is_dir())


if __name__ == "__main__":
    unittest.main()
