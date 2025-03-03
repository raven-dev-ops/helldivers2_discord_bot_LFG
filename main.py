import os
import logging
import traceback
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# Enable all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# MongoDB setup
MONGO_URI = os.getenv('MONGODB_URI')
if not MONGO_URI:
    raise EnvironmentError("MONGODB_URI environment variable not set.")

client = AsyncIOMotorClient(MONGO_URI)
bot.mongo_db = client['GPTHellbot']  # Attach MongoDB instance to the bot

async def check_mongo_connection():
    """
    Verify the MongoDB connection before starting the bot.
    """
    try:
        await bot.mongo_db.command("ping")
        logging.info("Successfully connected to MongoDB.")
    except Exception as e:
        logging.error("Failed to connect to MongoDB. Check your MONGO_URI configuration.")
        raise e

async def load_cogs():
    """
    Load the bot's cogs in the correct order.
    """
    cogs = [
        'cogs.sos_cog',               # Main SOS management cog (no dependencies)
        'cogs.guild_management_cog',  # Handles guild setup and management
        'cogs.cleanup_cog',           # Handles cleanup tasks
        'cogs.menu_view',             # Provides the SOS menu interface
        'cogs.sos_view',              # Handles the SOS creation workflow
        'cogs.register_modal',        # Handles user registration modals
        'cogs.dm_response',           # Handles DM interactions for SOS responses
        'cogs.leaderboard_cog',       # <-- NEW: Our Leaderboard Cog
    ]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logging.info(f"Successfully loaded cog: {cog}")
        except Exception as e:
            logging.error(f"Failed to load cog {cog}: {e}")
            logging.error(traceback.format_exc())

@bot.event
async def setup_hook():
    """
    Hook to load all cogs during bot startup.
    """
    logging.info("Running setup_hook to load cogs...")
    await check_mongo_connection()  # Ensure MongoDB is accessible
    await load_cogs()

    # If you have persistent views, register them here
    from cogs.menu_view import SOSMenuView
    bot.add_view(SOSMenuView(bot))  # Example persistent view
    logging.info("Registered persistent views.")

@bot.event
async def on_ready():
    """
    Triggered when the bot is ready.
    """
    try:
        logging.info(f'{bot.user} has logged in and is ready.')
        synced = await bot.tree.sync()
        logging.info(f"Slash commands synced ({len(synced)} commands).")
    except Exception as e:
        logging.error(f"An error occurred during on_ready: {e}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    Triggered when the bot joins a new guild.
    """
    logging.info(f"Joined new guild: {guild.name} (ID: {guild.id})")

    # Ensure that the cogs are loaded
    sos_cog = bot.get_cog("SOSCog")
    guild_cog = bot.get_cog("GuildManagementCog")
    if sos_cog and guild_cog:
        try:
            # Configure the guild on join
            await guild_cog.setup_guild(guild, force_refresh=True)
        except Exception as e:
            logging.error(f"Error setting up guild {guild.name} (ID: {guild.id}): {e}")
    else:
        logging.warning("SOSCog or GuildManagementCog is not loaded. Cannot set up the guild.")

def validate_env_variables():
    """
    Validate that all required environment variables are set.
    """
    required_env_vars = ['DISCORD_TOKEN', 'MONGODB_URI']
    for var in required_env_vars:
        if not os.getenv(var):
            raise EnvironmentError(f"{var} environment variable is not set.")

if __name__ == "__main__":
    validate_env_variables()
    discord_token = os.getenv('DISCORD_TOKEN')
    try:
        bot.run(discord_token)
    except Exception as e:
        logging.error(f"An error occurred while running the bot: {e}")
