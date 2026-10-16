"""The commands: one module per command, found by name.

What is a command:

    - A module directly in this package is a candidate, under its own name
      with ``_`` written ``-``.
    - A name that starts with an underscore is skipped, and so is a
      subpackage (a directory): neither is ever imported from here.
    - A candidate is a command when it defines ``run``. One that does not is
      a helper module: it is left alone, and nothing fails because of it.

A command module defines:

    run(args) -> int   does the work and returns the exit code (required)
    SUMMARY            one line for the command list (optional)
    configure(parser)  adds its arguments to an ``argparse`` parser (optional)

and its docstring is the command's own ``--help`` text. Adding a command
adds a file here and edits no other.

One faulty module does not take the others down. The command line imports
only the module of the command it names (``names`` lists the candidates
without importing any). The full list, which ``--help`` prints, is built
by ``survey``: a module that cannot be imported is shown there as
"unavailable", with the reason, and fails only when it is the command
asked for, as a one-line error.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from types import ModuleType

from ..errors import SetupError


def _package(package: ModuleType | None) -> ModuleType:
    return package or sys.modules[__name__]


def reason(exc: BaseException) -> str:
    """Why a module is unavailable, on one line."""
    return " ".join(f"{type(exc).__name__}: {exc}".split())


def names(package: ModuleType | None = None) -> dict[str, str]:
    """The candidates, command name to module name, in the order of the
    command names. Nothing is imported."""
    package = _package(package)
    found = {
        info.name.replace("_", "-"): info.name
        for info in pkgutil.iter_modules(package.__path__)
        if not info.ispkg and not info.name.startswith("_")
    }
    return dict(sorted(found.items()))


def load(name: str, package: ModuleType | None = None) -> ModuleType | None:
    """Import the module of the candidate ``name`` and return it, or None
    when it is a helper and not a command. A module that cannot be imported
    is a ``SetupError`` of one line."""
    package = _package(package)
    module_name = names(package).get(name)
    if module_name is None:
        raise SetupError(f"{name}: no such command")
    try:
        module = importlib.import_module(f"{package.__name__}.{module_name}")
    except Exception as exc:  # whatever the module's own code raises
        raise SetupError(f"command {name}: unavailable: {reason(exc)}") from None
    return module if callable(getattr(module, "run", None)) else None


def survey(package: ModuleType | None = None) -> tuple[dict[str, ModuleType], dict[str, str]]:
    """Every candidate imported: the commands by name, and for each module
    that could not be imported, the reason by name. Helpers are in neither."""
    found: dict[str, ModuleType] = {}
    unavailable: dict[str, str] = {}
    for name in names(package):
        try:
            module = load(name, package)
        except SetupError as exc:
            unavailable[name] = str(exc).split(": unavailable: ", 1)[-1]
            continue
        if module is not None:
            found[name] = module
    return found, unavailable


def discover(package: ModuleType | None = None) -> dict[str, ModuleType]:
    """The commands that can be imported, by name."""
    return survey(package)[0]
