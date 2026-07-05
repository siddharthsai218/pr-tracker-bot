# PR Tracker Bot 🤖

A personal Discord bot that automates GitHub PR tracking and daily standups, hosted on Railway.

## Features

- **PR Tracker** — polls GitHub every 5 minutes, auto-posts updates to a Discord channel when a PR is opened, merged, closed, reviewed, commented on, or hits a merge conflict. Also posts a daily morning summary of open PRs.
  - `/prs` — show all open PRs
  - `/merged` — show recently merged PRs
  - `/sync` — manually trigger a PR check

- **Standup** — DMs a 3-question daily standup (yesterday / today / blockers) and posts the summary to a log channel.
  - `/standup` — trigger manually
  - `/history` — view last 7 standups
  - `/streak` — check your standup streak
  - `/skip` — skip today's standup

- **Reminder** — (cog in progress)

## Tech Stack

- Python — [`discord.py`](https://discordpy.readthedocs.io/)
- GitHub REST/Search API via `httpx`
- Local JSON for caching PR state and standup history
- Hosted on [Railway](https://railway.app)

## Setup

1. Clone the repo
   \`\`\`bash
   git clone https://github.com/siddharthsai218/pr-tracker-bot.git
   cd YOUR_REPO_NAME
   \`\`\`

2. Install dependencies
   \`\`\`bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   \`\`\`

3. Create a `.env` file (see `.env.example`) with your Discord bot token, GitHub PAT, and channel/user IDs.

4. Run the bot
   \`\`\`bash
   python bot.py
   \`\`\`

## Note on data persistence

PR cache and standup history are stored in local JSON files. If deployed on a platform with an ephemeral filesystem, this data won't persist across restarts/redeploys — worth migrating to a proper database (e.g. Supabase/SQLite with a persistent volume) for long-term use.
