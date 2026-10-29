"""A provider's own model list, read without a session, and how it compares
with the provider's dictionary (gate G11).

How ``init`` and ``doctor`` use it

    known = dictionary.load(where, "codex")
    environ = homes.child_environment(found)        # never the real home's for a scratch home
    reading = modellist.read(known, environ, program_file=provider.program_file)
    if not reading.has_list:
        print(reading.describe())           # why: the dictionary alone is used
    found = modellist.compare(known, reading, mapping)     # None with no list
    found.missing_mapped, found.new_models, found.effort_differences, ...
    for line in found.lines(): print(line)
    checked = modellist.effective(known, reading)   # the dictionary as the list corrects it
    checked.accepts(model, effort)

    reading, found = modellist.check(known, environ)       # both at once

Where a list comes from
    The dictionary says how (``[model_list]``): ``command`` is tried first,
    and ``offline_command`` when that fails (for Codex ``codex debug models``,
    which refreshes the catalog over the network, then ``--bundled``, the
    catalog shipped in the binary). A dictionary with no ``command`` (Claude
    Code) gives no list: nothing lists that provider's models without
    starting a session.

    A reading is one of
      live     ``command`` answered
      offline  ``command`` failed, ``offline_command`` answered; ``notes``
               say why the first failed
      none     no list: no command, the program is not on ``PATH``, or
               neither command gave a list; ``reason`` says which

    A command fails when it cannot be started, does not finish in time,
    exits with another code than 0, prints more than ``MAX_OUTPUT`` bytes,
    or prints what is not a list (below). No failure is an error here: the
    caller falls back to the dictionary alone and says so.

How the program is started
    The first word of the command is looked up on the ``PATH`` of the
    environment given (or ``program_file`` is used, where ``homes`` found
    it), and the file found is started with the rest of the command as a
    fixed argument list: no shell, nothing from a settings file, standard
    input closed. Its environment is the one given: ``init`` and ``doctor``
    give ``homes.child_environment``, which for a scratch home points the
    provider at that home and never at the real one. This module reads no
    credentials and passes none of its own. On a timeout
    the program and what it started are ended: a provider's program is
    often a launcher that starts the real one.

What is read as a list
    The commands are experimental, so the reading is lenient. The output is
    one JSON object with a ``models`` array. Lines before or after it that
    are not JSON (a warning, a notice of an update) are skipped: the object
    is looked for at the start of each line, and only an object that has a
    ``models`` array is taken. Each entry is an object with a ``slug``;
    ``visibility``, ``default_reasoning_level`` and
    ``supported_reasoning_levels[].effort`` are optional, and any other key
    is ignored. An entry that is not such an object is skipped. A list with
    no entry is not taken for a list: compared with it, every mapped model
    would be missing.

    A model is offered for selection when its ``visibility`` is ``list``,
    or when the entry does not say. Any other value is a hidden entry.
    An entry that does not list its efforts leaves the dictionary's entry
    for that model in force.

What an account can actually use may differ from the list and from the
dictionary; neither is a promise.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass, replace
from typing import Any, Mapping

from . import fsio, paths, tomlio
from .dictionary import Dictionary, Model

LIVE = "live"
OFFLINE = "offline"
NONE = "none"

# The visibility of an entry that is offered for selection.
LISTED = "list"

# How long one command may take, in seconds. Read when ``read`` is called.
DEFAULT_TIMEOUT = 30.0

# The most a command may print. The full Codex catalog, with each model's
# base instructions, is a few hundred kilobytes.
MAX_OUTPUT = 32 * 1024 * 1024

_FIRST_LINE = 200


@dataclass(frozen=True)
class Listed:
    """One entry of a provider's list. ``efforts`` is None when the entry
    does not say which effort values the model accepts."""

    name: str
    efforts: tuple[str, ...] | None = None
    visibility: str | None = None
    default_effort: str | None = None

    @property
    def offered(self) -> bool:
        return self.visibility is None or self.visibility == LISTED


@dataclass(frozen=True)
class Reading:
    """A provider's list, or why there is none. See the module."""

    provider: str
    source: str
    models: tuple[Listed, ...] = ()
    command: tuple[str, ...] | None = None  # the command that gave the list
    reason: str = ""                        # NONE: why there is no list
    notes: tuple[str, ...] = ()             # each command that failed, and why

    @property
    def has_list(self) -> bool:
        return self.source != NONE

    def model(self, name: str) -> Listed | None:
        for entry in self.models:
            if entry.name == name:
                return entry
        return None

    def offered(self) -> list[str]:
        """The names of the entries offered for selection, in the list's order."""
        return [entry.name for entry in self.models if entry.offered]

    def describe(self) -> str:
        """One line: where the list came from, or why the dictionary alone
        is used."""
        if not self.has_list:
            return f"no model list: {self.reason}; the dictionary alone is used"
        hidden = len(self.models) - len(self.offered())
        count = f"{len(self.models)} models" + (f", {hidden} of them hidden" if hidden else "")
        text = f"checked against the list of `{' '.join(self.command or ())}` ({count})"
        if self.source == OFFLINE:
            text += "; this is the list shipped with the program, read because " + "; ".join(self.notes)
        return text


@dataclass(frozen=True)
class EffortDifference:
    model: str
    dictionary: tuple[str, ...]
    listed: tuple[str, ...]


@dataclass(frozen=True)
class Comparison:
    """A list beside the dictionary.

    ``missing_mapped`` and ``hidden_mapped`` are (key, model) pairs of the
    mapping compared: ``tiers.deep``, ``role_models.coder``. The rest is
    about the two sets of models, whatever is mapped.
    """

    provider: str
    missing_mapped: tuple[tuple[str, str], ...] = ()   # mapped, and not in the list
    hidden_mapped: tuple[tuple[str, str], ...] = ()    # mapped, and a hidden entry
    new_models: tuple[str, ...] = ()                   # offered, and not in the dictionary
    new_hidden: tuple[str, ...] = ()                   # hidden, and not in the dictionary
    gone_models: tuple[str, ...] = ()                  # in the dictionary, and not in the list
    effort_differences: tuple[EffortDifference, ...] = ()
    visibility_differences: tuple[tuple[str, str | None, str | None], ...] = ()      # model, dictionary, list
    default_effort_differences: tuple[tuple[str, str | None, str | None], ...] = ()  # model, dictionary, list

    @property
    def dictionary_equal(self) -> bool:
        """Whether the dictionary's models are the list's: the same names,
        each with the same efforts, visibility and default effort."""
        return not (
            self.new_models or self.new_hidden or self.gone_models or self.effort_differences
            or self.visibility_differences or self.default_effort_differences
        )

    @property
    def equal(self) -> bool:
        return self.dictionary_equal and not self.missing_mapped and not self.hidden_mapped

    def new_models_line(self) -> str | None:
        """The line for the models the list offers and the dictionary lacks,
        or None when there is none. Doctor makes it a warning; render prints
        it."""
        if not self.new_models:
            return None
        return f"in the list and not in the dictionary: {', '.join(self.new_models)}"

    def lines(self) -> list[str]:
        """Every difference, one line each; empty when there is none."""
        show = tomlio.format_value
        lines = [
            f"{key} = {show(model)}: the model is not in the provider's list" for key, model in self.missing_mapped
        ]
        lines += [
            f"{key} = {show(model)}: the list holds the model as a hidden entry" for key, model in self.hidden_mapped
        ]
        if self.new_models:
            lines.append(self.new_models_line())
        if self.new_hidden:
            lines.append(f"in the list as hidden entries and not in the dictionary: {', '.join(self.new_hidden)}")
        if self.gone_models:
            lines.append(f"in the dictionary and not in the list: {', '.join(self.gone_models)}")
        for found in self.effort_differences:
            lines.append(
                f"{found.model}: the dictionary has the efforts {', '.join(found.dictionary) or 'none'}; "
                f"the list has {', '.join(found.listed) or 'none'}"
            )
        for model, ours, theirs in self.visibility_differences:
            lines.append(f"{model}: the dictionary has the visibility {_said(ours)}; the list has {_said(theirs)}")
        for model, ours, theirs in self.default_effort_differences:
            lines.append(f"{model}: the dictionary has the default effort {_said(ours)}; the list has {_said(theirs)}")
        return lines


def _said(value: str | None) -> str:
    return "none" if value is None else tomlio.format_value(value)


# --- Reading ------------------------------------------------------------------

class ProgramFailed(Exception):
    """A program could not be started, did not finish in time, or printed
    too much; the text says which, and reads on after the program's name."""


class _Failed(ProgramFailed):
    """One command gave no list; the text says why."""


def parse(text: str) -> tuple[Listed, ...]:
    """The entries of a list as a provider printed it. A ``ValueError``
    says why the text is not a list; see the module for what is."""
    models = _models_of(text)
    found: dict[str, Listed] = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("slug")
        if not isinstance(name, str) or not name.strip() or name in found:
            continue
        found[name] = Listed(
            name=name,
            efforts=_efforts_of(entry.get("supported_reasoning_levels")),
            visibility=_text_or_none(entry.get("visibility")),
            default_effort=_text_or_none(entry.get("default_reasoning_level")),
        )
    if not found:
        raise ValueError("printed a list with no model in it" if not models else "printed a list in which no entry names a model")
    return tuple(found.values())


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _efforts_of(levels: Any) -> tuple[str, ...] | None:
    if not isinstance(levels, list):
        return None
    efforts: list[str] = []
    for level in levels:
        value = level.get("effort") if isinstance(level, dict) else level
        if isinstance(value, str) and value and value not in efforts:
            efforts.append(value)
    return tuple(efforts)


def _models_of(text: str) -> list[Any]:
    try:
        candidates = [json.loads(text)]
    except (ValueError, RecursionError):
        # Not JSON as a whole: an object that starts a line, with other
        # lines around it.
        candidates = []
        decoder = json.JSONDecoder()
        offset = 0
        for line in text.splitlines(keepends=True):
            if line.startswith("{"):
                try:
                    candidates.append(decoder.raw_decode(text, offset)[0])
                except (ValueError, RecursionError):
                    pass
            offset += len(line)
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("models"), list):
            return candidate["models"]
    if not text.strip():
        raise ValueError("printed nothing")
    raise ValueError("printed what is not a model list (no JSON object with a `models` array)")


def read(
    known: Dictionary,
    environ: Mapping[str, str] | None = None,
    *,
    program_file: str | None = None,
    timeout: float | None = None,
) -> Reading:
    """The provider's own list, or the reason there is none. Never raises
    for what the provider's program does; see the module.

    ``environ`` is the environment the program is looked up in and started
    with, this process's own when None. ``program_file`` is the program
    where it was already found (``homes.Provider.program_file``).
    """
    environ = os.environ if environ is None else environ
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    listing = known.model_list
    if listing.command is None:
        return Reading(
            known.provider, NONE,
            reason=f"{known.provider} has no command that lists models without starting a session",
        )
    notes: list[str] = []
    for source, command in ((LIVE, listing.command), (OFFLINE, listing.offline_command)):
        if command is None:
            continue
        program = program_file if program_file and command[0] == listing.command[0] else None
        program = program or _which(command[0], environ)
        if program is None:
            notes.append(f"the program `{command[0]}` is not on PATH")
            continue
        try:
            models = parse(_run((program, *command[1:]), environ, timeout))
        except _Failed as exc:
            notes.append(f"`{' '.join(command)}` {exc}")
            continue
        except ValueError as exc:
            notes.append(f"`{' '.join(command)}` {exc}")
            continue
        return Reading(known.provider, source, models, tuple(command), notes=tuple(notes))
    return Reading(known.provider, NONE, reason="; ".join(dict.fromkeys(notes)), notes=tuple(notes))


def _which(program: str, environ: Mapping[str, str]) -> str | None:
    search = environ.get("PATH", "")
    if not search:
        return None
    try:
        return shutil.which(program, path=search)
    except (OSError, ValueError):
        return None


def run_program(argv: tuple[str, ...], environ: Mapping[str, str], timeout: float) -> tuple[int, str, str]:
    """Start a program as ``_run`` does (a fixed argument list, no shell,
    standard input closed, ended with what it started on a timeout) and
    return its exit code, what it printed, and the first line of its
    standard error. Any exit code is an answer here: ``doctor`` starts
    programs whose code is part of what they say. A ``ProgramFailed`` when
    it could not be started, did not finish in time or printed too much."""
    with fsio.scratch_file() as out, fsio.scratch_file() as err:
        options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(
                list(argv), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                env=dict(environ), shell=False, **options,
            )
        except (OSError, ValueError) as exc:
            raise ProgramFailed(f"could not be started: {paths.reason(exc)}") from None
        try:
            code = process.wait(timeout)
        except subprocess.TimeoutExpired:
            _end(process)
            raise ProgramFailed(f"did not finish within {timeout:g} seconds") from None
        except BaseException:
            _end(process)
            raise
        data = _contents(out, MAX_OUTPUT + 1, raw=True)
        if len(data) > MAX_OUTPUT:
            raise ProgramFailed(f"printed more than {MAX_OUTPUT} bytes")
        return code, data.decode("utf-8-sig", errors="replace"), _first_line(_contents(err, 4096))


def _run(argv: tuple[str, ...], environ: Mapping[str, str], timeout: float) -> str:
    """What the program printed. Its output goes to files, not pipes: a
    pipe would be held open by a program the launcher started, and reading
    it would wait for that program long after the timeout."""
    with fsio.scratch_file() as out, fsio.scratch_file() as err:
        options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(
                list(argv), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                env=dict(environ), shell=False, **options,
            )
        except (OSError, ValueError) as exc:
            raise _Failed(f"could not be started: {paths.reason(exc)}") from None
        try:
            code = process.wait(timeout)
        except subprocess.TimeoutExpired:
            _end(process)
            raise _Failed(f"did not finish within {timeout:g} seconds") from None
        except BaseException:
            _end(process)
            raise
        if code != 0:
            said = _first_line(_contents(err, 4096))
            raise _Failed(f"exited with code {code}" + (f": {said}" if said else ""))
        data = _contents(out, MAX_OUTPUT + 1, raw=True)
        if len(data) > MAX_OUTPUT:
            raise _Failed(f"printed more than {MAX_OUTPUT} bytes")
        return data.decode("utf-8-sig", errors="replace")


def _contents(stream: Any, limit: int, raw: bool = False) -> Any:
    stream.seek(0)
    data = stream.read(limit)
    return data if raw else data.decode("utf-8", errors="replace")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            line = "".join(char if char.isprintable() else " " for char in line.strip())
            return line if len(line) <= _FIRST_LINE else line[:_FIRST_LINE] + "..."
    return ""


def _end(process: subprocess.Popen) -> None:
    """End the program and what it started, and do not wait long for it."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            # ``taskkill /T`` ends the whole tree; ``kill`` below ends
            # the launcher alone where it cannot be found.
            root = os.environ.get("SystemRoot", "")
            taskkill = os.path.join(root, "System32", "taskkill.exe") if root else "taskkill"
            subprocess.run(
                [taskkill, "/T", "/F", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(5)
    except (OSError, subprocess.SubprocessError):
        pass


# --- Comparing ----------------------------------------------------------------

def mapping_of(known: Dictionary) -> dict[str, str]:
    """The dictionary's own mapping, by key: ``tiers.<tier>`` and
    ``role_models.<role id>``."""
    mapped = {f"tiers.{tier}": model for tier, model in known.tiers.items()}
    mapped.update({f"role_models.{role}": model for role, model in known.role_models.items()})
    return mapped


def compare(known: Dictionary, reading: Reading, mapping: Mapping[str, str] | None = None) -> Comparison | None:
    """``reading`` beside the dictionary, or None when there is no list.
    ``mapping`` is the mapping in effect, key to model as ``mapping_of``
    gives it; the dictionary's own when None."""
    if not reading.has_list:
        return None
    mapping = mapping_of(known) if mapping is None else mapping
    listed = {entry.name: entry for entry in reading.models}
    efforts: list[EffortDifference] = []
    visibility: list[tuple[str, str | None, str | None]] = []
    defaults: list[tuple[str, str | None, str | None]] = []
    for name, ours in known.models.items():
        theirs = listed.get(name)
        if theirs is None:
            continue
        if theirs.efforts is not None and theirs.efforts != ours.efforts:
            efforts.append(EffortDifference(name, ours.efforts, theirs.efforts))
        if theirs.visibility != ours.visibility:
            visibility.append((name, ours.visibility, theirs.visibility))
        if theirs.default_effort != ours.default_effort:
            defaults.append((name, ours.default_effort, theirs.default_effort))
    return Comparison(
        provider=known.provider,
        missing_mapped=tuple((key, model) for key, model in mapping.items() if model not in listed),
        hidden_mapped=tuple(
            (key, model) for key, model in mapping.items() if model in listed and not listed[model].offered
        ),
        new_models=tuple(name for name, entry in listed.items() if name not in known.models and entry.offered),
        new_hidden=tuple(name for name, entry in listed.items() if name not in known.models and not entry.offered),
        gone_models=tuple(name for name in known.models if name not in listed),
        effort_differences=tuple(efforts),
        visibility_differences=tuple(visibility),
        default_effort_differences=tuple(defaults),
    )


def effective(known: Dictionary, reading: Reading) -> Dictionary:
    """The dictionary with what the list says in place of what it says: a
    listed model has the list's efforts (where the entry gives them),
    visibility and default effort, and a model only the list has is added.
    A model only the dictionary has stays. With no list, the dictionary."""
    if not reading.has_list:
        return known
    models = dict(known.models)
    for entry in reading.models:
        ours = models.get(entry.name)
        if entry.efforts is None and ours is None:
            continue  # nothing is known about its efforts: left unlisted, so unchecked
        models[entry.name] = Model(
            entry.name,
            ours.efforts if entry.efforts is None else entry.efforts,
            entry.visibility,
            entry.default_effort,
        )
    return replace(known, models=models)


def check(
    known: Dictionary,
    environ: Mapping[str, str] | None = None,
    *,
    mapping: Mapping[str, str] | None = None,
    program_file: str | None = None,
    timeout: float | None = None,
) -> tuple[Reading, Comparison | None]:
    """``read`` and ``compare`` in one call."""
    reading = read(known, environ, program_file=program_file, timeout=timeout)
    return reading, compare(known, reading, mapping)
