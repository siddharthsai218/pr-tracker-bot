import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
from datetime import datetime, timezone, timedelta
import re

YOUR_DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID"))
REMINDERS_CHANNEL_ID = int(os.getenv("REMINDERS_CHANNEL_ID"))

REMINDERS_FILE = "reminders.json"

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

CATEGORY_KEYWORDS = {
    "academic": ["exam", "assignment", "viva", "submission", "project", "test", "quiz", "lab", "class"],
    "dev": ["pr", "commit", "review", "issue", "contribute", "push", "deploy", "bug", "code"],
    "personal": ["gym", "sleep", "habit", "read", "workout", "meditate", "journal"],
    "event": ["meeting", "fest", "deadline", "call", "interview", "event", "seminar"]
}

CATEGORY_EMOJI = {
    "academic": "📚",
    "dev": "💻",
    "personal": "🏃",
    "event": "📅",
    "general": "🔔"
}

def detect_category(text):
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "general"

def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, "r") as f:
        return json.load(f)

def save_reminders(data):
    with open(REMINDERS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

def parse_datetime(date_str, time_str):
    """Parse date and time strings into a datetime object in IST."""
    now = datetime.now(IST)
    
    # Time parsing
    time_str = time_str.lower().strip()
    hour, minute = 9, 0
    
    time_formats = ["%I%p", "%I:%M%p", "%H:%M", "%H"]
    time_str_clean = time_str.replace(" ", "").upper()
    parsed_time = None
    for fmt in ["%I%p", "%I:%M%p", "%H:%M"]:
        try:
            parsed_time = datetime.strptime(time_str_clean, fmt)
            hour, minute = parsed_time.hour, parsed_time.minute
            break
        except:
            continue
    
    if parsed_time is None:
        # Try plain number like "9" or "21"
        try:
            h = int(time_str_clean.replace("AM","").replace("PM",""))
            if "PM" in time_str_clean and h != 12:
                h += 12
            hour, minute = h, 0
        except:
            hour, minute = 9, 0

    # Date parsing
    date_str = date_str.strip()
    parsed_date = None
    
    # Handle relative dates
    if date_str.lower() == "today":
        parsed_date = now.date()
    elif date_str.lower() == "tomorrow":
        parsed_date = (now + timedelta(days=1)).date()
    else:
        date_formats = [
            "%d %b", "%d %B", "%d/%m", "%d/%m/%Y",
            "%d-%m", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"
        ]
        for fmt in date_formats:
            try:
                d = datetime.strptime(date_str, fmt)
                # If no year, use current or next year
                if d.year == 1900:
                    d = d.replace(year=now.year)
                    if d.date() < now.date():
                        d = d.replace(year=now.year + 1)
                parsed_date = d.date()
                break
            except:
                continue
    
    if parsed_date is None:
        return None
    
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, hour, minute, tzinfo=IST)

def format_time_until(dt):
    """Human readable time until a datetime."""
    now = datetime.now(IST)
    diff = dt - now
    if diff.total_seconds() < 0:
        return "overdue"
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()
        self.monday_briefing.start()
        self.today_briefing.start()

    def cog_unload(self):
        self.check_reminders.cancel()
        self.monday_briefing.cancel()
        self.today_briefing.cancel()

    # ─── Slash Commands ──────────────────────────────────────────

    @app_commands.command(name="remind", description="Set a reminder — /remind task date time")
    @app_commands.describe(
        task="What to remind you about",
        date="Date: today, tomorrow, '10 Jun', '25/06'",
        time="Time: 9am, 14:30, 9:00pm"
    )
    async def remind_command(self, interaction: discord.Interaction, task: str, date: str, time: str):
        dt = parse_datetime(date, time)
        if not dt:
            await interaction.response.send_message(
                "❌ Couldn't parse that date/time. Try: `/remind \"CN exam\" \"10 Jun\" \"9am\"`",
                ephemeral=True
            )
            return
        
        now = datetime.now(IST)
        if dt < now:
            await interaction.response.send_message("❌ That date is in the past!", ephemeral=True)
            return

        category = detect_category(task)
        reminders = load_reminders()
        reminder = {
            "id": len(reminders) + 1,
            "task": task,
            "datetime": dt.isoformat(),
            "category": category,
            "repeat": None,
            "done": False,
            "notified_7d": False,
            "notified_3d": False,
            "notified_1d": False,
            "notified_3h": False,
            "notified_due": False,
            "overdue_notified": False
        }
        reminders.append(reminder)
        save_reminders(reminders)

        emoji = CATEGORY_EMOJI[category]
        await interaction.response.send_message(
            f"{emoji} **Reminder set!**\n"
            f"**Task:** {task}\n"
            f"**When:** {dt.strftime('%d %b %Y at %I:%M %p')} IST\n"
            f"**Category:** {category}\n"
            f"**Time until:** {format_time_until(dt)}\n\n"
            f"You'll get DMs at: 7 days, 3 days, 1 day, 3 hours, and at exact time."
        )

    @app_commands.command(name="remindrepeat", description="Set a recurring reminder")
    @app_commands.describe(
        task="What to remind you about",
        time="Time: 9am, 11pm, 14:30",
        repeat="daily or weekly"
    )
    async def remindrepeat_command(self, interaction: discord.Interaction, task: str, time: str, repeat: str):
        if repeat.lower() not in ["daily", "weekly"]:
            await interaction.response.send_message("❌ Repeat must be `daily` or `weekly`", ephemeral=True)
            return

        # Set first occurrence as today at given time
        dt = parse_datetime("today", time)
        if not dt:
            await interaction.response.send_message("❌ Couldn't parse that time.", ephemeral=True)
            return

        now = datetime.now(IST)
        if dt < now:
            # Move to tomorrow
            dt = dt + timedelta(days=1)

        category = detect_category(task)
        reminders = load_reminders()
        reminder = {
            "id": len(reminders) + 1,
            "task": task,
            "datetime": dt.isoformat(),
            "category": category,
            "repeat": repeat.lower(),
            "done": False,
            "notified_7d": True,  # skip advance notices for repeating
            "notified_3d": True,
            "notified_1d": True,
            "notified_3h": True,
            "notified_due": False,
            "overdue_notified": False
        }
        reminders.append(reminder)
        save_reminders(reminders)

        emoji = CATEGORY_EMOJI[category]
        await interaction.response.send_message(
            f"{emoji} **Recurring reminder set!**\n"
            f"**Task:** {task}\n"
            f"**Time:** {dt.strftime('%I:%M %p')} IST\n"
            f"**Repeats:** {repeat}\n"
            f"**First reminder:** {dt.strftime('%d %b %Y')}"
        )

    @app_commands.command(name="upcoming", description="Show all your upcoming reminders")
    async def upcoming_command(self, interaction: discord.Interaction):
        reminders = load_reminders()
        active = [r for r in reminders if not r["done"]]
        if not active:
            await interaction.response.send_message("✅ No upcoming reminders!")
            return

        active.sort(key=lambda x: x["datetime"])
        msg = "**📋 Upcoming Reminders:**\n\n"
        for r in active:
            dt = datetime.fromisoformat(r["datetime"])
            emoji = CATEGORY_EMOJI.get(r["category"], "🔔")
            repeat_tag = f" `{r['repeat']}`" if r["repeat"] else ""
            msg += (
                f"{emoji} **{r['task']}**{repeat_tag}\n"
                f"  📅 {dt.strftime('%d %b %Y at %I:%M %p')} IST — _{format_time_until(dt)}_\n\n"
            )
        await interaction.response.send_message(msg)

    @app_commands.command(name="today", description="Show everything due today")
    async def today_command(self, interaction: discord.Interaction):
        reminders = load_reminders()
        now = datetime.now(IST)
        today_reminders = [
            r for r in reminders
            if not r["done"] and
            datetime.fromisoformat(r["datetime"]).date() == now.date()
        ]
        if not today_reminders:
            await interaction.response.send_message("✅ Nothing due today — enjoy!")
            return
        today_reminders.sort(key=lambda x: x["datetime"])
        msg = f"**📅 Today's Reminders — {now.strftime('%d %b %Y')}:**\n\n"
        for r in today_reminders:
            dt = datetime.fromisoformat(r["datetime"])
            emoji = CATEGORY_EMOJI.get(r["category"], "🔔")
            msg += f"{emoji} **{r['task']}** — {dt.strftime('%I:%M %p')}\n"
        await interaction.response.send_message(msg)

    @app_commands.command(name="week", description="Show this week's reminders")
    async def week_command(self, interaction: discord.Interaction):
        reminders = load_reminders()
        now = datetime.now(IST)
        week_end = now + timedelta(days=7)
        week_reminders = [
            r for r in reminders
            if not r["done"] and
            now <= datetime.fromisoformat(r["datetime"]) <= week_end
        ]
        if not week_reminders:
            await interaction.response.send_message("✅ Nothing due this week!")
            return
        week_reminders.sort(key=lambda x: x["datetime"])
        msg = f"**📅 This Week's Reminders:**\n\n"
        for r in week_reminders:
            dt = datetime.fromisoformat(r["datetime"])
            emoji = CATEGORY_EMOJI.get(r["category"], "🔔")
            msg += f"{emoji} **{r['task']}** — {dt.strftime('%d %b at %I:%M %p')} _{format_time_until(dt)}_\n"
        await interaction.response.send_message(msg)

    @app_commands.command(name="done", description="Mark a reminder as done")
    @app_commands.describe(task="Part of the task name to search for")
    async def done_command(self, interaction: discord.Interaction, task: str):
        reminders = load_reminders()
        matched = [r for r in reminders if task.lower() in r["task"].lower() and not r["done"]]
        if not matched:
            await interaction.response.send_message(f"❌ No active reminder found matching `{task}`", ephemeral=True)
            return
        matched[0]["done"] = True
        save_reminders(reminders)
        await interaction.response.send_message(f"✅ Marked as done: **{matched[0]['task']}**")

    @app_commands.command(name="delete", description="Delete a reminder")
    @app_commands.describe(task="Part of the task name to search for")
    async def delete_command(self, interaction: discord.Interaction, task: str):
        reminders = load_reminders()
        matched = [r for r in reminders if task.lower() in r["task"].lower()]
        if not matched:
            await interaction.response.send_message(f"❌ No reminder found matching `{task}`", ephemeral=True)
            return
        reminders = [r for r in reminders if r["id"] != matched[0]["id"]]
        save_reminders(reminders)
        await interaction.response.send_message(f"🗑️ Deleted: **{matched[0]['task']}**")

    @app_commands.command(name="snooze", description="Snooze a reminder")
    @app_commands.describe(
        task="Part of the task name",
        duration="How long to snooze: 1h, 30m, 2h"
    )
    async def snooze_command(self, interaction: discord.Interaction, task: str, duration: str):
        reminders = load_reminders()
        matched = [r for r in reminders if task.lower() in r["task"].lower() and not r["done"]]
        if not matched:
            await interaction.response.send_message(f"❌ No active reminder found matching `{task}`", ephemeral=True)
            return

        # Parse duration
        duration = duration.lower().strip()
        minutes = 0
        if "h" in duration:
            parts = duration.split("h")
            minutes += int(parts[0]) * 60
            if parts[1].replace("m","").strip():
                minutes += int(parts[1].replace("m","").strip())
        elif "m" in duration:
            minutes = int(duration.replace("m",""))

        if minutes == 0:
            await interaction.response.send_message("❌ Couldn't parse duration. Try `1h`, `30m`, `2h30m`", ephemeral=True)
            return

        r = matched[0]
        old_dt = datetime.fromisoformat(r["datetime"])
        new_dt = old_dt + timedelta(minutes=minutes)
        r["datetime"] = new_dt.isoformat()
        r["notified_3h"] = False
        r["notified_due"] = False
        save_reminders(reminders)

        await interaction.response.send_message(
            f"⏰ Snoozed **{r['task']}** by {duration}\n"
            f"New time: {new_dt.strftime('%d %b at %I:%M %p')} IST"
        )

    @app_commands.command(name="list", description="List all reminders grouped by category")
    async def list_command(self, interaction: discord.Interaction):
        reminders = load_reminders()
        active = [r for r in reminders if not r["done"]]
        if not active:
            await interaction.response.send_message("✅ No active reminders!")
            return

        grouped = {}
        for r in active:
            cat = r["category"]
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(r)

        msg = "**📋 All Reminders by Category:**\n\n"
        for cat, items in grouped.items():
            emoji = CATEGORY_EMOJI.get(cat, "🔔")
            msg += f"{emoji} **{cat.upper()}**\n"
            for r in sorted(items, key=lambda x: x["datetime"]):
                dt = datetime.fromisoformat(r["datetime"])
                repeat_tag = f" `{r['repeat']}`" if r["repeat"] else ""
                msg += f"  • {r['task']}{repeat_tag} — {dt.strftime('%d %b at %I:%M %p')} _{format_time_until(dt)}_\n"
            msg += "\n"
        await interaction.response.send_message(msg)

    # ─── Core reminder checker (every 1 min) ─────────────────────

    @tasks.loop(minutes=5)
    async def check_reminders(self):
        try:
            reminders = load_reminders()
            if not reminders:
                return
            active = [r for r in reminders if not r["done"]]
            if not active:
                return
            user = await self.bot.fetch_user(YOUR_DISCORD_USER_ID)
            if not user:
                return

            reminders = load_reminders()
            now = datetime.now(IST)
            changed = False

            for r in reminders:
                if r["done"]:
                    continue

                dt = datetime.fromisoformat(r["datetime"])
                diff = dt - now
                total_seconds = diff.total_seconds()
                emoji = CATEGORY_EMOJI.get(r["category"], "🔔")

                # 7 days before
                if not r["notified_7d"] and 0 < total_seconds <= 7 * 24 * 3600 and total_seconds > 6 * 24 * 3600:
                    await user.send(
                        f"{emoji} **7 Day Reminder — {r['task']}**\n"
                        f"📅 Due: {dt.strftime('%d %b %Y at %I:%M %p')} IST\n"
                        f"⏳ 7 days to go!"
                    )
                    r["notified_7d"] = True
                    changed = True

                # 3 days before
                elif not r["notified_3d"] and 0 < total_seconds <= 3 * 24 * 3600 and total_seconds > 2 * 24 * 3600:
                    await user.send(
                        f"{emoji} **3 Day Reminder — {r['task']}**\n"
                        f"📅 Due: {dt.strftime('%d %b %Y at %I:%M %p')} IST\n"
                        f"⏳ 3 days to go — start preparing!"
                    )
                    r["notified_3d"] = True
                    changed = True

                # 1 day before
                elif not r["notified_1d"] and 0 < total_seconds <= 24 * 3600 and total_seconds > 3 * 3600:
                    await user.send(
                        f"{emoji} **Tomorrow — {r['task']}**\n"
                        f"📅 Due: {dt.strftime('%d %b %Y at %I:%M %p')} IST\n"
                        f"⏳ 1 day to go — are you ready?"
                    )
                    r["notified_1d"] = True
                    changed = True

                # 3 hours before
                elif not r["notified_3h"] and 0 < total_seconds <= 3 * 3600 and total_seconds > 0:
                    await user.send(
                        f"{emoji} **3 Hours Left — {r['task']}**\n"
                        f"📅 Due: {dt.strftime('%I:%M %p')} IST today\n"
                        f"⚡ Final stretch!"
                    )
                    r["notified_3h"] = True
                    changed = True

                # Due now (within 1 minute window)
                elif not r["notified_due"] and -60 <= total_seconds <= 60:
                    await user.send(
                        f"🔔 **DUE NOW — {r['task']}**\n"
                        f"📅 {dt.strftime('%d %b %Y at %I:%M %p')} IST"
                    )
                    r["notified_due"] = True
                    changed = True

                    # Also post to channel for academic/event items
                    if r["category"] in ["academic", "event"]:
                        channel = self.bot.get_channel(REMINDERS_CHANNEL_ID)
                        if channel:
                            await channel.send(
                                f"{emoji} **Due Now: {r['task']}**\n"
                                f"📅 {dt.strftime('%d %b %Y at %I:%M %p')} IST"
                            )

                    # Handle repeating reminders
                    if r["repeat"] == "daily":
                        r["datetime"] = (dt + timedelta(days=1)).isoformat()
                        r["notified_due"] = False
                        r["overdue_notified"] = False
                    elif r["repeat"] == "weekly":
                        r["datetime"] = (dt + timedelta(weeks=1)).isoformat()
                        r["notified_due"] = False
                        r["overdue_notified"] = False

                # Overdue (more than 1 hour past due, not done)
                elif not r["overdue_notified"] and total_seconds < -3600 and not r["repeat"]:
                    await user.send(
                        f"⚠️ **Overdue — {r['task']}**\n"
                        f"This was due {dt.strftime('%d %b at %I:%M %p')} IST\n"
                        f"Still pending? Use `/done {r['task'][:20]}` to mark complete or `/snooze` to reschedule."
                    )
                    r["overdue_notified"] = True
                    changed = True

            if changed:
                save_reminders(reminders)

        except Exception as e:
            print(f"[Reminder] Error in check_reminders: {e}")

    @check_reminders.error
    async def check_reminders_error(self, error):
        print(f"[Reminder] Task error: {error}")

    # ─── Monday 8AM weekly briefing ──────────────────────────────

    @tasks.loop(minutes=5)
    async def monday_briefing(self):
        try:
            now = datetime.now(IST)
            if now.weekday() == 0 and now.hour == 8 and now.minute == 0:
                user = await self.bot.fetch_user(YOUR_DISCORD_USER_ID)
                reminders = load_reminders()
                week_end = now + timedelta(days=7)
                week_reminders = [
                    r for r in reminders
                    if not r["done"] and now <= datetime.fromisoformat(r["datetime"]) <= week_end
                ]
                if not week_reminders:
                    await user.send("☀️ **Good Monday! Nothing due this week — go build something!**")
                    return
                week_reminders.sort(key=lambda x: x["datetime"])
                msg = f"☀️ **Weekly Briefing — Week of {now.strftime('%d %b')}**\n\n"
                for r in week_reminders:
                    dt = datetime.fromisoformat(r["datetime"])
                    emoji = CATEGORY_EMOJI.get(r["category"], "🔔")
                    msg += f"{emoji} **{r['task']}** — {dt.strftime('%d %b at %I:%M %p')} _{format_time_until(dt)}_\n"
                await user.send(msg)
        except Exception as e:
            print(f"[Reminder] Monday briefing error: {e}")

    # ─── Daily 7AM today briefing ────────────────────────────────

    @tasks.loop(minutes=5)
    async def today_briefing(self):
        try:
            now = datetime.now(IST)
            if now.hour == 7 and now.minute == 0:
                user = await self.bot.fetch_user(YOUR_DISCORD_USER_ID)
                reminders = load_reminders()
                today_reminders = [
                    r for r in reminders
                    if not r["done"] and
                    datetime.fromisoformat(r["datetime"]).date() == now.date()
                ]
                if not today_reminders:
                    return  # No DM if nothing due today
                today_reminders.sort(key=lambda x: x["datetime"])
                msg = f"📅 **Good morning! You have {len(today_reminders)} thing(s) due today:**\n\n"
                for r in today_reminders:
                    dt = datetime.fromisoformat(r["datetime"])
                    emoji = CATEGORY_EMOJI.get(r["category"], "🔔")
                    msg += f"{emoji} **{r['task']}** — {dt.strftime('%I:%M %p')}\n"
                await user.send(msg)
        except Exception as e:
            print(f"[Reminder] Today briefing error: {e}")


async def setup(bot):
    await bot.add_cog(Reminder(bot))