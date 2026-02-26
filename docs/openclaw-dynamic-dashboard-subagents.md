# OpenClaw: Dynamic Dashboard with Sub-agent Spawning

Static dashboards show stale data and require constant manual updates. This workflow creates a **live dashboard** that spawns sub-agents to fetch and process data in parallel, so you get real-time visibility across multiple data sources without building a custom frontend or hitting API rate limits.

## Pain point

Building a custom dashboard takes weeks. By the time it's done, requirements have changed. Polling multiple APIs sequentially is slow and hits rate limits. You need insight now, not after a weekend of coding.

## What it does

- **Monitors multiple data sources simultaneously** (APIs, databases, GitHub, social media)
- **Spawns sub-agents for each data source** to avoid blocking and distribute API load
- **Aggregates results** into a unified dashboard (text, HTML, or Canvas)
- **Updates every N minutes** with fresh data (cron schedule)
- **Sends alerts** when metrics cross thresholds
- **Stores historical metrics** in a database for trends and visualization

You define what you want to monitor conversationally: e.g. "Track GitHub stars, Twitter mentions, Polymarket volume, and system health." OpenClaw spawns sub-agents to fetch each source in parallel, aggregates the results, and delivers a formatted dashboard to Discord or as an HTML file.

Example dashboard sections:

- **GitHub**: stars, forks, open issues, recent commits
- **Social Media**: Twitter mentions, Reddit discussions, Discord activity
- **Markets**: Polymarket volume, prediction trends
- **System Health**: CPU, memory, disk usage, service status

## Skills needed

- **Sub-agent spawning** for parallel execution ([OpenClaw subagents](https://docs.openclaw.ai/subagents))
- **github** (gh CLI) for GitHub metrics
- **bird** (Twitter) or equivalent for social data
- **web_search** or **web_fetch** for external APIs
- **postgres** (or another DB) for storing historical metrics
- **Discord** or **Canvas** for rendering the dashboard
- **Cron jobs** for scheduled updates

## How to set it up

### 1. Set up a metrics database

Create tables for metrics and alerts (PostgreSQL example):

```sql
CREATE TABLE metrics (
  id SERIAL PRIMARY KEY,
  source TEXT,        -- e.g., "github", "twitter", "polymarket"
  metric_name TEXT,
  metric_value NUMERIC,
  timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alerts (
  id SERIAL PRIMARY KEY,
  source TEXT,
  condition TEXT,
  threshold NUMERIC,
  last_triggered TIMESTAMPTZ
);
```

Use the appropriate OpenClaw skill or tool to run DDL and to insert/query from the agent (e.g. `postgres` or your DB connector).

### 2. Create a Discord channel

Create a channel for dashboard updates (e.g. `#dashboard`). Configure OpenClaw to post to Discord (channel webhook or bot) so the agent can send the formatted dashboard there.

### 3. Prompt OpenClaw as dashboard manager

Give OpenClaw a system or long-lived instruction like the following. Adjust data sources and thresholds to your needs.

```text
You are my dynamic dashboard manager. Every 15 minutes, run a cron job to:

1. Spawn sub-agents in parallel to fetch data from:
   - GitHub: stars, forks, open issues, commits (past 24h)
   - Twitter: mentions of "@username", sentiment analysis
   - Polymarket: volume for tracked markets
   - System: CPU, memory, disk usage via shell commands

2. Each sub-agent writes results to the metrics database.

3. Aggregate all results and format a dashboard:

📊 **Dashboard Update** — [timestamp]

**GitHub**
- ⭐ Stars: [count] (+[change])
- 🍴 Forks: [count]
- 🐛 Open Issues: [count]
- 💻 Commits (24h): [count]

**Social Media**
- 🐦 Twitter Mentions: [count]
- 📈 Sentiment: [positive/negative/neutral]

**Markets**
- 📊 Polymarket Volume: $[amount]
- 🔥 Trending: [market names]

**System Health**
- 💻 CPU: [usage]%
- 🧠 Memory: [usage]%
- 💾 Disk: [usage]%

4. Post to Discord #dashboard.

5. Check alert conditions:
   - If GitHub stars change > 50 in 1 hour → ping me
   - If system CPU > 90% → alert
   - If negative sentiment spike on Twitter → notify

Store all metrics in the database for historical analysis.
```

### 4. Optional: Canvas for HTML dashboard

Use OpenClaw Canvas to render an HTML dashboard with charts and graphs. The agent can write HTML (or use a chart library) and serve it via Canvas so you get a visual, updatable dashboard.

### 5. Query historical data

Ask OpenClaw in natural language, e.g.:

- "Show me GitHub star growth over the past 30 days."
- "When did CPU last go above 90%?"
- "What was Polymarket volume yesterday?"

The agent queries the metrics table and can summarize or chart the results.

## Related links

- [Parallel Processing with Sub-agents](https://docs.openclaw.ai/subagents) — OpenClaw subagent docs
- [Dashboard Design Principles](https://www.nngroup.com/articles/dashboard-design/) — Nielsen Norman Group
