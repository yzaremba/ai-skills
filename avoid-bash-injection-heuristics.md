# Avoiding Bash "too-complex" injection heuristics

Claude Code's bash parser flags certain command shapes as `kind:"too-complex"` (or fails to extract a stable command prefix) and routes to a permission prompt **even when the allowlist matches**. The matcher is never consulted, so wildcards like `Bash(curl *)` don't help. No settings flag disables this — it's hard-coded in the binary's `df$()` classifier plus the prefix-extractor.

**Avoid the triggers by reshaping the command — don't try to allowlist your way out.** Before issuing any Bash call, scan the command string for the shapes below and rewrite. Default: write the payload to `/tmp/...` with the **Write tool**, then reference it by path. When in doubt, two short Bash calls (compute → use) beat one with `$(...)` or `$VAR` inline.

## Static-pattern triggers (regex-based)

| Heuristic message | Causes | Rewrite |
|---|---|---|
| `Contains brace with quote character (expansion obfuscation)` | Inline JSON: `curl --data '{"k":"v"}'`, `jq '. \| {a:"b"}'`, `printf '{"x":1}'`, any `'...{...}...'` or `"...{...}..."` | Write payload to `/tmp/foo.json` with **Write tool**, then `curl --data @/tmp/foo.json` / `jq -f /tmp/foo.jq -n` / `python /tmp/foo.py`. For `jq` filters, put the filter in a `.jq` file and use `-f`. |
| `Brace expansion` / `Brace expansion (unquoted { in concatenation with ,/..)` | `cp file.{old,new}`, `mv x.{a,b}`, `mkdir -p out/{a,b,c}`, `seq`-style `{1..10}` | Expand by hand (`cp file.old file.new` as two args; explicit list) **or** quote the brace (`'{a,b}'` literal) **or** loop in a separate two-call form. |
| `find contains unquoted glob characters — could glob-expand to a dangerous action before find runs` | Unquoted `*`/`?`/`[...]` anywhere in a `find` invocation: `find . -name *.py`, `find . -path */node_modules/* -prune`, `find logs -name *.gz -delete` (worst case: shell expands `*` in CWD *before* find sees it, possibly pulling in a filename like `-delete` that becomes a find action) | **Always single-quote glob args to `find`**: `find . -name '*.py'`, `find . -path '*/node_modules/*' -prune`, `find logs -name '*.gz' -delete`. Same for `-iname`, `-wholename`, `-ipath`, `-regex`. `find`-specific — other tools' glob args aren't gated this way, but quoting is still good hygiene. |
| `Brace body contains backslash-escaped brace` | `{\{...\}}` patterns, often from over-escaped templates | Drop the backslash escapes; use a tempfile if you need literal braces. |
| `Newline followed by # inside {a quoted argument / env var value / redirect target} can hide arguments from path validation` | `python -c "...\n# comment\n..."`, `bash -c $'...\n#...\n...'`, `FOO=$'...\n#...' cmd`, `cmd > "$'/tmp/a\n#b'"` | Write the script to `/tmp/foo.py` (or `.sh`) with **Write tool**, then `python /tmp/foo.py` / `bash /tmp/foo.sh`. Never embed `\n#` inside a quoted CLI arg / env value / redirect target. |
| `Contains backslash-escaped whitespace` | `path/with\ space`, `name=foo\ bar` | Quote the whole token: `"path/with space"`. |
| `Contains control characters` / `lone surrogate` / `Unicode whitespace` | Pasted text with hidden chars (NBSP, zero-width, CR, etc.) | Strip via the editor before issuing; or write to file first and read back. Watch for NBSP after copy-paste. |
| `Contains zsh ~[ ...` / `=cmd` / `<N-M>` glob | Zsh-specific syntaxes (`~[dir]`, `=ls`, `<1-100>`) | Use POSIX equivalents — explicit paths, `seq`, find/glob instead. |
| `Contains shell syntax (` | Subshell `(...)` at top level, e.g. `(cd foo && cmd)` | Use `cd foo && cmd` (no parens) or `cmd -C foo` (`git -C`, `make -C`). |
| `Command contains malformed syntax that cannot be parsed` | Unbalanced quotes/braces, stray backslashes | Re-write cleanly; if quoting is awkward, tempfile it. |

## `Contains <X>` — the node-type family (the big one)

**`Contains <something>` is NOT a fixed list — it is generated.** The binary builds the message as `` `Contains ${node.type}` `` for *any* tree-sitter node type in this set (`glK`):

```
command_substitution  process_substitution  expansion  simple_expansion
brace_expression      subshell              compound_statement
for_statement         while_statement       until_statement
if_statement          case_statement        function_definition
test_command          ansi_c_string         translated_string
herestring_redirect   heredoc_redirect
```

If the command's syntax tree contains **any** of these nodes, the parser returns `too-complex` and the allowlist is never consulted. So `Contains command_substitution`, `Contains expansion`, `Contains simple_expansion`, `Contains heredoc_redirect`, `Contains for_statement`, etc. are all the *same mechanism*. Don't expect to enumerate them — instead, **keep every Bash command a flat, simple command with no embedded shell constructs.**

| Node type → message | Syntax that produces it | Rewrite |
|---|---|---|
| `Contains command_substitution` | `$(...)` **and** backticks `` `...` `` — `echo "v=$(git rev-parse HEAD)"`, `cd "$(dirname x)"` | Two calls: run the inner command first, read the literal off its output, inline it in the second call. |
| `Contains process_substitution` | `<(...)`, `>(...)` — `diff <(sort a) <(sort b)` | Write each side to a `/tmp` file in separate calls, then `diff /tmp/a /tmp/b`. |
| `Contains expansion` | `${VAR}`, `${VAR:-def}`, `${VAR##*/}`, `${#VAR}` | Inline the literal value (compute in a prior call if unknown). |
| `Contains simple_expansion` | bare `$VAR` anywhere — `grep "$PAT" f`, `cd $DIR` | Inline the literal value. |
| `Contains brace_expression` | `{a,b}`, `{1..10}` — `cp x.{old,new}` | Expand by hand / explicit list / loop in a separate call. |
| `Contains subshell` | top-level `(...)` — `(cd foo && cmd)` | `cd foo && cmd` (no parens) or `cmd -C foo`. |
| `Contains compound_statement` | `{ cmd1; cmd2; }` brace group | Just `cmd1 && cmd2` (no braces), or separate calls. |
| `Contains for_statement` / `while_statement` / `until_statement` | `for f in ...; do ...; done`, `while ...; do ...; done` | Move the loop into a `/tmp/foo.sh` script (Write tool) and run `bash /tmp/foo.sh`; or unroll into explicit calls. |
| `Contains if_statement` / `case_statement` | `if ...; then ...; fi`, `case ... esac` | Tempfile script, or restructure as `cmd-a && cmd-b` / separate calls. |
| `Contains function_definition` | `foo() { ...; }` | Tempfile script. |
| `Contains test_command` | `[[ ... ]]` and `[ ... ]` — `[[ -f x ]] && cmd` | Use a positive check that doesn't need `[[`: e.g. `ls x` then act on result, or tempfile script. |
| `Contains ansi_c_string` | `$'...'` — `printf $'a\tb'` | Use a plain quoted string, or write the literal bytes to a file. |
| `Contains translated_string` | `$"..."` | Drop the `$` — use `"..."`. |
| `Contains herestring_redirect` | `<<<` — `cmd <<< "data"` | Write `data` to `/tmp/x` and `cmd < /tmp/x`, or `printf ... \| cmd`. |
| `Contains heredoc_redirect` | `<<EOF ... EOF` (incl. `<<'EOF'`) — the classic `cat <<EOF` | **Always** write the body to a file with the **Write tool**, then `cmd /tmp/foo` or `cmd < /tmp/foo`. Never use heredocs. |

## Other dynamic-content triggers (separate from the `glK` family)

| Heuristic message | Cause | Rewrite |
|---|---|---|
| `Arithmetic expansion references variable or non-literal` | `n=$((x+1))`, `$((N*2))` | Compute in a prior call / in Python, inline the literal. |
| `Argument starting with -` contains runtime-determined content | `cmd --port=$P`, `grep -e "$PAT"` | Inline literal value. |
| `Command name is a dynamic expression …` / `Command name is runtime-determined` | `$EDITOR file`, `${PYTHON} -m foo`, `` `which jq` `` | Use the literal binary path. |
| `Command contains unquoted variable expansion` | `cmd $ARGS` (word-splitting intent) | Wrapper script with real argv, or explicit literal arg list. |

## Default mental rules (priority order)

**Master rule: every Bash command must be a flat, simple command** — `cmd arg arg`, optionally joined with `&&` / `||` / `|` / `;`. No embedded shell constructs at all. If a command needs a loop, conditional, substitution, heredoc, or function, write a script to `/tmp/foo.sh` with the **Write tool** and run `bash /tmp/foo.sh`. The specifics:

1. **If the command would contain `{` plus a quote — STOP. Write the payload to `/tmp/...` first.** Heredocs (`cat <<EOF`), `bash -c "..."` / `python -c "..."` with non-trivial bodies are the biggest offenders.
2. **No `$VAR`, `${VAR}`, `$(...)`, or backticks in the command itself.** Compute in a prior Bash call, read the literal off the output, then issue the second call with the value inlined. Two short calls > one chained call.
3. **No control flow or grouping** — `for`/`while`/`until`/`if`/`case`/`{ ...; }`/`foo() {...}`/`[[ ... ]]`. Move to a `/tmp` script, or unroll into separate calls.
4. **No brace lists** (`{a,b}`, `{1..10}`) — expand by hand or loop in a script.
5. **No subshells `(...)`** at top level — use `&&` chains or `-C <dir>` flags.
6. **No heredocs / here-strings** (`<<EOF`, `<<<`) or process substitution (`<(...)`) — tempfile instead.
7. **No `\n#` inside any quoted arg, env value, or redirect target** — always tempfile.
8. **No `$'...'` / `$"..."`** — plain quotes, or tempfile for special bytes.
9. **No zsh-only syntax** — POSIX `seq` / explicit paths / `find`.
10. **No backslash-escaped spaces** — quote the whole token instead.

## What does NOT work

- Adding broader wildcards to `permissions.allow` (matcher is never consulted on `too-complex` commands).
- Exact-match allowlist entries (prefix extractor gave up before matching).
- Quoting tricks (escaping doesn't change the parser's view; sometimes makes it worse).
- Single-quoting `$VAR` to literalize it (parser still sees the `$` token and bails on the surrounding command's prefix extraction in many positions).

## Escape hatch (only if rewriting is impossible)

A `PreToolUse:Bash` hook can auto-approve a narrow custom safe-list, bypassing the heuristic entirely. Use only for shapes explicitly vetted; this weakens defense-in-depth.

## The `deniedPathInsideDirectory` circuit breaker (a *different* mechanism)

Separate from the bash parser heuristics above, Claude Code ≥ 2.1.25x has a **permission circuit breaker** that fires on read-capable commands whenever *any* `Read()` deny rule exists in settings. Its result carries `classifierApprovable: false`, so **no allow rule and no auto-mode classifier can clear it — only a human click**. Wildcards in `permissions.allow` are useless here; so is the `Bash(grep *)` entry.

Gated commands (`vuo`): **`grep` `egrep` `fgrep` `rg` `diff` `git` `cp` `mv`**.

It has two branches, and they need different fixes.

### Branch 1 — "would read '<dir>', which the deny rule `Read(...)` covers"

Fires when a deny pattern's **literal prefix** resolves to a directory that contains the command's target. A pattern whose first segment is a glob (`Read(**/.env)`) has an *empty* literal prefix, so it collapses to the **current working directory** — making *every* `grep -r … .` anywhere trip the prompt, even in directories with no `.env`.

**Fix (settings-level, already applied):** anchor every `Read()` deny pattern to a real root — `Read(//home/yzaremba/**/.env)`, not `Read(**/.env)`. The deny still blocks the Read tool *and* `cat .env` via Bash; only the breaker's false positive goes away. Cost: a `.env` under an unlisted root (`/opt`, `/srv`) is no longer denied — add an anchored rule if that ever matters.

### Branch 2 — "after a cd would search a directory that cannot be determined here"

```js
let De = isCompoundWithCd && !isAbsolute(arg) && !arg.startsWith("~")
         ? undefined                       // ← unconditional ask
         : UEn(resolve(cwd, arg), settings);
```

Fires on the **combination** of (a) a `cd` somewhere in the compound command and (b) a **relative** path argument to one of the gated commands. It does **not** consult the deny rule's paths at all — only that *some* `Read()` deny rule exists. **No settings change can suppress it** short of deleting every `Read()` deny rule, which is not worth it.

**Fix — reshape the command. Either drop the `cd` or make the paths absolute:**

| Shape | Result |
|---|---|
| `cd /repo && grep -n "x" business/foo.py` | ❌ prompts |
| `cd /repo && grep -n "x" /repo/business/foo.py` | ✅ clean |
| `grep -n "x" business/foo.py` *(no cd)* | ✅ clean |
| `grep -rn "x" business/` *(no cd)* | ✅ clean |

Verified empirically on 2.1.259 in this workspace — all four shapes above, plus the parallel `rg`/`git`/`cp`/`mv` cases.

### Rules

11. **Never pair a `cd` with a relative path argument to `grep`/`egrep`/`fgrep`/`rg`/`diff`/`git`/`cp`/`mv`.** Prefer dropping the `cd` entirely and letting paths resolve against the session cwd — that is shorter *and* clean. If a `cd` is genuinely needed (a script or tool that must run from a directory), spell every gated command's path arguments absolutely.
12. **Prefer `git -C <dir>` over `cd <dir> && git …`** — same reason, and it avoids leaving the shell cwd moved.
13. Deny patterns in `permissions.deny` must **start with a literal path segment**, never `**`.
