"""Shared by the setup tests: the package on the path, and scratch places.

No test reads the real home directory or needs a provider: every run is
given a temporary home, and a temporary project where it needs one.

Nor does a test that pins exact content read the repository's own roles,
dictionaries or defaults. It runs on a fake clone built here from the
fixtures below, so adding a role, bringing a dictionary up to a newer
provider version or adding a setting edits no test. The repository's own
sources are checked by a few tests that hold whatever those sources say
(see ``ScratchCase.repository``).
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SETUP = TESTS.parent
SCRIPT = SETUP / "workflow_setup.py"
DEFAULTS = SETUP / "defaults.toml"
REPOSITORY = SETUP.parents[1]

if str(SETUP) not in sys.path:
    sys.path.insert(0, str(SETUP))

from wfsetup import cli, fsio, locations  # noqa: E402
from wfsetup.locations import Locations  # noqa: E402

# A test builds its scratch world with ``fsio``'s own functions (a link, a
# junction, a file). Outside the bounds of a run those may change the
# system's temporary directory and nothing else; the tool itself has no
# such base, and changes nothing outside a run's bounds.
fsio._BASE = fsio.bounds([tempfile.gettempdir()])

# ``doctor --project`` looks for a ``CLAUDE.md`` in every directory above the
# project. For a scratch project it stops below the temporary directory: a
# file of this machine's own above it (the user's ``.claude/CLAUDE.md``,
# where the temporary directory is inside the home) is no part of a test.
from wfsetup import instructions  # noqa: E402

instructions._CEILING = Path(tempfile.gettempdir()).resolve()

FIXTURES = TESTS / "fixtures"

# --- The fake clone ----------------------------------------------------------

FIXTURE_DEFAULTS = '''schema_version = 1

[process]
docs_dir = "docs"
questions = "one-at-a-time"
recommend = true

[roles]
enabled = true
manager_default = false
high_stakes = false
max_parallel_coders = 3

[memory]
dir = "docs/memory"

[setup]
allow_unshared_clone = false
'''

FIXTURE_DICTIONARIES = {
    "claude-code": '''schema_version = 1
display_name = "Claude Code"
checked_on_version = "2.1.289"
checked_on_date = "2026-10-05"
oldest_supported_version = "2.1.281"

[model_list]
note = "Claude Code has no command that lists models without starting a session; the dictionary alone is used."

[tiers]
fast = "haiku"
standard = "sonnet"
deep = "opus"
frontier = "fable"

[efforts]
low = "low"
medium = "medium"
high = "high"
max = "max"

[skills]
compaction_tokens = 5000

[models.haiku]
efforts = []

[models.sonnet]
efforts = ["low", "medium", "high", "xhigh", "max"]

[models.opus]
efforts = ["low", "medium", "high", "xhigh", "max"]

[models.fable]
efforts = ["low", "medium", "high", "xhigh", "max"]
''',
    "codex": '''schema_version = 1
display_name = "Codex"
checked_on_version = "0.160.0"
checked_on_date = "2026-10-05"

[model_list]
command = ["codex", "debug", "models"]
offline_command = ["codex", "debug", "models", "--bundled"]
experimental = true
note = "Read with a debug command that Codex marks experimental; it can change without notice."

[tiers]
fast = "gpt-6-luna"
standard = "gpt-6.1-sol"
deep = "gpt-6.1-sol"
frontier = "gpt-6-astra"

[efforts]
low = "low"
medium = "medium"
high = "high"
max = "max"

[models."gpt-6.1-sol"]
efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
visibility = "list"
default_effort = "low"

[models.gpt-6-astra]
efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
visibility = "list"
default_effort = "medium"

[models.gpt-6-sol]
efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
visibility = "list"
default_effort = "medium"

[models.gpt-6-luna]
efforts = ["low", "medium", "high", "xhigh", "max"]
visibility = "list"
default_effort = "medium"

[models.gpt-reserve]
efforts = ["low", "medium", "high", "xhigh", "max"]
visibility = "hide"
default_effort = "medium"

[models."gpt-5.5"]
efforts = ["low", "medium", "high", "xhigh"]
visibility = "list"
default_effort = "medium"
''',
}

FIXTURE_ROLES = {
    "coder": '''name = "coder"
title = "Coder"
description = "Implements one brief."
includes = ["brief-reading.md"]

[profile]
tier = "standard"
effort = "medium"

[profile.hard]
tier = "deep"
effort = "high"

[limits]
edits = true
commands = true
dispatches = []

[entry]
dispatch = true
load = false
start = false
''',
    "manager": '''name = "manager"
title = "Manager"
description = "Routes each request."

[profile]
tier = "standard"
effort = "medium"

[limits]
edits = false
commands = true
dispatches = ["product-manager", "coder", "coder-hard"]
''',
    "product-manager": '''name = "product-manager"
title = "Product Manager"
description = "Develops one idea."

[profile]
tier = "deep"
effort = "high"
high_stakes_tier = "frontier"
''',
}

# What the two fixture dictionaries give the providers group.
SHIPPED_PROVIDERS = {
    "providers.claude-code.tiers.fast": "haiku",
    "providers.claude-code.tiers.standard": "sonnet",
    "providers.claude-code.tiers.deep": "opus",
    "providers.claude-code.tiers.frontier": "fable",
    "providers.claude-code.efforts.low": "low",
    "providers.claude-code.efforts.medium": "medium",
    "providers.claude-code.efforts.high": "high",
    "providers.claude-code.efforts.max": "max",
    "providers.codex.tiers.fast": "gpt-6-luna",
    "providers.codex.tiers.standard": "gpt-6.1-sol",
    "providers.codex.tiers.deep": "gpt-6.1-sol",
    "providers.codex.tiers.frontier": "gpt-6-astra",
    "providers.codex.efforts.low": "low",
    "providers.codex.efforts.medium": "medium",
    "providers.codex.efforts.high": "high",
    "providers.codex.efforts.max": "max",
}
SHIPPED_PROVIDERS_TEXT = "".join(f'{key} = "{value}"  (shipped)\n' for key, value in SHIPPED_PROVIDERS.items())

# A dictionary with nothing wrong in it, for a provider that does not exist.
VALID_DICTIONARY = '''schema_version = 1
checked_on_version = "9.9.9"
checked_on_date = "2026-10-05"
oldest_supported_version = "9.0"

[model_list]
command = ["acme", "models"]
offline_command = ["acme", "models", "--offline"]
experimental = true
note = "May change."

[tiers]
fast = "a-small"
standard = "a-mid"
deep = "a-mid"
frontier = "a.large"

[efforts]
low = "minimal"
medium = "medium"
high = "high"
max = "extreme"

[models.a-small]
efforts = ["minimal", "medium"]

[models.a-mid]
efforts = ["minimal", "medium", "high", "extreme"]
visibility = "list"
default_effort = "medium"

[models."a.large"]
efforts = ["minimal", "medium", "high", "extreme", "beyond"]
visibility = "hide"

[models.a-plain]
efforts = []
'''

COMPACTION_LINE = "\n[skills]\ncompaction_tokens = {}\n"


def set_compaction_tokens(file: Path, tokens: int | None) -> None:
    """Give the dictionary at ``file`` the limit ``tokens`` on a loaded
    role's skill, or none: its ``[skills]`` table, as the fixtures write
    it, is taken out, and the new one, if any, goes at the end."""
    import re

    text = re.sub(r"\n\[skills\]\ncompaction_tokens = [0-9]+\n", "\n", file.read_text(encoding="utf-8"))
    if tokens is not None:
        text = text.rstrip("\n") + "\n" + COMPACTION_LINE.format(tokens)
    file.write_text(text, encoding="utf-8", newline="\n")


def run(*argv: str) -> tuple[int, str, str]:
    """Run the command line in this process: exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse: a usage error, or --help
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def child_environment() -> dict[str, str]:
    """The environment of a child process: this one's, without what would
    change where Python finds modules or whether it writes bytecode."""
    return {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}


def can_lock_directories() -> bool:
    """Whether taking a directory's permissions away keeps this process
    out of it: not on Windows, and not for root."""
    return os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0


class ScratchCase(unittest.TestCase):
    """A test with an empty home, an empty project and a fake clone.

    The clone holds the fixture defaults and, when ``FILLED``, the fixture
    dictionaries and roles. The command line run in this process
    (``run``, ``show``) works on that clone, not on the repository.
    """

    FILLED = True

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        # Made real, so that a path the tool finds from its own file equals
        # the one a test builds.
        self.root = Path(scratch.name).resolve()
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.user_file = self.home / ".agents" / "workflow.toml"
        self.project_file = self.project / ".agents" / "workflow.toml"
        self.local_file = self.project / ".agents" / "workflow.local.toml"

        # Not "clone": a test of another file builds a clone of its own there.
        self.clone = self.root / "fake-clone"
        self.defaults_file = self.write(self.clone / "tools" / "setup" / "defaults.toml", FIXTURE_DEFAULTS)
        self.roles_dir = self.clone / "roles"
        self.claude_code_dictionary = self.dictionary_file("claude-code")
        self.codex_dictionary = self.dictionary_file("codex")
        if self.FILLED:
            for provider, text in FIXTURE_DICTIONARIES.items():
                self.write(self.dictionary_file(provider), text)
            for role, text in FIXTURE_ROLES.items():
                self.write(self.role_file(role), text)
        patch = mock.patch.object(locations, "CLONE", self.clone)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, file: Path, text: str) -> Path:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(text.encode("utf-8"))
        return file

    def dictionary_file(self, provider: str) -> Path:
        return self.clone / "providers" / provider / "dictionary.toml"

    def role_file(self, role: str) -> Path:
        return self.clone / "roles" / role / "role.toml"

    def locations(self, project: bool = True) -> Locations:
        return Locations(home=self.home, project=self.project if project else None, clone=self.clone)

    def repository(self, project: bool = True) -> Locations:
        """The repository's own defaults, roles and dictionaries, with the
        scratch home and project. For tests that hold whatever they say."""
        return Locations(home=self.home, project=self.project if project else None, clone=REPOSITORY)

    def show(self, *argv: str, project: bool = True) -> tuple[int, str, str]:
        places = ["--home", str(self.home)]
        if project:
            places += ["--project", str(self.project)]
        return run("show", *argv, *places)

    def show_repository(self, *argv: str) -> tuple[int, str, str]:
        """``show`` on the repository itself, with the scratch home."""
        with mock.patch.object(locations, "CLONE", REPOSITORY):
            return run("show", *argv, "--home", str(self.home))

    def install_tool(self) -> Path:
        """Copy the tool into the fake clone and return its script, so a
        child process runs the real code on the fixtures."""
        target = self.clone / "tools" / "setup"
        shutil.copyfile(SCRIPT, target / SCRIPT.name)
        shutil.copytree(SETUP / "wfsetup", target / "wfsetup", ignore=shutil.ignore_patterns("__pycache__"))
        return target / SCRIPT.name


class CloneCase(ScratchCase):
    """A test whose clone holds the fixture defaults and nothing else: only
    the provider dictionaries and the roles the test writes."""

    FILLED = False

    def setUp(self) -> None:
        super().setUp()
        self.dictionary = self.dictionary_file("acme")

    def where(self) -> Locations:
        return self.locations()

    def write_role(self, role: str, profile: str, name: str | None = None) -> Path:
        """A role whose ``[profile]`` table, and anything after it, is
        ``profile``."""
        return self.write(
            self.role_file(role),
            f'name = "{name or role}"\ntitle = "{role.title()}"\ndescription = "Does {role} work."\n'
            f"\n[profile]\n{profile}",
        )
