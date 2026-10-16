"""A provider's program for the tests of ``discovery``: a stub that answers
each command the check starts, and says what it was started with.

It is ``provider_stub.StubProgram`` with a script of its own. The script
picks its answer by what is among its arguments:

    version        ``--version``
    app-server     ``app-server``: it reads requests from standard input,
                   answers ``initialize`` itself, prints the answer's
                   ``stdout`` when ``skills/list`` comes, and ends when its
                   input does. With an exit code that is not 0 it reads
                   nothing: it prints and fails, as a server that cannot
                   start
    exec           ``exec``           (the Codex session probe)
    print          ``-p``             (the Claude Code session probe)
    profile        ``--profile``
    prompt-input   ``prompt-input``
    bundled, live  as ``provider_stub`` has them

An answer may also have ``hold``: seconds the stub stays running after it
printed, as a session does, and ``tail``, which it prints after that.

``calls()`` gives the argument lists as before; ``starts()`` gives each
start whole: ``argv``, ``mode``, ``cwd`` and the variables of ``ENVIRON``
as the stub saw them. ``requests()`` gives what the app server was sent.
"""
from __future__ import annotations

import json
from pathlib import Path

import provider_stub

APP_SERVER = "app-server"
EXEC = "exec"
PRINT = "print"
PROFILE = "profile"
PROMPT_INPUT = "prompt-input"
MODES = (APP_SERVER, EXEC, PRINT, PROFILE, PROMPT_INPUT)
SESSION_MODES = (EXEC, PRINT)

ENVIRON = ("HOME", "USERPROFILE", "CODEX_HOME", "CLAUDE_CONFIG_DIR")

_STUB = r'''import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "answers.json"), encoding="utf-8") as handle:
    answers = json.load(handle)
arguments = sys.argv[1:]
if "--version" in arguments:
    mode = "version"
elif "app-server" in arguments:
    mode = "app-server"
elif "exec" in arguments:
    mode = "exec"
elif "-p" in arguments:
    mode = "print"
elif "--profile" in arguments:
    mode = "profile"
elif "prompt-input" in arguments:
    mode = "prompt-input"
elif "--bundled" in arguments:
    mode = "bundled"
else:
    mode = "live"
answer = {"stdout": "", "stderr": "", "code": 0, "sleep": 0, "hold": 0, "tail": ""}
answer.update(answers.get(mode, {}))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "argv": arguments, "mode": mode, "cwd": os.getcwd(), "mark": os.environ.get("WFSETUP_TEST_MARK"),
        "environ": {name: os.environ.get(name) for name in ("HOME", "USERPROFILE", "CODEX_HOME", "CLAUDE_CONFIG_DIR")},
    }) + "\n")


def say(text):
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


time.sleep(answer["sleep"])
if mode == "app-server" and answer["code"] == 0:
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        with open(os.path.join(here, "requests.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(request) + "\n")
        if request.get("method") == "initialize":
            say(json.dumps({"id": request.get("id"), "result": {}}) + "\n")
        elif request.get("method") == "skills/list":
            say(answer["stdout"])
else:
    say(answer["stdout"])
time.sleep(answer["hold"])
say(answer["tail"])
sys.stderr.write(answer["stderr"])
sys.exit(answer["code"])
'''


class DiscoveryStub(provider_stub.StubProgram):
    def __init__(self, directory: Path, name: str = "codex") -> None:
        super().__init__(directory, name)
        self.script.write_text(_STUB, encoding="utf-8", newline="\n")

    def answer(self, mode: str, stdout: str = "", *, code: int = 0, stderr: str = "", sleep: float = 0,
               hold: float = 0, tail: str = "") -> None:
        self._answers[mode] = {"stdout": stdout, "stderr": stderr, "code": code, "sleep": sleep, "hold": hold,
                               "tail": tail}
        self._save()

    def starts(self) -> list[dict]:
        return self._calls()

    def modes(self) -> list[str]:
        return [call["mode"] for call in self._calls()]

    def requests(self) -> list[dict]:
        log = self.bin / "requests.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
