import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
from datetime import datetime, timezone

# ── Change these two values ──────────────────────────────────────
YOUR_DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID"))
DAILY_LOG_CHANNEL_ID = int(os.getenv("DAILY_LOG_CHANNEL_ID"))
# ─────────────────────────────────────────────────────────────────

STANDUP_FILE = "standup_data.json"

QUESTIONS = [
    "What did you get done yesterday?",
    "What's the plan for today?",
    "Any blockers?"
]

def load_standup_data():
    if not os.path.exists(STANDUP_FILE):
        return {}
    with open(STANDUP_FILE, "r") as f:
        return json.load(f)

def save_standup_data(data):
    with open(STANDUP_FILE, "w") as f:
        json.dump(data, f, indent=2)


class Standup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending = {}  # user_id -> {answers: [], question_index: int}
        self.morning_standup.start()

    def cog_unload(self):
        self.morning_standup.cancel()

    async def start_standup(self, user: discord.User):
        """Start the standup flow for a user."""
        self.pending[user.id] = {"answers": [], "question_index": 0}
        await user.send(
            f"🌅 **Good morning Sid! Standup time.**\n\n"
            f"**Question 1/3:** {QUESTIONS[0]}"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for DM replies to collect standup answers."""
        # Only listen to DMs from the right user, ignore bot messages
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != YOUR_DISCORD_USER_ID:
            return
        if message.author.id not in self.pending:
            return

        state = self.pending[message.author.id]
        state["answers"].append(message.content)
        state["question_index"] += 1

        if state["question_index"] < len(QUESTIONS):
            # Ask next question
            next_q = state["question_index"] + 1
            await message.author.send(
                f"**Question {next_q}/3:** {QUESTIONS[state['question_index']]}"
            )
        else:
            # All answers collected — post to #daily-log
            answers = state["answers"]
            del self.pending[message.author.id]

            today = datetime.now(timezone.utc).strftime("%d %b %Y")
            log_msg = (
                f"📋 **Daily Standup — {today}**\n\n"
                f"✅ **Yesterday:** {answers[0]}\n\n"
                f"📌 **Today:** {answers[1]}\n\n"
                f"🚧 **Blockers:** {answers[2]}"
            )

            # Post to #daily-log channel
            channel = self.bot.get_channel(DAILY_LOG_CHANNEL_ID)
            if channel:
                await channel.send(log_msg)

            # Save to local file
            data = load_standup_data()
            today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            data[today_key] = {
                "yesterday": answers[0],
                "today": answers[1],
                "blockers": answers[2]
            }
            save_standup_data(data)

            await message.author.send("✅ Standup posted to #daily-log!")

    @tasks.loop(minutes=1)
    async def morning_standup(self):
        """Trigger standup at 8AM IST (2:30 UTC)."""
        now = datetime.now(timezone.utc)
        if now.hour == 2 and now.minute == 30:
            user = await self.bot.fetch_user(YOUR_DISCORD_USER_ID)
            if user:
                await self.start_standup(user)

    @app_commands.command(name="standup", description="Trigger your daily standup manually")
    async def standup_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Check your DMs!", ephemeral=True)
        user = await self.bot.fetch_user(YOUR_DISCORD_USER_ID)
        await self.start_standup(user)

    @app_commands.command(name="history", description="See your last 7 standups")
    async def history_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = load_standup_data()
        if not data:
            await interaction.followup.send("No standup history yet.")
            return
        # Get last 7 entries sorted by date
        sorted_days = sorted(data.keys(), reverse=True)[:7]
        msg = "**📋 Last 7 Standups:**\n\n"
        for day in sorted_days:
            entry = data[day]
            msg += (
                f"**{day}**\n"
                f"✅ {entry['yesterday']}\n"
                f"📌 {entry['today']}\n"
                f"🚧 {entry['blockers']}\n\n"
            )
        await interaction.followup.send(msg)

    @app_commands.command(name="streak", description="See your standup streak")
    async def streak_command(self, interaction: discord.Interaction):
        data = load_standup_data()
        if not data:
            await interaction.response.send_message("No standup history yet — do your first one with `/standup`!")
            return
        from datetime import timedelta, date
        sorted_days = sorted(data.keys(), reverse=True)
        streak = 0
        check_date = date.today()
        for day_str in sorted_days:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            if day == check_date or day == check_date - timedelta(days=1):
                streak += 1
                check_date = day - timedelta(days=1)
            else:
                break
        await interaction.response.send_message(f"🔥 Your current standup streak: **{streak} day(s)**")

    @app_commands.command(name="skip", description="Skip today's standup")
    async def skip_command(self, interaction: discord.Interaction):
        data = load_standup_data()
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data[today_key] = {
            "yesterday": "skipped",
            "today": "skipped",
            "blockers": "skipped"
        }
        save_standup_data(data)
        await interaction.response.send_message("✅ Today's standup skipped.")


async def setup(bot):
    await bot.add_cog(Standup(bot))