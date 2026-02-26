# OpenClaw: Daily Reddit Digest

Run a daily digest to get the top performing posts from your favourite subreddits. OpenClaw uses a read-only Reddit skill to fetch and curate posts, learns your preferences over time via memory, and can run on a schedule (e.g. every day at 5pm).

## What to use it for

- **Browsing subreddits**: hot, new, or top posts
- **Searching posts** by topic
- **Pulling comment threads** for context
- **Building shortlists** of posts to manually review or reply to later

This workflow is **read-only**. No posting, voting, or commenting. The skill only fetches and displays content.

## Skill required

Install the **[reddit-readonly](https://clawhub.ai/buksan1950/reddit-readonly)** skill from ClawHub. It does not require Reddit auth. Install it in OpenClaw (e.g. from ClawHub or your OpenClaw skill install flow) before using the prompt below.

## How to set it up

After installing the skill, prompt your OpenClaw with the following (paste your list of subreddits where indicated):

```text
I want you to give me the top performing posts from the following subreddits.
<paste the list here>
Create a separate memory for the reddit processes, about the type of posts I like to see and every day ask me if I liked the list you provided. Save my preference as rules in the memory to use for a better digest curation. (e.g. do not include memes.)
Every day at 5pm, run this process and give me the digest.
```

- **Subreddit list**: Replace `<paste the list here>` with your subreddits (e.g. one per line or comma-separated).
- **Memory**: OpenClaw will create a separate memory for Reddit preferences. Each day it can ask whether you liked the list and save rules (e.g. "do not include memes") to improve future digests.
- **Schedule**: "Every day at 5pm" is handled by OpenClaw’s cron or reminder system. Ensure scheduling is enabled in your OpenClaw config so the daily job runs.

## Related links

- [reddit-readonly skill](https://clawhub.ai/buksan1950/reddit-readonly) — ClawHub skill page
- [OpenClaw Memory](https://docs.openclaw.ai/concepts/memory) — how memory and rules work
- [OpenClaw](https://github.com/openclaw/openclaw) — agent framework
