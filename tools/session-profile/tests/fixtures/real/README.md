# Fixtures cut from real provider records

Unlike `../handwritten`, these come from a record a provider wrote, so they
show that the reader looks where the provider actually puts things.

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
  directories and every path were dropped, and the project directory is
  renamed `-fixture-toy`.
- Only the head of each transcript is kept: two `agent-setting` entries,
  one `user` entry and the first three responses per agent.

To cut it again, or to cut another session the same way:

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
  account ids and timestamps were dropped.
- An `agent_path` such as `/root/coder_r1` is the provider's name for a
  thread in the tree of agents. It is not a path of the machine.
- What it shows about the record: a spawned thread has its role, path and
  nickname both at the top of the `session_meta` payload and under
  `source.subagent.thread_spawn`; the main thread's record names no role;
  a `guardian_review` thread has a parent id and nothing else.

To cut it again, or to cut another session the same way, name each rollout
wanted and then the output directory:

    python reduce_codex.py <home>/sessions/<year>/<month>/<day>/rollout-<...>.jsonl [...] codex-0.160.0
