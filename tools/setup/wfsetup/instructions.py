"""Whether both providers load a project's ``AGENTS.md``: the check
``instruction-files`` of ``doctor --project DIR``.

The project's ``AGENTS.md`` holds the lesson index of the ``project-memory``
skill, so a provider that does not load the file does not see the index.
``project-memory/references/loading.md`` says the same to a session; the
provider pages below were read on 2026-10-12.

Claude Code (code.claude.com/docs/en/memory)
    Reads ``AGENTS.md`` directly from 2.1.277, and in every kind of session
    from 2.1.281, only while no ``CLAUDE.md``, ``.claude/CLAUDE.md`` or
    ``CLAUDE.local.md`` is in the directory a session starts in or in one
    above it. The user's own ``CLAUDE.md`` does not count: the file of that
    name that lies in the Claude Code home. It is told by where it lies and
    not by what it leads to: a project's ``CLAUDE.md`` that is a link to the
    user's own is the project's, and counts. Where the Claude Code home is
    not ``~/.claude`` (``CLAUDE_CONFIG_DIR``), ``~/.claude/CLAUDE.md`` is an
    ordinary ``.claude/CLAUDE.md`` of the home directory, and counts for a
    project below it. Where one of the three is there, Claude Code reads
    the ``CLAUDE.md`` files alone, and ``AGENTS.md`` loads by one of two
    remedies:

      an import   a line ``@AGENTS.md`` in one of those files, the path
                  relative to the file that holds it. Only an import
                  written in one of the three files is looked for: a file
                  that an import names is not opened, so an ``AGENTS.md``
                  reached through a second file is not seen. A file that
                  is a link to the project's ``AGENTS.md`` is that file,
                  and counts as importing it. ``imports`` says what is no
                  import: where it cannot tell, it finds none.
      a setting   ``pluginConfigs."agents-md@builtin".options.instructionFiles``
                  set to ``claude-md-and-agents-md`` in the user's
                  ``settings.json``. Claude Code ignores the key in a
                  project's settings files. From 2.1.285 the plugin's id is
                  ``cc-plugin-agents-md@builtin`` and either id is read;
                  before it only the older one is. Both are looked at. The
                  value under the newer id alone is a remedy from 2.1.285
                  only, and this tool supports Claude Code from 2.1.281:
                  a **warning**, not a pass. Two ids with different values
                  are no remedy: a **warning** that names both values.

    One of the three with neither remedy is an **error**. The values
    ``claude-md`` and ``managed-only`` of the same setting stop the direct
    reading: a warning where nothing imports the file.

    Claude Code skips an instruction file over 4 MiB. Such a file is said
    to be skipped, is not opened, and an import in it is no remedy: a
    **warning** for a ``CLAUDE.md``, an **error** for the project's
    ``AGENTS.md``, which is then not loaded whatever names it. A file it
    loads here that is over three quarters of that is a **warning**.

Codex (learn.chatgpt.com/docs/agent-configuration/agents-md)
    Builds its instructions once, when it starts: the first non-empty of
    ``AGENTS.override.md`` and ``AGENTS.md`` in the Codex home, then one
    file for each directory from the project root down to the directory it
    was started in, ``AGENTS.override.md`` before ``AGENTS.md``. So an
    ``AGENTS.override.md`` in the project root that is a file and not
    empty replaces the ``AGENTS.md`` beside it: a **warning**. An empty one
    replaces nothing (info), and a directory of that name is no file. It
    stops adding files once their combined
    size reaches ``project_doc_max_bytes``, 32 KiB by default: a
    **warning** when the Codex home's file and the project root's file are
    together over three quarters of the limit. (The page on advanced
    configuration words the limit per file; the combined size is the
    stricter reading.) The limit is read from the user's ``config.toml``, as
    one of ``doctor.CODEX_KEYS``; a project's ``.codex/config.toml`` is not
    looked at, nor a file in a directory below the project root.

"At or above" is by the project's real path, every link followed, since
that is the directory a session is in: its own directory, then each parent
up to the root of the file system or of the drive.

A doubt is settled against the project: a remedy that is not there and is
reported as there costs more than an error that is not one.

Nothing is written. A credentials file is never opened. Of a settings file
only the one key is read and only a value the setting takes is printed.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from . import codexsettings, fsio, homes, jsonkeys, paths
from .errors import SetupError

NAME = "instruction-files"

AGENTS = "AGENTS.md"
OVERRIDE = "AGENTS.override.md"
# The three files of Claude Code, as they lie in one directory.
CLAUDE_FILES = (("CLAUDE.md",), (".claude", "CLAUDE.md"), ("CLAUDE.local.md",))
IMPORT_LINE = "@AGENTS.md"

SETTINGS_FILE = "settings.json"
PROJECT_SETTINGS = ((".claude", "settings.json"), (".claude", "settings.local.json"))
PLUGIN_ID = "agents-md@builtin"
PLUGIN_ID_NEW = "cc-plugin-agents-md@builtin"   # from Claude Code 2.1.285
PLUGIN_IDS = (PLUGIN_ID, PLUGIN_ID_NEW)
SETTING = f'pluginConfigs."{PLUGIN_ID}".options.instructionFiles'
BOTH = "claude-md-and-agents-md"
EITHER = "claude-md-or-agents-md"   # the default
CLAUDE_ONLY = "claude-md"
MANAGED_ONLY = "managed-only"
SETTING_VALUES = (EITHER, BOTH, CLAUDE_ONLY, MANAGED_ONLY)

DIRECT_FROM = "2.1.277"
EVERY_SESSION_FROM = "2.1.281"

CODEX_DEFAULT_LIMIT = 32 * 1024
CLAUDE_FILE_LIMIT = 4 * 1024 * 1024
# A warning past this share of a limit.
SHARE = (3, 4)

# A test's: the walk upward stops below this directory, so that a file of
# the machine's own, above the system's temporary directory, is not taken
# for one above a scratch project. None for a run.
_CEILING: Path | None = None

_FENCE = re.compile(r"(`{3,}|~{3,})(.*)", re.S)
# What opens a block quote or a list item, with the one space that is its own.
_CONTAINER = re.compile(r"[ \t]*(>|(?:[-+*]|\d{1,9}[.)])(?=[ \t]|$)) ?")
_RUN = re.compile(r"`+")
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
# A heading or a rule: an indented line after one continues no paragraph.
_BREAK = re.compile(r"#|[-=_*\s]+\Z")
_IMPORT = re.compile(r"(?:^|(?<=\s))@((?:\\ |\S)+)")


# --- Reading ---------------------------------------------------------------------

def _size(path: Path) -> int | None:
    """The size of the file at ``path``, a link followed; None where there
    is no file. Nothing is opened."""
    try:
        found = os.stat(path)
    except (OSError, ValueError):
        return None
    return found.st_size if stat.S_ISREG(found.st_mode) else None


def _real(path: Path | str) -> str:
    return paths.fold(os.path.realpath(path))


def above(project: Path) -> list[Path]:
    """The project's real directory, then each directory above it."""
    real = Path(os.path.realpath(project))
    found = []
    for directory in (real, *real.parents):
        if _CEILING is not None and (paths.same(directory, _CEILING) or not paths.inside(directory, _CEILING)):
            break
        found.append(directory)
    return found


def claude_files(context: Any, project: Path) -> list[Path]:
    """Each of the three files at or above the project, nearest first. The
    user's own ``CLAUDE.md`` is not one of them: the ``CLAUDE.md`` that lies
    in the Claude Code home, whatever it leads to. A file somewhere else
    that is a link to it is one of them."""
    own = _real(context.homes.provider(homes.CLAUDE_CODE).home)
    found = []
    for directory in above(project):
        for parts in CLAUDE_FILES:
            file = directory.joinpath(*parts)
            if not fsio.is_file(file):
                continue
            if parts[-1] == CLAUDE_FILES[0][0] and _real(file.parent) == own:
                continue
            found.append(file)
    return found


def _width(text: str) -> int:
    """The indentation of ``text``, a tab taken as four columns."""
    spread = text.expandtabs(4)
    return len(spread) - len(spread.lstrip(" "))


def _split(line: str, runs_on: bool) -> tuple[str, str, bool, bool]:
    """A line as what leads it and what it says: the lead with each list
    marker as the columns it takes, the rest, whether the line is indented
    as code is, and whether a list marker was among the lead. ``runs_on``:
    the line before is a paragraph's, which an indented line continues."""
    lead, rest, listed = "", line, False
    code = _width(line) >= 4 and not runs_on
    while (mark := _CONTAINER.match(rest)) is not None:
        listed = listed or mark.group(1) != ">"
        lead += re.sub(r"[^>\s]", " ", mark.group())
        rest = rest[mark.end():]
        code = code or _width(rest) >= 4
    said = rest.lstrip()
    return lead + rest[:len(rest) - len(said)], said.rstrip(), code, listed


def _closes(said: str, mark: str, length: int) -> bool:
    found = _FENCE.match(said)
    return found is not None and found.group(1)[0] == mark and len(found.group(1)) >= length \
        and not found.group(2).strip()


def _blocks(text: str) -> list[list[str]]:
    """The lines of ``text`` that are no code, in blocks: a blank line and
    a stretch of code each end one. Left out: a fenced code block, at the
    margin or in a block quote or a list item, and a line indented by four
    columns or a tab that continues no paragraph.

    A fence that opens at the margin closes as Markdown has it. One that
    opens anywhere else closes only on a line led exactly as it was, with
    every line between led the same way; where a line is not, where the
    quote or the item ended cannot be told, and nothing from there to the
    end of the text is kept."""
    blocks: list[list[str]] = [[]]
    fence: tuple[str, int, str | None] | None = None
    runs_on = False
    for line in text.splitlines():
        lead, said, code, listed = _split(line, runs_on)
        if fence is not None:
            mark, length, led = fence
            if led is None:
                if lead.strip() == "" and not listed and _width(line) < 4 and _closes(said, mark, length):
                    fence = None
            elif not listed and lead == led and _closes(said, mark, length):
                fence = None
            elif not (line + " " * len(led)).startswith(led):
                break
            continue
        opened = _FENCE.match(said)
        if opened is not None and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            fence = (opened.group(1)[0], len(opened.group(1)), None if lead == "" and not listed else lead)
        elif said and not code:
            blocks[-1].append(said)
            runs_on = _BREAK.match(said) is None
            continue
        if blocks[-1]:
            blocks.append([])
        runs_on = False
    return blocks


def _outside_spans(line: str) -> tuple[str | None, bool]:
    """``line`` without its code spans, and whether every run of backticks
    in it has its pair in it. None where what is a span cannot be told: a
    run after a backslash, or after a ``<`` (a tag may hold a backtick)."""
    runs = list(_RUN.finditer(line))
    kept, start, at, whole = [], 0, 0, True
    while at < len(runs):
        run = runs[at]
        before = line[start:run.start()]
        escaped = (len(before) - len(before.rstrip("\\"))) % 2 == 1
        if "<" in before or (escaped and len(run.group()) > 1):
            return None, False
        close = None if escaped else next(
            (n for n in range(at + 1, len(runs)) if len(runs[n].group()) == len(run.group())), None,
        )
        if close is None:
            whole = whole and escaped
            at += 1
        else:
            kept.append(before)
            start, at = runs[close].end(), close + 1
    kept.append(line[start:])
    return " ".join(kept), whole


def _prose(blocks: list[list[str]]) -> str:
    """The blocks as text, code spans out. A span is looked for in one
    line. A block of several lines where a line has a backtick without its
    pair is left out whole: which lines the span takes cannot be told."""
    kept = []
    for block in blocks:
        lines = []
        for line in block:
            text, whole = _outside_spans(line)
            if text is None or not (whole or len(block) == 1):
                lines = []
                break
            lines.append(text)
        if lines:
            kept.append("\n".join(lines))
    return "\n\n".join(kept)


def _blank(found: re.Match[str]) -> str:
    return "\n\n" if "\n" in found.group() else " "


def imports(text: str) -> list[str]:
    """The path of each ``@path`` import in ``text``, as written. No
    import: what is in a fenced code block (in a block quote and in a list
    item too), in an indented code block, in a code span, or in an HTML
    comment, of one line or of several.

    The text is read twice, the comments taken out before the code and
    after it, since each can hide the other's marks; a path is an import
    only where both readings have it."""
    first = _IMPORT.findall(_prose(_blocks(_COMMENT.sub(_blank, text))))
    second = _IMPORT.findall(_COMMENT.sub(" ", _prose(_blocks(text))))
    return [found.replace("\\ ", " ") for found in first if found in second]


def _named(text: str, file: Path, home: Path) -> Path | None:
    """The file an import in ``file`` names."""
    try:
        if text == "~" or text.startswith(("~/", "~\\")):
            path = home / text[2:]
        elif os.path.isabs(text):
            path = Path(text)
        else:
            path = file.parent / text
        return Path(os.path.normpath(path))
    except (OSError, ValueError):
        return None


def imports_agents(file: Path, agents: Path, home: Path) -> bool:
    """Whether ``file`` imports ``agents``, or is a link to it. A file that
    cannot be read imports nothing; nor does one over the size Claude Code
    skips, which is not opened."""
    wanted = _real(agents)
    if _real(file) == wanted:
        return True
    size = _size(file)
    if size is None or size > CLAUDE_FILE_LIMIT:
        return False
    try:
        text = fsio.read_bytes(file).decode("utf-8-sig", errors="replace")
    except SetupError:
        return False
    for written in imports(text):
        named = _named(written, file, home)
        if named is not None and (paths.same(named, agents) or _real(named) == wanted):
            return True
    return False


def setting(path: Path) -> tuple[dict[str, str], str | None]:
    """The value the file gives the setting, by each plugin id that has
    one, and why the file could not be read. A value that is not one the
    setting takes is given as an empty string, never as it is. No other key
    of the file is kept."""
    try:
        data = codexsettings._bytes(path)
    except SetupError as exc:
        return {}, exc.lines[0].removeprefix(f"{path}: ")
    if data is None:
        return {}, None
    try:
        parsed = jsonkeys.parse(data)[1]
    except jsonkeys.Refusal as exc:
        # Only the kind of fault: the parser's own words may quote the file.
        return {}, "is not UTF-8 text" if "UTF-8" in str(exc) else "is not a JSON object that can be read"
    values = {}
    for ident in PLUGIN_IDS:
        value: Any = parsed
        for part in ("pluginConfigs", ident, "options", "instructionFiles"):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            values[ident] = value if isinstance(value, str) and value in SETTING_VALUES else ""
    return values, None


def _import_text(file: Path, agents: Path) -> str:
    """The import line that names ``agents`` from ``file``."""
    try:
        relative = os.path.relpath(agents, file.parent).replace(os.sep, "/")
    except ValueError:
        relative = AGENTS
    return "@" + relative.replace(" ", "\\ ")


def _over(size: int, limit: int) -> bool:
    return size * SHARE[1] > limit * SHARE[0]


# --- The check -------------------------------------------------------------------

def _claude(context: Any, project: Path) -> list[Any]:
    from . import doctor

    provider = context.homes.provider(homes.CLAUDE_CODE)
    if not provider.installed:
        return [doctor.info("claude-code: not installed; nothing to check")]
    agents = Path(os.path.realpath(project)) / AGENTS
    found = claude_files(context, project)
    findings = []
    skipped = []
    limit = f"the {CLAUDE_FILE_LIMIT:,} bytes (4 MiB) above which Claude Code skips an instruction file"
    for file in [*found, agents, provider.place(homes.INSTRUCTIONS).path]:
        size = _size(file)
        if size is None:
            continue
        if size > CLAUDE_FILE_LIMIT:
            if file is agents:
                continue
            skipped.append(file)
            findings.append(doctor.warning(
                f"claude-code: {file} is {size:,} bytes, over {limit}: it is skipped, and nothing in it is read, an "
                "import included; shorten it", file,
            ))
        elif _over(size, CLAUDE_FILE_LIMIT):
            findings.append(doctor.warning(
                f"claude-code: {file} is {size:,} bytes, over three quarters of {limit}; shorten it", file,
            ))
    size = _size(agents)
    if size is None:
        return findings + [doctor.info(
            f"claude-code: {agents}: no such file, so the project has no {AGENTS} for a session to load"
        )]
    if size > CLAUDE_FILE_LIMIT:
        return findings + [doctor.error(
            f"claude-code: {agents} is not loaded: it is {size:,} bytes, over {limit}. It is skipped whatever "
            "imports it and whatever the setting is; shorten it", agents,
        )]

    user_file = provider.home / SETTINGS_FILE
    by_id, fault = setting(user_file)
    values = list(by_id.values())
    if fault is not None:
        findings.append(doctor.warning(
            f"{user_file}: {fault}; whether {SETTING} is set there is not known, and it is taken as unset", user_file,
        ))
    disagree = len(set(values)) > 1
    if disagree:
        said = " and ".join(
            (f'"{by_id[ident]}"' if by_id[ident] else "a value the setting does not take") + f' under "{ident}"'
            for ident in PLUGIN_IDS
        )
        findings.append(doctor.warning(
            f"claude-code: instructionFiles is {said} in {user_file}: the two ids disagree. Claude Code before "
            f"2.1.285 reads \"{PLUGIN_ID}\" alone, and which of the two a later one follows is not known, so the "
            "setting is not counted as a remedy; give both the same value, or remove one", user_file,
        ))
    usable = [file for file in found if file not in skipped]
    importing = [file for file in usable if imports_agents(file, agents, context.homes.home)]
    listed = ", ".join(str(file) for file in found)

    if MANAGED_ONLY in values:
        findings.append(doctor.warning(
            f"claude-code: {SETTING} is \"{MANAGED_ONLY}\" in {user_file}: Claude Code then loads only the "
            f"organization's managed instructions, and {agents} is not loaded, import or not", user_file,
        ))
    elif importing:
        findings.append(doctor.fine(f"claude-code: {agents} is loaded through the import in {importing[0]}"))
    elif BOTH in values and not disagree and PLUGIN_ID in by_id:
        findings.append(doctor.fine(
            f"claude-code: {agents} is loaded beside the CLAUDE.md files: {SETTING} is \"{BOTH}\" in {user_file}"
        ))
    elif BOTH in values and not disagree:
        findings.append(doctor.warning(
            f"claude-code: {agents} is loaded beside the CLAUDE.md files on Claude Code 2.1.285 or later only: "
            f"instructionFiles is \"{BOTH}\" in {user_file} under \"{PLUGIN_ID_NEW}\" alone, and Claude Code "
            f"before 2.1.285 ignores that id (this tool supports it from {EVERY_SESSION_FROM}). Set it under "
            f"\"{PLUGIN_ID}\", which every version reads", user_file,
        ))
    elif found:
        ignored = [
            str(project.joinpath(*parts)) for parts in PROJECT_SETTINGS
            if BOTH in setting(project.joinpath(*parts))[0].values()
        ]
        line = f"`{_import_text((usable or found)[0], agents)}`"
        findings.append(doctor.error(
            f"claude-code: {agents} is not loaded: at or above the project there is {listed}, so Claude Code reads "
            f"the CLAUDE.md files in place of {AGENTS}, and neither remedy is in place. "
            + (f"Add the line {line} to {usable[0]} (an import, its path relative to that file)" if usable else
               f"Each of them is over the size Claude Code skips, so an import in one is not read: shorten "
               f"{found[0]} and add the line {line} to it (an import, its path relative to that file)")
            + f", or set {SETTING} to \"{BOTH}\" in {user_file}"
            + (f". The setting in {', '.join(ignored)} does nothing: Claude Code ignores it in a project's "
               "settings files" if ignored else ""),
            agents,
        ))
    elif CLAUDE_ONLY in values:
        findings.append(doctor.warning(
            f"claude-code: {SETTING} is \"{CLAUDE_ONLY}\" in {user_file}: Claude Code then reads CLAUDE.md files "
            f"only, and no CLAUDE.md at or above the project imports {agents}, so it is not loaded", user_file,
        ))
    else:
        findings.append(doctor.fine(
            f"claude-code: no CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md at or above the project, so Claude "
            f"Code reads {agents} directly (from {DIRECT_FROM}; in every kind of session from {EVERY_SESSION_FROM})"
        ))
    return findings


def _first(directory: Path) -> tuple[Path, int] | None:
    """The file Codex takes from a directory: the first of the override and
    ``AGENTS.md`` that is not empty."""
    for name in (OVERRIDE, AGENTS):
        size = _size(directory / name)
        if size:
            return directory / name, size
    return None


def _codex(context: Any, project: Path) -> list[Any]:
    from . import doctor

    provider = context.homes.provider(homes.CODEX)
    if not provider.installed:
        return [doctor.info("codex: not installed; nothing to check")]
    findings = []
    override = project / OVERRIDE
    size = _size(override)
    if size:
        findings.append(doctor.warning(
            f"codex: {override}: Codex takes one instruction file from a directory, and this one replaces the "
            f"{AGENTS} beside it: the project's {AGENTS}, and the lesson index in it, is not loaded on Codex while "
            "the file is there", override,
        ))
    elif size == 0:
        findings.append(doctor.info(
            f"codex: {override} is empty: Codex takes the first of the two files that is not empty, so the "
            f"{AGENTS} beside it is the one loaded. Once the file holds anything it replaces {AGENTS}"
        ))
    else:
        # No file: nothing there, a directory, a link to nowhere. Only what
        # cannot be looked at is said.
        try:
            fsio.look(override)
        except SetupError as exc:
            findings.append(doctor.warning(
                f"codex: {exc.lines[0]}; whether it replaces the {AGENTS} beside it is not known", override,
            ))

    limit, source = CODEX_DEFAULT_LIMIT, f"Codex's default of 32 KiB; {doctor.DOC_BYTES_KEY} is unset"
    read = doctor.codex_settings(context)
    if read is not None and read.fault is not None:
        source = f"Codex's default of 32 KiB; {read.path} cannot be read for {doctor.DOC_BYTES_KEY}"
    elif read is not None and read.values[doctor.DOC_BYTES_KEY] is not doctor.UNSET:
        value = read.values[doctor.DOC_BYTES_KEY]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            findings.append(doctor.warning(
                f"codex: {doctor.DOC_BYTES_KEY} in {read.path} is not a number of bytes; the sizes are measured "
                f"against the default of {CODEX_DEFAULT_LIMIT:,}", doctor.DOC_BYTES_KEY,
            ))
        elif value == 0:
            return findings + [doctor.warning(
                f"codex: {doctor.DOC_BYTES_KEY} = 0 in {read.path}: that leaves no room for any instruction file, "
                f"so no {AGENTS} is loaded on Codex", doctor.DOC_BYTES_KEY,
            )]
        else:
            limit, source = value, f"{doctor.DOC_BYTES_KEY} in {read.path}"

    loaded = [one for one in (_first(provider.home), _first(project)) if one is not None]
    total = sum(size for _, size in loaded)
    sizes = ", ".join(f"{file} {size:,}" for file, size in loaded)
    if total >= limit:
        findings.append(doctor.warning(
            f"codex: the instruction files Codex loads here are {total:,} bytes together, at or over the limit of "
            f"{limit:,} ({source}): {sizes}. Codex stops adding files once their combined size reaches the limit, "
            "so the end of them is not loaded; shorten them", project / AGENTS,
        ))
    elif _over(total, limit):
        findings.append(doctor.warning(
            f"codex: the instruction files Codex loads here are {total:,} bytes together, over three quarters of "
            f"the limit of {limit:,} ({source}): {sizes}. Codex stops adding files once their combined size "
            "reaches the limit; shorten them before it does", project / AGENTS,
        ))
    else:
        findings.append(doctor.fine(
            f"codex: the instruction files Codex loads here are {total:,} bytes together, of a limit of {limit:,} "
            f"({source})"
        ))
    return findings


def check(context: Any) -> list[Any]:
    """The check ``instruction-files`` of ``doctor``; see the module."""
    from . import doctor

    project = context.homes.project
    if project is None:
        return [doctor.info(
            f"no project was named: `doctor --project DIR` checks that both providers load DIR/{AGENTS}"
        )]
    return _claude(context, project) + _codex(context, project)
