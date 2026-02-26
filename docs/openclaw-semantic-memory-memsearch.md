# OpenClaw + memsearch: Semantic Memory Search

OpenClaw's built-in memory system stores everything as markdown files. As memories grow over weeks and months, finding that one decision from last Tuesday becomes impossible—there is no search, just scrolling through files. This guide adds **vector-powered semantic search** on top of OpenClaw's existing markdown memory using [memsearch](https://github.com/zilliztech/memsearch), so you can find any past memory by meaning, not just keywords.

## Pain point

OpenClaw memory is stored as plain markdown under the agent workspace: **`MEMORY.md`** (long-term facts and decisions) and **`memory/YYYY-MM-DD.md`** (daily logs). That’s great for portability and human readability, but there is no search. As your memory grows, you either grep through files (keyword-only, misses semantic matches) or load entire files into context (wastes tokens). You need a way to ask “what did I decide about X?” and get the exact relevant chunk, regardless of phrasing.

## What memsearch adds

- **Semantic search**: Find by meaning (e.g. “what caching solution did we pick?” finds the relevant memory even if the word “caching” does not appear).
- **Hybrid search**: Dense vectors + BM25 full-text with RRF reranking for better results.
- **SHA-256 content hashing**: Unchanged files are never re-embedded—zero wasted API calls when you re-run index.
- **File watcher**: Auto-reindex when memory files change so the index stays up to date.
- **Flexible embeddings**: OpenAI, Google, Voyage, Ollama, or fully local (no API key needed).

Markdown remains the source of truth; the vector index is a derived cache. You can rebuild it anytime with `memsearch index`.

## OpenClaw memory paths

You must point memsearch at your **OpenClaw workspace** (the directory that contains the memory markdown files).

| Scenario | Path to index |
|----------|----------------|
| Default single-agent workspace | **`~/.openclaw/workspace`** (contains `MEMORY.md` and `memory/`) |
| Custom workspace | Whatever you set in `agents.defaults.workspace` in your `openclaw.json` |

If you use a custom workspace, index that path instead of `~/.openclaw/workspace`.

## Step-by-step setup

### 1. Install memsearch

Requires Python 3.10+ and pip (or uv).

```bash
pip install memsearch
```

For a **fully local** setup (no API key):

```bash
pip install "memsearch[local]"
```

Optional providers: `memsearch[google]`, `memsearch[voyage]`, `memsearch[ollama]`, `memsearch[all]`.

### 2. Configure memsearch

Run the interactive config wizard (writes to `~/.memsearch/config.toml`):

```bash
memsearch config init
```

For fully local embeddings:

```bash
memsearch config set embedding.provider local
```

### 3. Index your OpenClaw memory

```bash
memsearch index ~/.openclaw/workspace
```

Use your custom workspace path here if you have one. Re-run this command anytime to refresh the index; unchanged content is skipped via content hash.

### 4. Search by meaning

```bash
memsearch search "what caching solution did we pick?"
memsearch search "auth flow" --top-k 10 --json-output
```

### 5. Live sync (optional)

To auto-reindex whenever memory files change:

```bash
memsearch watch ~/.openclaw/workspace
```

Runs until you stop it (Ctrl+C). Use `--debounce-ms 3000` to reduce reindex frequency.

### 6. One-command index from this repo (optional)

If you use the script provided in this repo:

```bash
./scripts/openclaw-memsearch-index.sh
```

To run the watcher in the background:

```bash
./scripts/openclaw-memsearch-index.sh --watch
```

See the script for requirements (memsearch installed and configured first).

## Caveats

- **Markdown is the source of truth.** The vector index is a cache. Re-run `memsearch index` to rebuild; do not edit the vector DB directly.
- **OpenClaw’s built-in `memory_search`** is unchanged. memsearch is an alternative (e.g. for CLI use, Milvus backend, or hybrid+RRF). You can use both.
- **Milvus**: memsearch uses Milvus (Milvus Lite by default, no separate server). See [memsearch docs](https://zilliztech.github.io/memsearch/) for server or cloud backends.

## Links

- [memsearch GitHub](https://github.com/zilliztech/memsearch) — library and CLI
- [memsearch Documentation](https://zilliztech.github.io/memsearch/) — full CLI reference, Python API, configuration
- [OpenClaw Memory](https://docs.openclaw.ai/concepts/memory) — how OpenClaw stores memory
- [OpenClaw](https://github.com/openclaw/openclaw) — the memory architecture that inspired memsearch
- [Milvus](https://milvus.io/) — vector database backend used by memsearch
