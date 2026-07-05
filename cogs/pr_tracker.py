import discord
from discord.ext import commands, tasks
from discord import app_commands
import httpx
import os
import json
from datetime import datetime, timezone

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
PR_TRACKER_CHANNEL_ID = int(os.getenv("PR_TRACKER_CHANNEL_ID"))

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

CACHE_FILE = "pr_cache.json"

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r") as f:
        return json.load(f)

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

async def github_get(url):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                return resp.json()
        return None
    except Exception as e:
        print(f"[PR Tracker] GitHub API error: {e}")
        return None

async def fetch_my_open_prs():
    data = await github_get(
        f"https://api.github.com/search/issues?q=is:pr+is:open+author:{GITHUB_USERNAME}&per_page=50&sort=updated"
    )
    return data.get("items", []) if data else []

async def fetch_my_all_prs():
    data = await github_get(
        f"https://api.github.com/search/issues?q=is:pr+author:{GITHUB_USERNAME}&per_page=50&sort=updated&order=desc"
    )
    return data.get("items", []) if data else []

async def get_pr_reviews(repo_full, pr_number):
    data = await github_get(f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/reviews")
    return data if data else []

async def get_pr_details(repo_full, pr_number):
    return await github_get(f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}")

async def get_pr_comments(repo_full, pr_number):
    data = await github_get(f"https://api.github.com/repos/{repo_full}/issues/{pr_number}/comments?per_page=50")
    return data if data else []

async def get_pr_review_comments(repo_full, pr_number):
    data = await github_get(f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/comments?per_page=50")
    return data if data else []

def get_repo_from_pr(pr):
    return pr["repository_url"].replace("https://api.github.com/repos/", "")

def make_embed(title, url, description, color, footer=None):
    embed = discord.Embed(title=title, url=url, description=description, color=color)
    if footer:
        embed.set_footer(text=footer)
    return embed


class PRTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_pr_updates.start()
        self.daily_summary.start()

    def cog_unload(self):
        self.check_pr_updates.cancel()
        self.daily_summary.cancel()

    # ─── Slash Commands ──────────────────────────────────────────

    @app_commands.command(name="prs", description="Show all your open PRs across GitHub")
    async def prs_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        prs = await fetch_my_open_prs()
        if not prs:
            await interaction.followup.send("✅ No open PRs right now!")
            return
        await interaction.followup.send(f"**{len(prs)} open PR(s) by {GITHUB_USERNAME}:**")
        for pr in prs:
            repo = get_repo_from_pr(pr)
            reviews = await get_pr_reviews(repo, pr["number"])
            meaningful = [r for r in reviews if r["state"] in ["APPROVED", "CHANGES_REQUESTED", "DISMISSED"]]
            status = meaningful[-1]["state"].lower() if meaningful else "awaiting review"
            labels = ", ".join([l["name"] for l in pr.get("labels", [])]) or "none"
            embed = discord.Embed(title=f"#{pr['number']} — {pr['title']}", url=pr["html_url"], color=discord.Color.blurple())
            embed.add_field(name="Repo", value=repo, inline=True)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Labels", value=labels, inline=True)
            embed.set_footer(text=f"Updated {pr['updated_at'][:10]}")
            await interaction.channel.send(embed=embed)

    @app_commands.command(name="merged", description="Show your recently merged PRs")
    async def merged_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await github_get(
            f"https://api.github.com/search/issues?q=is:pr+is:merged+author:{GITHUB_USERNAME}&per_page=50&sort=updated"
        )
        prs = data.get("items", []) if data else []
        if not prs:
            await interaction.followup.send("No merged PRs found recently.")
            return
        await interaction.followup.send(f"**{len(prs)} recently merged PR(s) by {GITHUB_USERNAME}:**")
        for pr in prs[:10]:
            repo = get_repo_from_pr(pr)
            labels = ", ".join([l["name"] for l in pr.get("labels", [])]) or "none"
            embed = discord.Embed(title=f"#{pr['number']} — {pr['title']}", url=pr["html_url"], color=discord.Color.green())
            embed.add_field(name="Repo", value=repo, inline=True)
            embed.add_field(name="Status", value="✅ merged", inline=True)
            embed.add_field(name="Labels", value=labels, inline=True)
            embed.set_footer(text=f"Updated {pr['updated_at'][:10]}")
            await interaction.channel.send(embed=embed)

    @app_commands.command(name="sync", description="Manually trigger a PR check right now")
    async def sync_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.check_pr_updates()
        prs = await fetch_my_open_prs()
        if not prs:
            await interaction.followup.send("✅ Sync done — no open PRs right now!")
            return
        await interaction.followup.send(f"**🔄 Sync complete — {len(prs)} open PR(s):**")
        for pr in prs:
            repo = get_repo_from_pr(pr)
            reviews = await get_pr_reviews(repo, pr["number"])
            meaningful = [r for r in reviews if r["state"] in ["APPROVED", "CHANGES_REQUESTED", "DISMISSED"]]
            status = meaningful[-1]["state"].lower() if meaningful else "awaiting review"
            labels = ", ".join([l["name"] for l in pr.get("labels", [])]) or "none"
            embed = discord.Embed(title=f"#{pr['number']} — {pr['title']}", url=pr["html_url"], color=discord.Color.blurple())
            embed.add_field(name="Repo", value=repo, inline=True)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Labels", value=labels, inline=True)
            embed.set_footer(text=f"Updated {pr['updated_at'][:10]}")
            await interaction.channel.send(embed=embed)

    # ─── Auto PR checker ─────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_pr_updates(self):
        try:
            channel = self.bot.get_channel(PR_TRACKER_CHANNEL_ID)
            if not channel:
                return
            cache = load_cache()
            prs = await fetch_my_all_prs()
            for pr in prs:
                pr_id = str(pr["id"])
                repo = get_repo_from_pr(pr)
                pr_number = pr["number"]
                pr_title = pr["title"]
                pr_url = pr["html_url"]
                details = await get_pr_details(repo, pr_number)
                reviews = await get_pr_reviews(repo, pr_number)
                comments = await get_pr_comments(repo, pr_number)
                review_comments = await get_pr_review_comments(repo, pr_number)
                review_state = "no reviews yet"
                if reviews:
                    meaningful = [r for r in reviews if r["state"] in ["APPROVED", "CHANGES_REQUESTED", "DISMISSED"]]
                    if meaningful:
                        review_state = meaningful[-1]["state"].lower()
                mergeable_state = details.get("mergeable_state", "") if details else ""
                total_comments = len(comments) + len(review_comments)
                all_comments = sorted(comments + review_comments, key=lambda x: x["created_at"], reverse=True)
                latest_comment = all_comments[0] if all_comments else None
                pr_state = pr["state"]
                is_merged = pr.get("pull_request", {}).get("merged_at") is not None
                current = {
                    "title": pr_title,
                    "state": "merged" if is_merged else pr_state,
                    "review_state": review_state,
                    "comment_count": total_comments,
                    "latest_comment_id": latest_comment["id"] if latest_comment else None,
                    "mergeable_state": mergeable_state,
                    "updated_at": pr["updated_at"]
                }
                if pr_id not in cache:
                    embed = make_embed(
                        title=f"🆕 New PR #{pr_number} — {pr_title}",
                        url=pr_url,
                        description=f"**Repo:** `{repo}`\n**Status:** opened",
                        color=discord.Color.blurple()
                    )
                    await channel.send(embed=embed)
                    cache[pr_id] = current
                else:
                    old = cache[pr_id]
                    if is_merged and old["state"] != "merged":
                        embed = make_embed(
                            title=f"✅ PR Merged! #{pr_number} — {pr_title}",
                            url=pr_url,
                            description=f"**Repo:** `{repo}`\nYour PR was merged! 🎉",
                            color=discord.Color.green(),
                            footer=pr["updated_at"][:10]
                        )
                        await channel.send(embed=embed)
                        current["state"] = "merged"
                    elif pr_state == "closed" and not is_merged and old["state"] == "open":
                        embed = make_embed(
                            title=f"❌ PR Closed #{pr_number} — {pr_title}",
                            url=pr_url,
                            description=f"**Repo:** `{repo}`\nPR was closed without merging.",
                            color=discord.Color.red()
                        )
                        await channel.send(embed=embed)
                    if old.get("review_state", "no reviews yet") != review_state and review_state != "no reviews yet":
                        if review_state == "approved":
                            emoji, color = "✅", discord.Color.green()
                        elif review_state == "changes_requested":
                            emoji, color = "🔄", discord.Color.orange()
                        else:
                            emoji, color = "👀", discord.Color.yellow()
                        embed = make_embed(
                            title=f"{emoji} Review Update — PR #{pr_number}",
                            url=pr_url,
                            description=f"**{pr_title}**\n**Repo:** `{repo}`\n**Review:** `{review_state}`",
                            color=color
                        )
                        await channel.send(embed=embed)
                    if total_comments > old.get("comment_count", 0) and latest_comment:
                        commenter = latest_comment.get("user", {}).get("login", "someone")
                        body = latest_comment.get("body", "")[:200]
                        if commenter.lower() != GITHUB_USERNAME.lower():
                            embed = make_embed(
                                title=f"💬 New Comment — PR #{pr_number}",
                                url=pr_url,
                                description=f"**{pr_title}**\n**Repo:** `{repo}`\n**By:** `{commenter}`\n\n> {body}",
                                color=discord.Color.blurple()
                            )
                            await channel.send(embed=embed)
                    if mergeable_state == "dirty" and old.get("mergeable_state") != "dirty":
                        embed = make_embed(
                            title=f"⚠️ Merge Conflict — PR #{pr_number}",
                            url=pr_url,
                            description=f"**{pr_title}**\n**Repo:** `{repo}`\nThis PR has conflicts that need to be resolved.",
                            color=discord.Color.yellow()
                        )
                        await channel.send(embed=embed)
                    if old.get("mergeable_state") == "dirty" and mergeable_state == "clean":
                        embed = make_embed(
                            title=f"✅ Conflicts Resolved — PR #{pr_number}",
                            url=pr_url,
                            description=f"**{pr_title}**\n**Repo:** `{repo}`\nMerge conflicts have been resolved!",
                            color=discord.Color.green()
                        )
                        await channel.send(embed=embed)
                    cache[pr_id] = current
            save_cache(cache)
        except Exception as e:
            print(f"[PR Tracker] Error in check_pr_updates: {e}")

    @check_pr_updates.error
    async def check_pr_updates_error(self, error):
        print(f"[PR Tracker] Task error (will retry next cycle): {error}")

    # ─── Daily 9AM IST summary ───────────────────────────────────

    @tasks.loop(minutes=1)
    async def daily_summary(self):
        try:
            now = datetime.now(timezone.utc)
            if now.hour == 3 and now.minute == 30:
                channel = self.bot.get_channel(PR_TRACKER_CHANNEL_ID)
                if not channel:
                    return
                prs = await fetch_my_open_prs()
                if not prs:
                    await channel.send("☀️ **Good morning! No open PRs today — go open some!**")
                    return
                msg = f"☀️ **Morning PR Summary — {now.strftime('%d %b %Y')}**\nYou have **{len(prs)} open PR(s)**:\n\n"
                for pr in prs:
                    repo = get_repo_from_pr(pr)
                    msg += f"• [`#{pr['number']}`]({pr['html_url']}) {pr['title']} — `{repo}`\n"
                await channel.send(msg)
        except Exception as e:
            print(f"[PR Tracker] Error in daily_summary: {e}")

    @daily_summary.error
    async def daily_summary_error(self, error):
        print(f"[PR Tracker] Daily summary error: {error}")


async def setup(bot):
    await bot.add_cog(PRTracker(bot))