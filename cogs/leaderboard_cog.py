import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict

CATEGORY_NAME = "GPT NETWORK"
LEADERBOARD_CHANNEL_NAME = "leaderboard"

class LeaderboardCog(commands.Cog):
    """
    A Cog that manages a periodic leaderboard update.
    """

    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_lock = asyncio.Lock()
        # Start the periodic leaderboard update
        self.update_leaderboard_task.start()

    def cog_unload(self):
        self.update_leaderboard_task.cancel()

    @tasks.loop(hours=8)
    async def update_leaderboard_task(self):
        """
        Periodically updates every guild's #leaderboard channel with the latest stats.
        """
        async with self.leaderboard_lock:
            logging.info("Starting global leaderboard update for all guilds...")
            for guild in self.bot.guilds:
                try:
                    channel = await self.ensure_leaderboard_channel(guild)
                    if not channel:
                        logging.warning(f"No valid leaderboard channel in '{guild.name}'. Skipping.")
                        continue

                    # Pull data and build embeds
                    leaderboard_data = await self.calculate_leaderboard_data()
                    embeds = await self.build_leaderboard_embeds(leaderboard_data)

                    # Clean up old messages (limit=10 to avoid mass-deletion)
                    async for message in channel.history(limit=10):
                        if message.author == self.bot.user and message.embeds:
                            await message.delete()

                    # Send the newly built leaderboard
                    for embed in embeds:
                        await channel.send(embed=embed)

                    logging.info(f"Leaderboard updated in guild '{guild.name}'.")
                except Exception as e:
                    logging.exception(f"Error updating leaderboard for '{guild.name}': {e}")

    @update_leaderboard_task.before_loop
    async def before_update_leaderboard_task(self):
        """
        Ensure the bot is ready before the loop starts.
        """
        await self.bot.wait_until_ready()
        logging.info("Bot is ready. Starting update_leaderboard_task.")

    async def ensure_leaderboard_channel(self, guild: discord.Guild) -> discord.TextChannel:
        """
        Ensures the specified guild has a 'GPT NETWORK' category and a 'leaderboard' channel.
        Prevents reactions in the channel by setting add_reactions=False for @everyone.
        Returns the channel if successful, otherwise None.
        """
        if not guild.me.guild_permissions.manage_channels:
            logging.warning(
                f"Bot lacks 'Manage Channels' permission in guild '{guild.name}'. "
                "Skipping channel creation."
            )
            return None

        # Find or create the category
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            try:
                category = await guild.create_category(name=CATEGORY_NAME)
                logging.info(f"Created category '{CATEGORY_NAME}' in '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating category '{CATEGORY_NAME}' in '{guild.name}': {e}")
                return None

        # Find or create the #leaderboard channel
        leaderboard_channel = discord.utils.get(
            guild.text_channels,
            name=LEADERBOARD_CHANNEL_NAME,
            category=category
        )

        # Overwrites: read-only, no reactions for @everyone
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=False
            )
        }

        if not leaderboard_channel:
            try:
                leaderboard_channel = await guild.create_text_channel(
                    name=LEADERBOARD_CHANNEL_NAME,
                    overwrites=overwrites,
                    category=category
                )
                logging.info(
                    f"Created channel '{LEADERBOARD_CHANNEL_NAME}' in '{guild.name}'."
                )
            except Exception as e:
                logging.error(f"Error creating channel '{LEADERBOARD_CHANNEL_NAME}' in '{guild.name}': {e}")
                return None
        else:
            try:
                await leaderboard_channel.edit(category=category, overwrites=overwrites)
                logging.info(
                    f"Updated '#{LEADERBOARD_CHANNEL_NAME}' overwrites in '{guild.name}'."
                )
            except Exception as e:
                logging.warning(
                    f"Could not update '#{LEADERBOARD_CHANNEL_NAME}' overwrites in '{guild.name}': {e}"
                )
                return None

        return leaderboard_channel

    async def calculate_leaderboard_data(self):
        """
        Fetches and processes the leaderboard data from 'GPTHellbot.User_Stats'.
        Also fetches 'Alliance' collection to map discord_server_id -> server_name (Clan).

        Aggregates stats per player across all entries, then computes the
        AVERAGE of each metric. Returns a list sorted by average kills descending.
        """
        try:
            mongo_uri = os.getenv('MONGODB_URI')
            if not mongo_uri:
                raise ValueError("MONGODB_URI not set in environment.")

            client = AsyncIOMotorClient(mongo_uri)
            db = client['GPTHellbot']
            stats_collection = db['User_Stats']
            alliance_collection = db['Alliance']

            # Fetch alliance server info (maps server_id -> server_name)
            alliance_servers = await alliance_collection.find().to_list(length=None)
            server_map = {
                srv.get("discord_server_id"): srv.get("server_name", "Unknown Clan")
                for srv in alliance_servers
            }

            # Retrieve all player stats
            cursor = stats_collection.find()
            all_players = await cursor.to_list(length=None)

            # Aggregate stats
            player_data = defaultdict(lambda: {
                "total_kills": 0,
                "total_deaths": 0,
                "total_shots_fired": 0,
                "total_shots_hit": 0,
                "count": 0,
                "Clan": "Unknown Clan",
            })

            for p in all_players:
                name = p.get('player_name', 'Unknown Player')
                kills = int(p.get('Kills', 0) or 0)
                deaths = int(p.get('Deaths', 0) or 0)
                sfired = int(p.get('Shots Fired', 0) or 0)
                shit = int(p.get('Shots Hit', 0) or 0)

                # Attempt to map from discord_server_id -> clan name
                discord_server_id = p.get('discord_server_id')
                clan_name = server_map.get(discord_server_id, "Unknown Clan")

                player_data[name]["total_kills"] += kills
                player_data[name]["total_deaths"] += deaths
                player_data[name]["total_shots_fired"] += sfired
                player_data[name]["total_shots_hit"] += shit
                player_data[name]["count"] += 1
                player_data[name]["Clan"] = clan_name

            # Compute average stats
            leaderboard_list = []
            for player_name, stats in player_data.items():
                c = stats["count"]
                if c <= 0:
                    continue  # skip if no valid data

                avg_kills = stats["total_kills"] / c
                avg_deaths = stats["total_deaths"] / c
                avg_fired = stats["total_shots_fired"] / c
                avg_hit = stats["total_shots_hit"] / c
                acc = (avg_hit / avg_fired * 100) if avg_fired > 0 else 0

                leaderboard_list.append({
                    "player_name": player_name,
                    "Kills_Avg": avg_kills,
                    "Deaths_Avg": avg_deaths,
                    "ShotsFired_Avg": avg_fired,
                    "ShotsHit_Avg": avg_hit,
                    "Accuracy": acc,
                    "Clan": stats["Clan"],
                })

            # Sort by average kills descending
            leaderboard_list.sort(key=lambda x: x["Kills_Avg"], reverse=True)
            return leaderboard_list

        except Exception as e:
            logging.error(f"Error calculating leaderboard data: {e}")
            return []

    def remove_trailing_zeros(self, value_str: str) -> str:
        """
        Removes trailing zeros and a trailing decimal point from a string
        that was formatted with decimal places (e.g. '370.00' -> '370').
        """
        return value_str.rstrip('0').rstrip('.')

    async def build_leaderboard_embeds(self, leaderboard_data):
        """
        Creates a list of Discord Embeds from the given leaderboard data,
        displaying stats for each player, without trailing .00 and without the "(Avg)" label.
        """
        if not leaderboard_data:
            embed = discord.Embed(
                title="MARCH ALLIANCE LEADERBOARD\n**Best Overall Averages**\n",
                description="No leaderboard data available.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Leaderboard updates every 8 hours. Reset monthly.")
            return [embed]

        embeds = []
        batch_size = 25
        total_players = len(leaderboard_data)
        num_pages = (total_players + batch_size - 1) // batch_size

        for page_idx in range(num_pages):
            start_index = page_idx * batch_size
            end_index = min(start_index + batch_size, total_players)
            batch = leaderboard_data[start_index:end_index]

            embed = discord.Embed(
                title=(
                    f"**MARCH ALLIANCE LEADERBOARD**\n"
                    f"*Best Overall Averages*\n(Page {page_idx + 1}/{num_pages})"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="Leaderboard updates every 8 hours. Monthly reset.")

            for i, player in enumerate(batch, start=start_index):
                p_name = player["player_name"]

                # Format each float to two decimals, then remove trailing zeros
                kills_str = self.remove_trailing_zeros(f"{player['Kills_Avg']:.2f}")
                deaths_str = self.remove_trailing_zeros(f"{player['Deaths_Avg']:.2f}")
                sfired_str = self.remove_trailing_zeros(f"{player['ShotsFired_Avg']:.2f}")
                shit_str = self.remove_trailing_zeros(f"{player['ShotsHit_Avg']:.2f}")

                # For accuracy, format to one decimal then strip .0 if present
                acc_str = self.remove_trailing_zeros(f"{player['Accuracy']:.1f}")

                clan_name = player["Clan"]

                field_value = (
                    f"**Clan:** {clan_name}\n"
                    f"**Kills:** {kills_str}\n"
                    f"**Accuracy:** {acc_str}%\n"
                    f"**Deaths:** {deaths_str}\n"
                    f"**Shots Fired:** {sfired_str}\n"
                    f"**Shots Hit:** {shit_str}"
                )

                embed.add_field(
                    name=f"{i + 1}. {p_name}",
                    value=field_value,
                    inline=True
                )

            embeds.append(embed)

        return embeds

async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
