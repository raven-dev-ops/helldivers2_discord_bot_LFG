import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict

CATEGORY_NAME = "GPT NETWORK"
LEADERBOARD_CHANNEL_NAME = "❗｜leaderboard"

class LeaderboardCog(commands.Cog):
    """
    A Cog that manages a periodic leaderboard update.
    For May 2025, leaderboard ranks by Least Deaths, Most Kills, Best Accuracy.
    Players must have a minimum of 3 games played to appear on the leaderboard.
    """

    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_lock = asyncio.Lock()
        self.update_leaderboard_task.start()

    def cog_unload(self):
        self.update_leaderboard_task.cancel()

    @tasks.loop(hours=8)
    async def update_leaderboard_task(self):
        async with self.leaderboard_lock:
            logging.info("Starting global leaderboard update for all guilds...")
            for guild in self.bot.guilds:
                try:
                    channel = await self.ensure_leaderboard_channel(guild)
                    if not channel:
                        logging.warning(f"No valid leaderboard channel in '{guild.name}'. Skipping.")
                        continue

                    leaderboard_data = await self.calculate_leaderboard_data()
                    embeds = await self.build_leaderboard_embeds(leaderboard_data)

                    async for message in channel.history(limit=10):
                        if message.author == self.bot.user and message.embeds:
                            await message.delete()

                    for embed in embeds:
                        await channel.send(embed=embed)

                    logging.info(f"Leaderboard updated in guild '{guild.name}'.")
                except Exception as e:
                    logging.exception(f"Error updating leaderboard for '{guild.name}': {e}")

    @update_leaderboard_task.before_loop
    async def before_update_leaderboard_task(self):
        await self.bot.wait_until_ready()
        logging.info("Bot is ready. Starting update_leaderboard_task.")

    async def ensure_leaderboard_channel(self, guild: discord.Guild) -> discord.TextChannel:
        if not guild.me.guild_permissions.manage_channels:
            logging.warning(f"Bot lacks 'Manage Channels' permission in guild '{guild.name}'. Skipping channel creation.")
            return None

        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            category = await guild.create_category(name=CATEGORY_NAME)

        leaderboard_channel = discord.utils.get(
            guild.text_channels,
            name=LEADERBOARD_CHANNEL_NAME,
            category=category
        )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, add_reactions=False)
        }

        if not leaderboard_channel:
            leaderboard_channel = await guild.create_text_channel(
                name=LEADERBOARD_CHANNEL_NAME,
                overwrites=overwrites,
                category=category
            )
        else:
            await leaderboard_channel.edit(category=category, overwrites=overwrites)

        return leaderboard_channel

    async def calculate_leaderboard_data(self):
        mongo_uri = os.getenv('MONGODB_URI')
        client = AsyncIOMotorClient(mongo_uri)
        db = client['GPTHellbot']
        stats_collection = db['User_Stats']
        alliance_collection = db['Alliance']

        alliance_servers = await alliance_collection.find().to_list(length=None)
        server_map = {srv.get("discord_server_id"): srv.get("server_name", "Unknown Clan") for srv in alliance_servers}

        cursor = stats_collection.find()
        all_players = await cursor.to_list(length=None)

        player_data = defaultdict(lambda: {"kills": 0, "deaths": 0, "shots_fired": 0, "shots_hit": 0, "games_played": 0, "Clan": "Unknown Clan"})

        for p in all_players:
            name = p.get('player_name', 'Unknown Player')
            discord_server_id = p.get('discord_server_id')
            clan_name = server_map.get(discord_server_id, "Unknown Clan")

            player_data[name]["kills"] += int(p.get('Kills', 0) or 0)
            player_data[name]["deaths"] += int(p.get('Deaths', 0) or 0)
            player_data[name]["shots_fired"] += int(p.get('Shots Fired', 0) or 0)
            player_data[name]["shots_hit"] += int(p.get('Shots Hit', 0) or 0)
            player_data[name]["games_played"] += 1
            player_data[name]["Clan"] = clan_name

        leaderboard_list = [
            {"player_name": name, **data, "accuracy": (data["shots_hit"] / data["shots_fired"] * 100 if data["shots_fired"] else 0)}
            for name, data in player_data.items() if data["games_played"] >= 3
        ]

        leaderboard_list.sort(key=lambda x: (x["deaths"], -x["kills"], -x["accuracy"]))
        return leaderboard_list

    async def build_leaderboard_embeds(self, leaderboard_data):
        if not leaderboard_data:
            return [discord.Embed(title="MAY ALLIANCE LEADERBOARD\n**Best (Least) Deaths**", description="No leaderboard data available.\nMust submit at least (3) games to appear!", color=discord.Color.blue())]

        embeds = []
        batch_size = 25
        total_players = len(leaderboard_data)
        num_pages = (total_players + batch_size - 1) // batch_size

        for page_idx in range(num_pages):
            batch = leaderboard_data[page_idx * batch_size:(page_idx + 1) * batch_size]
            embed = discord.Embed(title=f"**MAY ALLIANCE LEADERBOARD**\n*(Least Deaths, Most Kills, Best Accuracy)*\n(Page {page_idx + 1}/{num_pages})", color=discord.Color.blue())
            embed.set_footer(text="Leaderboard updates every 8 hours. Monthly reset.")

            for i, player in enumerate(batch, start=1 + page_idx * batch_size):
                embed.add_field(name=f"{i}. {player['player_name']}", value=f"Clan: {player['Clan']}\nDeaths: {player['deaths']}\nKills: {player['kills']}\nAccuracy: {player['accuracy']:.1f}%", inline=True)

            embeds.append(embed)

        return embeds

async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))