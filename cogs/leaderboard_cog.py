import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict
import pprint # For pretty printing

# --- Constants ---
CATEGORY_NAME = "GPT NETWORK"
LEADERBOARD_CHANNEL_NAME = "❗｜leaderboard"
LEADERBOARD_IMAGE_PATH = "sos_leaderboard.png" # Assuming the image is in the root
MIN_GAMES_PLAYED = 3 # Define the minimum games played requirement

# --- Configure logging ---
# It's good practice to configure logging more centrally if you have a larger bot,
# but for this cog, ensuring a basic level is fine.
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__) # Use a specific logger for this cog

class LeaderboardCog(commands.Cog):
    """
    A Cog that manages a periodic leaderboard update.
    For May 2025, leaderboard ranks by Least Deaths, Most Kills, Best Accuracy.
    Players must have a minimum of MIN_GAMES_PLAYED games played to appear on the leaderboard.
    Includes an embedded image at the top of each leaderboard embed.
    """

    def __init__(self, bot):
        self.bot = bot
        if not hasattr(self.bot, 'mongo_db') or self.bot.mongo_db is None:
            logger.error("MongoDB client not found in bot object during LeaderboardCog init. Database functions may fail.")
            # Consider not starting the task if DB is absolutely critical from the start
            # For now, we let it initialize, and the task will check again.
        else:
            logger.info("MongoDB client found in bot object during LeaderboardCog init.")

        self.leaderboard_lock = asyncio.Lock()
        try:
            self.update_leaderboard_task.start()
        except Exception as e:
            logger.error(f"Failed to start update_leaderboard_task: {e}", exc_info=True)

    def cog_unload(self):
        self.update_leaderboard_task.cancel()
        logger.info("LeaderboardCog unloaded, update task cancelled.")

    @tasks.loop(hours=8)
    async def update_leaderboard_task(self):
        async with self.leaderboard_lock:
            logger.info("Starting global leaderboard update for all guilds...")
            if not hasattr(self.bot, 'mongo_db') or self.bot.mongo_db is None:
                logger.error("MongoDB client not available during leaderboard update task. Skipping update.")
                return

            try:
                leaderboard_data = await self.calculate_leaderboard_data()
                if not leaderboard_data: # Explicitly check if data is empty
                    logger.info("No leaderboard data was calculated. Leaderboard will indicate no data.")
                
                # build_leaderboard_embeds now always returns a tuple (embeds, image_path_to_use)
                embeds, image_path_to_use = await self.build_leaderboard_embeds(leaderboard_data)

            except Exception as e:
                logger.exception(f"Error calculating or building leaderboard data: {e}")
                return

            for guild in self.bot.guilds:
                logger.debug(f"Processing guild: {guild.name} ({guild.id})")
                try:
                    channel = await self.ensure_leaderboard_channel(guild)
                    if not channel:
                        logger.warning(f"No valid leaderboard channel in '{guild.name}' or bot lacks permissions. Skipping update for this guild.")
                        continue

                    required_perms = {"send_messages": False, "embed_links": False}
                    if image_path_to_use: # Only require attach_files if an image is being used
                        required_perms["attach_files"] = False
                    
                    current_perms = channel.permissions_for(guild.me)
                    missing_perms_list = [
                        perm_name for perm_name, needed in required_perms.items() 
                        if not getattr(current_perms, perm_name)
                    ]

                    if missing_perms_list:
                        logger.warning(f"Bot lacks required permissions ({', '.join(missing_perms_list)}) in channel '{channel.name}' ({channel.id}) in guild '{guild.name}'. Cannot send leaderboard. Skipping.")
                        continue
                    
                    # Clear previous bot messages
                    logger.debug(f"Clearing previous leaderboard messages in channel '{channel.name}' in guild '{guild.name}'.")
                    try:
                        # Check for manage_messages permission before attempting to delete
                        if channel.permissions_for(guild.me).manage_messages:
                            async for message in channel.history(limit=20):
                                if message.author == self.bot.user and (message.embeds or message.attachments): # Check for embeds or attachments
                                    try:
                                        await message.delete()
                                        await asyncio.sleep(0.6) # Slightly increased delay
                                    except discord.Forbidden:
                                        logger.warning(f"Bot lacks permission to delete a specific message in '{channel.name}' of '{guild.name}'. Might be due to message age or other restrictions.")
                                    except discord.HTTPException as http_e:
                                        logger.warning(f"HTTP error deleting message in '{channel.name}' of '{guild.name}': {http_e}")
                            logger.debug(f"Finished clearing previous leaderboard messages in '{guild.name}'.")
                        else:
                            logger.warning(f"Bot lacks 'Manage Messages' permission in '{channel.name}' of '{guild.name}'. Skipping message clearing.")
                    except discord.Forbidden:
                        logger.error(f"Bot lacks permissions to read message history or manage messages in channel '{channel.name}' ({channel.id}) in guild '{guild.name}'. Previous messages may not be cleared.")
                    except Exception as e:
                        logger.error(f"Error clearing previous messages in channel '{channel.name}' ({channel.id}) in guild '{guild.name}': {e}", exc_info=True)

                    # Send new leaderboard
                    if not embeds: # This means leaderboard_data was empty
                        no_data_embed = discord.Embed(
                            title=f"**MAY ALLIANCE LEADERBOARD**", # Simpler title for no data
                            description=f"No leaderboard data available.\nPlayers must submit at least ({MIN_GAMES_PLAYED}) games to appear!",
                            color=discord.Color.blue()
                        )
                        no_data_file = None
                        if image_path_to_use:
                            try:
                                no_data_file = discord.File(image_path_to_use, filename=os.path.basename(image_path_to_use))
                                no_data_embed.set_image(url=f"attachment://{os.path.basename(image_path_to_use)}")
                            except Exception as e:
                                logger.error(f"Error preparing image for 'no data' embed in guild '{guild.name}': {e}", exc_info=True)
                                no_data_file = None
                        
                        try:
                            await channel.send(embed=no_data_embed, file=no_data_file if no_data_file else discord.utils.MISSING)
                            logger.info(f"Sent 'no data' leaderboard embed {'with image' if no_data_file else 'without image'} to '{guild.name}'.")
                        except Exception as e:
                            logger.error(f"Failed to send 'no data' embed to '{guild.name}': {e}", exc_info=True)
                    else:
                        logger.debug(f"Sending {len(embeds)} leaderboard embeds to channel '{channel.name}' in guild '{guild.name}'.")
                        for embed_idx, embed_to_send in enumerate(embeds):
                            image_file_for_embed = None
                            # Only attach the image to the first embed in a paginated series to avoid spamming the image
                            if image_path_to_use and embed_idx == 0: 
                                try:
                                    image_file_for_embed = discord.File(image_path_to_use, filename=os.path.basename(image_path_to_use))
                                    # embed.set_image was already called in build_leaderboard_embeds
                                except Exception as e:
                                    logger.error(f"Error preparing image file for embed in guild '{guild.name}': {e}", exc_info=True)
                                    image_file_for_embed = None
                            
                            try:
                                await channel.send(embed=embed_to_send, file=image_file_for_embed if image_file_for_embed else discord.utils.MISSING)
                                await asyncio.sleep(1.1) # Delay between sending multiple embeds
                            except discord.Forbidden:
                                logger.error(f"Bot lacks permissions to send messages/embeds/files to channel '{channel.name}' ({channel.id}) in guild '{guild.name}'. Skipping remaining embeds for this guild.")
                                break 
                            except Exception as e:
                                logger.error(f"Error sending leaderboard embed to channel '{channel.name}' ({channel.id}) in guild '{guild.name}': {e}", exc_info=True)
                                # Potentially continue to next embed or break depending on error severity
                        logger.info(f"Leaderboard updated in guild '{guild.name}'.")

                except Exception as e:
                    logger.exception(f"An overall error occurred during leaderboard update for '{guild.name}': {e}")
            
            logger.info("Completed global leaderboard update for all guilds.")

    @update_leaderboard_task.before_loop
    async def before_update_leaderboard_task(self):
        await self.bot.wait_until_ready()
        logger.info("Bot is ready. update_leaderboard_task loop is starting.")

    async def ensure_leaderboard_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        # Check for manage_channels at the guild level first
        if not guild.me.guild_permissions.manage_channels:
            logger.warning(f"Bot lacks 'Manage Channels' permission in guild '{guild.name}'. Attempting to find existing channel only.")
            # Try to find existing channel even if we can't create/edit
            leaderboard_channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
            if leaderboard_channel:
                 # If found, check its specific permissions
                channel_perms = leaderboard_channel.permissions_for(guild.me)
                required_channel_perms_list = ["send_messages", "embed_links", "attach_files", "manage_messages"]
                if all(getattr(channel_perms, perm, False) for perm in required_channel_perms_list):
                    logger.info(f"Found existing leaderboard channel '{leaderboard_channel.name}' in '{guild.name}' with sufficient permissions (bot cannot edit it).")
                    return leaderboard_channel
                else:
                    missing_channel_perms = [p for p in required_channel_perms_list if not getattr(channel_perms, p, False)]
                    logger.error(f"Found existing leaderboard channel '{leaderboard_channel.name}' in '{guild.name}', but bot lacks channel-specific permissions: {', '.join(missing_channel_perms)}. Cannot use.")
                    return None
            else: # No manage_channels perm and channel not found
                logger.warning(f"Leaderboard channel '{LEADERBOARD_CHANNEL_NAME}' not found in '{guild.name}' and bot cannot create it.")
                return None


        # Bot has manage_channels, proceed with category and channel creation/update
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            try:
                category = await guild.create_category(name=CATEGORY_NAME, reason="Creating category for GPT Hellbot features.")
                logger.info(f"Created category '{CATEGORY_NAME}' in guild '{guild.name}'.")
            except discord.Forbidden:
                logger.error(f"Bot lacks permissions to create category in guild '{guild.name}'. Leaderboard channel may be uncategorized.")
                category = None 
            except Exception as e:
                logger.error(f"Error creating category in guild '{guild.name}': {e}", exc_info=True)
                category = None

        leaderboard_channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME, category=category)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, add_reactions=False, manage_messages=True, attach_files=True, embed_links=True)
        }

        if not leaderboard_channel:
            logger.info(f"Leaderboard channel '{LEADERBOARD_CHANNEL_NAME}' not found in '{guild.name}'. Attempting to create.")
            try:
                leaderboard_channel = await guild.create_text_channel(
                    name=LEADERBOARD_CHANNEL_NAME,
                    overwrites=overwrites,
                    category=category,
                    reason="Creating leaderboard channel for GPT Hellbot."
                )
                logger.info(f"Created leaderboard channel '{LEADERBOARD_CHANNEL_NAME}' in guild '{guild.name}'.")
            except discord.Forbidden:
                logger.error(f"Bot lacks permissions to create text channel in guild '{guild.name}'.")
                return None
            except Exception as e:
                logger.error(f"Error creating text channel in guild '{guild.name}': {e}", exc_info=True)
                return None
        else: # Channel exists, ensure its settings are correct
            try:
                # Check if edits are needed
                needs_edit = False
                if leaderboard_channel.category != category: needs_edit = True
                # More robust overwrite comparison might be needed if complex
                # For now, just re-apply if any doubt or if a simpler check fails.
                # A simple check: if bot's overwrites are not what we expect.
                current_bot_overwrite = leaderboard_channel.overwrites_for(guild.me)
                expected_bot_overwrite = overwrites[guild.me]
                if not (current_bot_overwrite.view_channel == expected_bot_overwrite.view_channel and
                        current_bot_overwrite.send_messages == expected_bot_overwrite.send_messages and
                        current_bot_overwrite.manage_messages == expected_bot_overwrite.manage_messages and
                        current_bot_overwrite.attach_files == expected_bot_overwrite.attach_files and
                        current_bot_overwrite.embed_links == expected_bot_overwrite.embed_links):
                    needs_edit = True

                if needs_edit:
                    await leaderboard_channel.edit(category=category, overwrites=overwrites, reason="Updating leaderboard channel category/permissions.")
                    logger.info(f"Updated leaderboard channel '{leaderboard_channel.name}' in guild '{guild.name}'.")
                else:
                    logger.debug(f"Leaderboard channel '{leaderboard_channel.name}' in guild '{guild.name}' already configured correctly.")
            except discord.Forbidden:
                logger.error(f"Bot lacks permissions to edit channel '{leaderboard_channel.name}' in guild '{guild.name}'. Current permissions might be insufficient.")
                # Fall through to final permission check
            except Exception as e:
                logger.error(f"Error editing leaderboard channel '{leaderboard_channel.name}' in guild '{guild.name}': {e}", exc_info=True)
                # Fall through to final permission check

        # Final check of permissions in the (potentially new or existing) channel
        if leaderboard_channel: # Ensure channel is not None
            channel_perms = leaderboard_channel.permissions_for(guild.me)
            required_channel_perms_list = ["send_messages", "embed_links", "attach_files", "manage_messages"] # manage_messages for deleting old ones
            if not all(getattr(channel_perms, perm, False) for perm in required_channel_perms_list):
                missing_channel_perms = [p for p in required_channel_perms_list if not getattr(channel_perms, p, False)]
                logger.error(f"Bot does not have sufficient channel-specific permissions ({', '.join(missing_channel_perms)}) in channel '{leaderboard_channel.name}' ({leaderboard_channel.id}) in guild '{guild.name}'. Cannot use this channel.")
                return None
        else: # Should not happen if creation succeeded, but as a safeguard
            logger.error(f"Leaderboard channel object is None after creation/update attempt in '{guild.name}'.")
            return None
            
        return leaderboard_channel

    async def calculate_leaderboard_data(self):
        logger.info("Attempting to calculate leaderboard data...")
        mongo_uri = os.getenv('MONGODB_URI')
        if not mongo_uri:
            logger.error("MONGODB_URI environment variable not set. Cannot calculate leaderboard.")
            return []

        db_client = None
        try:
            if hasattr(self.bot, 'mongo_db') and self.bot.mongo_db is not None:
                # Assuming self.bot.mongo_db is already an AsyncIOMotorClient instance
                # And the database is selected like: self.bot.mongo_db.get_database("GPTHellbot")
                # Or if self.bot.mongo_db IS the database object itself:
                if isinstance(self.bot.mongo_db, AsyncIOMotorClient): # If it's the client
                     db = self.bot.mongo_db['GPTHellbot']
                else: # Assume it's the database object directly
                     db = self.bot.mongo_db 
                logger.debug("Using bot's existing MongoDB connection/database.")
            else:
                logger.warning("Bot's MongoDB client not found or not initialized. Creating a new client for leaderboard calculation.")
                db_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000) # Add timeout
                await db_client.admin.command('ping') # Verify connection
                db = db_client['GPTHellbot']
                logger.info("Successfully connected to MongoDB with new client.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}", exc_info=True)
            if db_client:
                db_client.close() # Close client if created here and failed
            return []

        stats_collection = db['User_Stats']
        alliance_collection = db['Alliance']
        player_data = defaultdict(lambda: {"kills": 0, "deaths": 0, "shots_fired": 0, "shots_hit": 0, "games_played": 0, "Clan": "Unknown Clan", "player_doc_ids": []})
        server_map = {}
        leaderboard_list = []

        try:
            # Fetch Alliance Data
            alliance_servers_cursor = alliance_collection.find({}, {"discord_server_id": 1, "server_name": 1})
            alliance_servers = await alliance_servers_cursor.to_list(length=None) # Fetch all
            if not alliance_servers:
                logger.warning("No alliance server entries found in 'Alliance' collection. Clan names may be 'Unknown Clan'.")
            else:
                for srv in alliance_servers:
                    s_id = srv.get("discord_server_id")
                    s_name = srv.get("server_name")
                    if s_id and s_name:
                        server_map[str(s_id)] = s_name # Ensure server_id is stored as string key
                    else:
                        logger.warning(f"Alliance document missing discord_server_id or server_name: {srv}")
            logger.info(f"Fetched {len(alliance_servers)} alliance server entries. Mapped {len(server_map)} servers.")
            if len(alliance_servers) > 0: logger.debug(f"Server Map: {pprint.pformat(server_map)}")


            # Fetch User Stats
            # IMPORTANT: Ensure your User_Stats documents have the correct fields and types!
            # Fields expected: player_name (str), Kills (int/str), Deaths (int/str),
            #                  Shots Fired (int/str), Shots Hit (int/str), discord_server_id (str/int)
            stats_cursor = stats_collection.find({})
            all_players_stats_docs = await stats_cursor.to_list(length=None) # Fetch all
            
            logger.info(f"Fetched {len(all_players_stats_docs)} documents from 'User_Stats'.")
            if not all_players_stats_docs:
                logger.warning("No documents found in 'User_Stats' collection. Leaderboard will be empty.")
                if db_client: db_client.close() # Close client if created here
                return []
            
            # Log a sample of the first few documents to help diagnose field name/type issues
            if len(all_players_stats_docs) > 0:
                logger.debug(f"Sample User_Stats document (first one): {pprint.pformat(all_players_stats_docs[0])}")
                if len(all_players_stats_docs) > 1:
                     logger.debug(f"Sample User_Stats document (second one if exists): {pprint.pformat(all_players_stats_docs[1])}")


            for p_doc in all_players_stats_docs:
                player_name = p_doc.get('player_name')
                if not player_name:
                    logger.warning(f"User_Stats document missing 'player_name'. Doc ID: {p_doc.get('_id')}. Skipping this document.")
                    continue

                # Robust stat conversion
                try:
                    kills = int(p_doc.get('Kills', 0) or 0)
                    deaths = int(p_doc.get('Deaths', 0) or 0)
                    shots_fired = int(p_doc.get('Shots Fired', 0) or 0)
                    shots_hit = int(p_doc.get('Shots Hit', 0) or 0)
                except ValueError as ve:
                    logger.warning(f"Could not convert stats to int for player '{player_name}', doc ID {p_doc.get('_id')}. Stats: K='{p_doc.get('Kills')}', D='{p_doc.get('Deaths')}', SF='{p_doc.get('Shots Fired')}', SH='{p_doc.get('Shots Hit')}'. Error: {ve}. Treating problematic stat as 0 for this record.")
                    # Attempt to salvage what we can, or default all to 0 for this record if critical
                    kills = int(p_doc.get('Kills', 0)) if str(p_doc.get('Kills','0')).isdigit() else 0
                    deaths = int(p_doc.get('Deaths', 0)) if str(p_doc.get('Deaths','0')).isdigit() else 0
                    shots_fired = int(p_doc.get('Shots Fired', 0)) if str(p_doc.get('Shots Fired','0')).isdigit() else 0
                    shots_hit = int(p_doc.get('Shots Hit', 0)) if str(p_doc.get('Shots Hit','0')).isdigit() else 0
                except TypeError as te: # Handles if p_doc.get() returns None and int(None) is attempted
                    logger.warning(f"TypeError during stat conversion for player '{player_name}', doc ID {p_doc.get('_id')}. Error: {te}. Treating as 0 for this record.")
                    kills, deaths, shots_fired, shots_hit = 0,0,0,0


                player_data[player_name]["kills"] += kills
                player_data[player_name]["deaths"] += deaths
                player_data[player_name]["shots_fired"] += shots_fired
                player_data[player_name]["shots_hit"] += shots_hit
                player_data[player_name]["games_played"] += 1 # Assuming one doc = one game
                player_data[player_name]["player_doc_ids"].append(str(p_doc.get('_id')))


                # Clan Association
                # Ensure discord_server_id in User_Stats is a string if keys in server_map are strings
                raw_server_id = p_doc.get('discord_server_id')
                if raw_server_id is not None:
                    # Convert to string for consistent lookup, as server_map keys are strings
                    doc_server_id_str = str(raw_server_id) 
                    if doc_server_id_str in server_map:
                        # Only update clan if it's not already set by another game from the same clan,
                        # or if the current clan is "Unknown Clan"
                        if player_data[player_name]["Clan"] == "Unknown Clan" or player_data[player_name]["Clan"] == server_map[doc_server_id_str]:
                            player_data[player_name]["Clan"] = server_map[doc_server_id_str]
                        # else:
                            # logger.debug(f"Player '{player_name}' associated with multiple clans. Sticking with first identified: {player_data[player_name]['Clan']}")
                    elif player_data[player_name]["Clan"] == "Unknown Clan": # Only log if not already found in a previous game for this player
                        logger.warning(f"Server ID '{doc_server_id_str}' for player '{player_name}' (Doc ID: {p_doc.get('_id')}) not found in alliance server_map. Keys available: {list(server_map.keys())}")
                elif player_data[player_name]["Clan"] == "Unknown Clan":
                     logger.debug(f"Document for player '{player_name}' (Doc ID: {p_doc.get('_id')}) has no 'discord_server_id'.")


            logger.info(f"Processed {len(player_data)} unique players from User_Stats.")
            if len(player_data) > 0: logger.debug(f"Aggregated player data (first few if many): {pprint.pformat(dict(list(player_data.items())[:5]))}")

            # Filter and finalize leaderboard
            for name, data in player_data.items():
                if data["games_played"] >= MIN_GAMES_PLAYED:
                    accuracy = (data["shots_hit"] / data["shots_fired"] * 100) if data["shots_fired"] > 0 else 0.0
                    leaderboard_list.append({
                        "player_name": name,
                        "kills": data["kills"],
                        "deaths": data["deaths"],
                        "shots_fired": data["shots_fired"],
                        "shots_hit": data["shots_hit"],
                        "games_played": data["games_played"],
                        "Clan": data["Clan"],
                        "accuracy": accuracy,
                        # "doc_ids": data["player_doc_ids"] # Optional: for debugging which docs contributed
                    })
                else:
                    logger.debug(f"Player '{name}' has {data['games_played']} games, less than minimum {MIN_GAMES_PLAYED}. Not added to leaderboard.")
            
            if not leaderboard_list:
                logger.warning(f"No players met the minimum {MIN_GAMES_PLAYED} games requirement. Leaderboard will be empty.")
            else:
                # Sort: 1. Least Deaths (ascending), 2. Most Kills (descending), 3. Best Accuracy (descending)
                leaderboard_list.sort(key=lambda x: (x["deaths"], -x["kills"], -x["accuracy"]))
                logger.info(f"Calculated leaderboard data for {len(leaderboard_list)} eligible players.")
                logger.debug(f"Final sorted leaderboard list (first few if many): {pprint.pformat(leaderboard_list[:5])}")

        except Exception as e:
            logger.error(f"Error during MongoDB data retrieval or processing for leaderboard: {e}", exc_info=True)
            leaderboard_list = [] # Ensure empty list on error
        finally:
            if db_client: # If we created a client in this function, close it.
                db_client.close()
                logger.info("Closed temporary MongoDB client.")
        
        return leaderboard_list

    async def build_leaderboard_embeds(self, leaderboard_data):
        embeds = []
        batch_size = 10 # Reduced batch size per embed to avoid hitting embed field limits or total length too quickly
        total_players = len(leaderboard_data)
        
        image_path_to_use = None
        image_filename = None
        if os.path.exists(LEADERBOARD_IMAGE_PATH):
            image_path_to_use = LEADERBOARD_IMAGE_PATH
            image_filename = os.path.basename(LEADERBOARD_IMAGE_PATH)
            logger.debug(f"Leaderboard image found at: {image_path_to_use}")
        else:
            logger.warning(f"Leaderboard image file not found at path: {LEADERBOARD_IMAGE_PATH}. Embeds will not have an image.")

        if total_players == 0:
            # No data, task loop will handle sending a "no data" message.
            # This function will return an empty list of embeds.
            logger.debug("build_leaderboard_embeds: No data, returning empty embeds list.")
            return [], image_path_to_use # image_path_to_use is still relevant for the "no data" embed

        num_pages = (total_players + batch_size - 1) // batch_size

        for page_idx in range(num_pages):
            start_idx = page_idx * batch_size
            end_idx = start_idx + batch_size
            batch = leaderboard_data[start_idx:end_idx]

            embed = discord.Embed(
                title=f"**MAY ALLIANCE LEADERBOARD**\n*(Least Deaths, Most Kills, Best Accuracy)*",
                color=discord.Color.blue()
            )
            if num_pages > 1:
                embed.title += f"\n(Page {page_idx + 1}/{num_pages})"
            
            embed.set_footer(text="Leaderboard updates every 24 hours. Must submit (3) games to appear.")

            # Only set image on the first page/embed
            if image_path_to_use and image_filename and page_idx == 0:
                embed.set_image(url=f"attachment://{image_filename}")
            
            description_parts = []
            for rank, player in enumerate(batch, start=start_idx + 1):
                # Using f-strings and explicit field formatting for clarity
                rank_emoji = ""
                if page_idx == 0: # Only show emojis for the first page
                    if rank == 1: rank_emoji = "🥇 "
                    elif rank == 2: rank_emoji = "🥈 "
                    elif rank == 3: rank_emoji = "🥉 "

                # Format for each player
                # Using zero-width spaces or careful formatting if names are very long
                player_name_display = player['player_name']
                if len(player_name_display) > 25: # Truncate very long names for display
                    player_name_display = player_name_display[:22] + "..."

                field_name = f"{rank_emoji}#{rank}. {player_name_display}"
                field_value = (
                    f"**Clan:** {player.get('Clan', 'N/A')}\n"
                    f"**Deaths:** {player['deaths']}\n"
                    f"**Kills:** {player['kills']}\n"
                    f"**Accuracy:** {player['accuracy']:.1f}%\n"
                    f"**Shots Hit:** ({player['shots_hit']}\n"
                    f"**Shots Fired:** ({player['shots_fired']})\n"
                    f"*Games: {player['games_played']}*"
                )
                # Discord embed fields have limits on name (256 chars) and value (1024 chars)
                # Adding fields one by one. Inline works best for 3-wide.
                # Check if adding this field would exceed total fields limit (25)
                if len(embed.fields) < 25:
                     embed.add_field(name=field_name, value=field_value, inline=True) # Try inline=True
                else:
                    logger.warning("Reached maximum embed fields (25). Some players might not be displayed on this page.")
                    break # Stop adding fields to this embed
            
            # Check for total embed length (6000 chars) - less common with paginated fields
            if len(embed) > 5900 : # Check total length; discord.Embed has a __len__
                logger.warning(f"Embed page {page_idx+1} is too long ({len(embed)} chars). May not send correctly.")
                # Potentially, you might need to split this batch further if this happens
            
            embeds.append(embed)
            if len(embeds) * batch_size >= 50 and page_idx < num_pages -1 : # Safety break if too many players/embeds for one message cycle.
                logger.warning(f"Generating many embeds ({len(embeds)}), stopping early to prevent issues. Only first ~50 players shown if batch size is 1.")
                break


        logger.info(f"Built {len(embeds)} leaderboard embeds.")
        return embeds, image_path_to_use


async def setup(bot):
    if not hasattr(bot, 'mongo_db') or bot.mongo_db is None:
        logger.critical("MongoDB client ('mongo_db') not found in bot object during LeaderboardCog setup. THIS COG REQUIRES IT AND CANNOT BE LOADED.")
        raise RuntimeError("LeaderboardCog requires bot.mongo_db to be initialized.") # More forceful
    
    # You might want to pass the MONGODB_URI to the cog if it's not always using bot.mongo_db
    # or if you want the cog to manage its own client entirely.
    # For now, it assumes bot.mongo_db is preferred.
    await bot.add_cog(LeaderboardCog(bot))
    logger.info("LeaderboardCog loaded successfully.")