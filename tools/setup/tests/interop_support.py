"""The Windows side of this machine, for the tests that need both sides.

A test that runs under Linux in WSL can start a Windows program and can
write to a Windows drive. That is the only way to test what one side sees
of what the other made: a junction made by Windows, read from WSL; a link
made in WSL, met by the Windows Python.

Nothing here names a machine. The Windows system directory is looked for
on the drives WSL has mounted (the mount table says which they are and
which drive letter each has), ``cmd.exe`` there says where the Windows
temporary directory is, and ``where`` says where a Windows Python is. A
test asks with ``need``, which skips it, with the reason, on a Linux that
is not WSL, in a WSL that starts no Windows program, and where no Windows
Python of the version setup needs is installed.

Every scratch directory is made below the Windows temporary directory and
is removed when the test ends.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts the package on the path)
from wfsetup import homes

_DRIVE = re.compile(r"([A-Za-z]):\\?")
_OCTAL = re.compile(r"\\([0-7]{3})")
_TIMEOUT = 120


def drive_table(table: str) -> dict[str, str]:
    """Drive letter (lower case) to mount point, from the text of the
    mount table. WSL writes the drive as the mounted device (``C:\\``); a
    mount that does not say is taken by the last part of its mount point,
    when that is one letter."""
    found: dict[str, str] = {}
    points = set(homes.drive_mounts(table))
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        device, point = (_OCTAL.sub(lambda match: chr(int(match.group(1), 8)), text) for text in fields[:2])
        if point not in points:
            continue
        named = _DRIVE.fullmatch(device)
        letter = named.group(1) if named else os.path.basename(point.rstrip("/"))
        if len(letter) == 1 and letter.isalpha():
            found.setdefault(letter.lower(), point)
    return found


@dataclass(frozen=True)
class Windows:
    """The Windows side as a test on the WSL side reaches it."""

    drives: dict[str, str]     # drive letter to mount point
    system: Path               # the Windows system directory, as WSL sees it
    cmd: Path
    temp: str                  # the Windows temporary directory, as Windows writes it
    python: str | None         # a Windows Python, as WSL starts it

    def here(self, text: str) -> Path:
        """A Windows drive path as this side writes it."""
        named = re.match(r"([A-Za-z]):[\\/]*(.*)", text)
        if named is None or named.group(1).lower() not in self.drives:
            raise ValueError(f"{text}: not on a drive that is mounted here")
        return Path(self.drives[named.group(1).lower()], *re.split(r"[\\/]+", named.group(2)))

    def there(self, path: Path | str) -> str:
        """A path below a drive's mount point as Windows writes it."""
        text = os.fspath(path)
        for letter, point in sorted(self.drives.items(), key=lambda item: -len(item[1])):
            stem = point.rstrip("/")
            if text == stem or text.startswith(stem + "/"):
                return f"{letter.upper()}:\\" + text[len(stem) + 1:].replace("/", "\\")
        raise ValueError(f"{text}: not on a Windows drive")

    def run(self, *argv: str) -> subprocess.CompletedProcess:
        """Start a Windows program and wait. Its working directory is the
        Windows system directory: ``cmd.exe`` complains of one inside WSL."""
        return subprocess.run(
            list(argv), cwd=self.system, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=_TIMEOUT, check=False,
        )

    def shell(self, *words: str) -> subprocess.CompletedProcess:
        """A built-in of ``cmd.exe`` (``mklink``, ``rmdir``)."""
        return self.run(str(self.cmd), "/d", "/c", *words)

    def scratch(self, test: unittest.TestCase) -> Path:
        """A new directory in the Windows temporary directory, gone when
        ``test`` ends."""
        made = tempfile.TemporaryDirectory(prefix="wfsetup-two-sides-", dir=self.here(self.temp))
        test.addCleanup(made.cleanup)
        return Path(made.name)

    def as_temp(self) -> mock._patch:
        """While this is entered, ``tempfile`` makes its directories in the
        Windows temporary directory."""
        return mock.patch.object(tempfile, "tempdir", str(self.here(self.temp)))


def _said(done: subprocess.CompletedProcess) -> list[str]:
    return [line.strip() for line in done.stdout.decode("utf-8", "replace").splitlines() if line.strip()]


def _find() -> tuple[Windows | None, str]:
    if homes.detect_side() != homes.WSL:
        return None, "needs WSL: this is not the Linux side of a machine with a Windows side"
    try:
        with open("/proc/self/mounts", "r", encoding="utf-8", errors="replace") as stream:
            drives = drive_table(stream.read())
    except OSError as exc:
        return None, f"the mount table cannot be read: {exc}"
    system = next(
        (Path(point, name, "System32") for point in drives.values() for name in ("Windows", "WINDOWS", "windows")
         if Path(point, name, "System32", "cmd.exe").is_file()),
        None,
    )
    if system is None:
        return None, "no Windows system directory on a mounted drive (is a Windows drive mounted in this WSL?)"
    found = Windows(drives, system, system / "cmd.exe", "", None)
    try:
        temp = _said(found.shell("echo", "%TEMP%"))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"this WSL starts no Windows program (interop is off?): {exc}"
    if len(temp) != 1 or "%" in temp[0]:
        return None, "cmd.exe did not say where the Windows temporary directory is"
    found = Windows(drives, system, found.cmd, temp[0], None)
    try:
        if not found.here(temp[0]).is_dir():
            return None, f"the Windows temporary directory {temp[0]} is not on a drive mounted here"
    except ValueError as exc:
        return None, str(exc)
    for text in _said(found.shell("where", "python.exe", "py.exe")):
        if "\\WindowsApps\\" in text:
            continue  # the store's stand-in, which is no Python
        try:
            program = str(found.here(text))
            version = _said(found.run(program, "-c", "import sys; print(*sys.version_info[:2])"))
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
        if len(version) == 1 and tuple(int(part) for part in version[0].split() if part.isdigit()) >= (3, 11):
            return Windows(drives, system, found.cmd, temp[0], program), ""
    return found, ""


_FOUND: tuple[Windows | None, str] | None = None


def need(test: unittest.TestCase, python: bool = False) -> Windows:
    """The Windows side, or the test is skipped with the reason."""
    global _FOUND
    if _FOUND is None:
        _FOUND = _find()
    found, why = _FOUND
    if found is None:
        test.skipTest(why)
    if python and found.python is None:
        test.skipTest("no Windows Python 3.11 or later is installed on the Windows side (`where python.exe py.exe`)")
    return found
