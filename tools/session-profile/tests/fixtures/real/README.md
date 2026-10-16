# Fixtures cut from real provider records

Unlike `../handwritten`, these come from a record a provider wrote, so they
show that the reader looks where the provider actually puts things.

Every value kept is a short ASCII identifier token; anything else in a field
is dropped, not kept. The tests check that of every value in every fixture
file, and of every directory and file name.

## `claude-code-2.1.289/`

- Provider: Claude Code 2.1.289.
- Cut on 2026-10-05 from one session started with `claude --agent manager`,
  in which the main agent dispatched three subagents (`product-manager`,
  `coder`, `coder-hard`).
- Shaped as a config home: point `CLAUDE_CONFIG_DIR` at it.
- It holds no transcript text. Each entry is reduced to the fields
  `session_profile.py` reads: `type`, `version`, `message.id`,
  `message.model`, `effort`, `perTurnEffort`, `attributionAgent`,
  `agentSetting`, and `agentType` from each subagent's meta file. Message
  content, tool input and output, prompts, descriptions, working
  directories, timestamps and every path were dropped, and the project
  directory is renamed `-fixture-toy`.
- `message.id` is not the provider's id. The reader uses it only to count a
  response written as several entries once, so each distinct id is replaced
  by `m1`, `m2`, ... in order of first appearance in its file.
- The session id (the main transcript's name) and the subagent ids (in the
  `agent-<id>` file names) are the provider's: the reader finds the files
  by them.
- An entry whose model is `<synthetic>` (one Claude Code made up itself,
  for an API error) is dropped whole. The reader leaves such an entry out;
  kept without its model it would count as a response with no model. This
  session had none.
- Only the head of each transcript is kept: two `agent-setting` entries,
  one `user` entry and the first three responses per agent.

The fixture is exactly what the reducer writes from that session, and what
it writes from the fixture itself. To cut it again, or to cut another
session the same way:

    python reduce_claude_code.py <config>/projects/<project>/<session>.jsonl claude-code-2.1.289

## `codex-0.160.0/`

- Provider: Codex CLI 0.160.0.
- Cut on 2026-10-05 from one interactive session whose main thread ran the
  Manager's instructions. It spawned three role threads (`product_manager`,
  `coder`, `coder_hard`), and each Coder's request to commit was reviewed in
  a `guardian_review` thread, which is a child of that Coder's thread and
  not of the main one. The session had six threads. Five are here: the
  review of the `coder_hard` thread was left out, the other one shows the
  shape.
- Shaped as a Codex home: point `CODEX_HOME` at it. The file names are the
  provider's, because they carry the thread ids.
- It holds no transcript text. Of each rollout only the `session_meta`
  record and every `turn_context` record are kept, reduced to the fields
  `session_profile.py` reads: from `session_meta`, `id`,
  `parent_thread_id`, `agent_role`, `agent_path`, `agent_nickname`,
  `thread_source`, `cli_version`, and the copies of the parent id, role,
  path and nickname under `source.subagent.thread_spawn`; from
  `turn_context`, `model`, `effort`, and `collaboration_mode.settings.model`
  and `.reasoning_effort`. Messages, instructions, tool calls and output,
  working directories, sandbox and permission settings, git information,
  account ids and the timestamp of every record were dropped.
- The times are not all gone: a rollout's file name keeps the date and time
  its thread started (`rollout-2026-10-05T10-56-19-...`), and the day
  directories repeat the date. They stay because the name is the provider's
  and carries the thread id. Nothing inside a file holds a time.
- An `agent_path` such as `/root/coder_r1` is the provider's name for a
  thread in the tree of agents. It is not a path of the machine. The reader
  and the reducer take only that shape: `/root`, then up to eight segments
  of letters, digits, `_` and `-`. Anything else is treated as absent.
- What it shows about the record: a spawned thread has its role, path and
  nickname both at the top of the `session_meta` payload and under
  `source.subagent.thread_spawn`; the main thread's record names no role;
  a `guardian_review` thread has a parent id and nothing else.

This fixture is a snapshot. It was cut while the session was still open,
and the session went on afterwards: the main thread's rollout has more
turns now than the 17 the fixture holds and the tests pin. To cut it again
from the same rollouts therefore does not give these bytes. It gives the
same `session_meta` records and, for the main thread, a longer run of
`turn_context` records, and the pinned count of 17 would have to be
changed with it. What does hold, and is tested, is that reducing the
fixture itself gives the same bytes.

To cut another session the same way, or this one as it stands now, name
each rollout wanted and then the output directory:

    python reduce_codex.py <home>/sessions/<year>/<month>/<day>/rollout-<...>.jsonl [...] codex-0.160.0
