"""Shared by the file-operation tests: a scratch home with roots, a plan
factory with fixed stamps, and a snapshot of a tree."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import support
from wfsetup import fileops
from wfsetup.manifest import Roots


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as scratch:
        try:
            os.symlink(scratch, os.path.join(scratch, "link"), target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS = _can_symlink()
POSIX = os.name == "posix"


def snapshot(root: Path) -> dict[str, tuple]:
    """Every path below ``root``: a link with its text, a directory, or a
    file with its bytes and permission bits."""
    found: dict[str, tuple] = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files]:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            status = os.lstat(path)
            if os.path.islink(path):
                found[relative] = ("link", os.readlink(path))
            elif stat.S_ISDIR(status.st_mode):
                found[relative] = ("directory",)
            else:
                found[relative] = ("file", path.read_bytes(), stat.S_IMODE(status.st_mode))
    return found


class OpsCase(support.ScratchCase):
    """A scratch home, project and clone, as roots."""

    def setUp(self) -> None:
        super().setUp()
        self.roots = Roots(self.home, self.project, self.clone)
        self.state = self.home / ".agents" / "workflow-setup"
        self.manifest_file = self.state / "manifest.json"
        self.project_state = self.project / ".agents" / "workflow-setup"
        self.project_manifest_file = self.project_state / "manifest.json"
        self._runs = 0

    def stamp(self) -> str:
        self._runs += 1
        return f"20260101T0000{self._runs:02d}000000Z"

    def plan(self, **options) -> fileops.Plan:
        return fileops.Plan(self.roots, stamp=self.stamp(), **options)

    def reversal(self, **options) -> fileops.Plan:
        return fileops.plan_reversal(self.roots, stamp=self.stamp(), **options)

    def put(self, path: Path, data: bytes | str, mode: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def snap(self) -> dict[str, tuple]:
        return snapshot(self.root)

    def record(self):
        return fileops.read_record(self.roots)

    def refused(self, plan: fileops.Plan) -> fileops.PlanError:
        """The plan is refused, by ``describe`` and by ``apply``, and the
        tree is as it was."""
        before = self.snap()
        with self.assertRaises(fileops.PlanError):
            plan.describe()
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(self.snap(), before)
        return caught.exception

    def temporaries(self) -> list[str]:
        return [name for name in self.snap() if os.path.basename(name).startswith(".wfsetup-")]
