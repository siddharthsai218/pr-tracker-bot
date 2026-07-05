import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    await bot.load_extension("cogs.pr_tracker")
    await bot.load_extension("cogs.standup")
    await bot.load_extension("cogs.reminder")

@bot.event
async def on_ready():
    await load_cogs()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    print("✅ All cogs loaded and slash commands synced")

bot.run(DISCORD_TOKEN)