"""Run scripts/check.py under an audit hook that records what it must never do.

Usage: python audit_runner.py CHECK_PY [arguments of check.py]

The hook records every attempt to start a process, load a library, open a
socket, or create, change or remove a file. If anything was recorded the
events are printed to stderr and the exit code is 97; otherwise it is the
exit code of check.py.
"""
import os
import sys

EXIT_CAUGHT = 97
FORBIDDEN = {
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
    "os.startfile", "os.startfile/2", "pty.spawn", "ctypes.dlopen", "_winapi.CreateProcess",
    "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.symlink", "os.link",
    "os.truncate", "os.utime", "os.putenv", "os.kill",
}
PREFIXES = ("socket.", "shutil.", "tempfile.", "urllib.", "http.", "ftplib.", "smtplib.", "winreg.")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
caught = []


def hook(event, args):
    if event in FORBIDDEN or event.startswith(PREFIXES):
        caught.append((event, repr(args)[:200]))
    elif event == "open":
        mode, flags = args[1], args[2]
        if isinstance(mode, str):
            writes = any(char in mode for char in "wax+")
        else:
            writes = bool(isinstance(flags, int) and flags & WRITE_FLAGS)
        if writes:
            caught.append((event, repr(args)[:200]))


def main():
    script = os.path.abspath(sys.argv[1])
    sys.path.insert(0, os.path.dirname(script))
    sys.addaudithook(hook)
    import check
    code = check.main(sys.argv[2:])
    sys.stdout.flush()
    if caught:
        for event, detail in caught:
            sys.stderr.write(f"caught: {event} {detail}\n")
        return EXIT_CAUGHT
    return code


if __name__ == "__main__":
    sys.exit(main())
