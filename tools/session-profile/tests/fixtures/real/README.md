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
