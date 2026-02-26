# OpenClaw Skills Reference

OpenClaw agents have built-in capabilities (tools/functions) that do not require installing extra skills. Community skills (e.g. reddit-readonly) are documented in their own guides in this repo.

This page is a quick reference for what the agent can do. For full API and gateway details, see [OpenClaw documentation](https://docs.openclaw.ai/).

## Agents and sessions

| Function | Description |
|----------|-------------|
| **agents_list** | List agent IDs. |
| **sessions_list** | List sessions. |
| **sessions_history** | Fetch message history for a session. |
| **session_status** | Show session status. |

## Execution

| Function | Description |
|----------|-------------|
| **exec** | Run shell commands. |
| **process** | Manage running exec sessions (e.g. kill, steer). |

## Browser and Canvas

| Function | Description |
|----------|-------------|
| **browser** | Control the browser. |
| **canvas** | Present and evaluate Canvas content. |

## Messaging and subagents

| Function | Description |
|----------|-------------|
| **message** | Send and manage messages. |
| **sessions_send** | Send messages to other sessions. |
| **sessions_spawn** | Spawn sub-agents. |
| **subagents** | List, kill, or steer spawned sub-agents. |

## Memory

| Function | Description |
|----------|-------------|
| **memory_search** | Semantic search over memory (markdown). |
| **memory_get** | Read specific memory file or line range. |

## Web

| Function | Description |
|----------|-------------|
| **web_search** | Search the web. |
| **web_fetch** | Fetch and extract content from a URL. |

## Nodes and TTS

| Function | Description |
|----------|-------------|
| **nodes** | Discover and control paired nodes. |
| **tts** | Convert text to speech. |

## Related docs in this repo

- [macOS app setup and troubleshooting](openclaw-macos-app-setup.md) — gateway, agent key, deep links
- [OpenAlgo skill](openclaw-openalgo-skill.md) — trade and query via OpenAlgo API from the agent
- [Semantic memory search (memsearch)](openclaw-semantic-memory-memsearch.md)
- [Dynamic dashboard with sub-agents](openclaw-dynamic-dashboard-subagents.md)
- [Daily Reddit digest](openclaw-daily-reddit-digest.md)
