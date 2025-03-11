import discord
from discord.ext import commands
import logging

class GuildManagementCog(commands.Cog):
    """
    A cog to manage guild setup and configurations, including a #leaderboard channel
    that is fully read-only for everyone except the bot.
    """

    def __init__(self, bot):
        self.bot = bot

    async def setup_guild(self, guild: discord.Guild, force_refresh=False):
        """
        Ensure a guild has the necessary setup and configurations:
          - 'GPT NETWORK' category
          - #gpt-network read-only channel (public, no reactions)
          - GPT STAT ACCESS role (with permission to use application commands)
          - #monitor & #stats-log channels visible only to GPT STAT ACCESS + bot (no reactions)
          - #leaderboard channel, read-only to everyone but the bot
          - A new embedded "how-to-submit-stats" message in #stats-log (delete old bot messages if force_refresh)
          - Finally, store all relevant IDs in the Server_Listing collection.
        """
        category_name = "GPT NETWORK"
        gpt_channel_name = "gpt-network"
        monitor_channel_name = "monitor"
        stats_log_channel_name = "stats-log"
        leaderboard_channel_name = "leaderboard"

        logging.info(f"Starting setup for guild: {guild.name} (ID: {guild.id})")

        bot_member = guild.me
        if not bot_member.guild_permissions.manage_channels:
            logging.warning(
                f"Bot lacks channel-management permissions in guild '{guild.name}'. Skipping setup."
            )
            return

        # ----------------------------------------------------------------------
        # 1) Create (or retrieve) GPT NETWORK category with default overwrites
        # ----------------------------------------------------------------------
        category_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                connect=True,
                add_reactions=False  # No reactions for everyone
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True   # Bot can react if desired
            )
        }

        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(
                    name=category_name,
                    overwrites=category_overwrites
                )
                logging.info(f"Created category '{category.name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating category '{category_name}' in guild '{guild.name}': {e}")
                return
        else:
            try:
                await category.edit(overwrites=category_overwrites)
                logging.info(f"Updated permission overwrites for category '{category.name}'.")
            except Exception as e:
                logging.warning(f"Could not update category overwrites for '{category_name}': {e}")

        # ----------------------------------------------------------------------
        # 2) Create (or retrieve) the #gpt-network channel (public read-only, no reactions)
        # ----------------------------------------------------------------------
        gpt_channel_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True
            )
        }
        gpt_channel = discord.utils.get(guild.text_channels, name=gpt_channel_name)
        if not gpt_channel:
            try:
                gpt_channel = await guild.create_text_channel(
                    name=gpt_channel_name,
                    overwrites=gpt_channel_overwrites,
                    category=category
                )
                logging.info(f"Created channel '#{gpt_channel_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating channel '#{gpt_channel_name}' in guild '{guild.name}': {e}")
                return
        else:
            try:
                await gpt_channel.edit(category=category, overwrites=gpt_channel_overwrites)
                logging.info(f"Updated channel '#{gpt_channel_name}' overwrites.")
            except Exception as e:
                logging.error(f"Error editing '#{gpt_channel_name}' in guild '{guild.name}': {e}")

        # ----------------------------------------------------------------------
        # 3) Create (or refresh) a permanent invite link for #gpt-network
        # ----------------------------------------------------------------------
        try:
            invite = await gpt_channel.create_invite(max_age=0, max_uses=0, unique=True)
            discord_invite_link = invite.url
        except Exception as e:
            logging.error(f"Error creating invite link for '#{gpt_channel_name}': {e}")
            discord_invite_link = ""

        # ----------------------------------------------------------------------
        # 4) Create (or retrieve) GPT STAT ACCESS role (use_application_commands = True)
        # ----------------------------------------------------------------------
        gpt_stat_access_role = discord.utils.get(guild.roles, name="GPT STAT ACCESS")
        if not gpt_stat_access_role:
            try:
                permissions = discord.Permissions.none()
                permissions.use_application_commands = True
                gpt_stat_access_role = await guild.create_role(
                    name="GPT STAT ACCESS",
                    mentionable=True,
                    permissions=permissions,
                    reason="Role for stats access, including slash commands."
                )
                logging.info(f"Created role 'GPT STAT ACCESS' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating role 'GPT STAT ACCESS' in guild '{guild.name}': {e}")
                return
        else:
            logging.info("Role 'GPT STAT ACCESS' already exists.")
            # Ensure it has permission to use slash commands
            try:
                current_perms = gpt_stat_access_role.permissions
                if not current_perms.use_application_commands:
                    current_perms.update(use_application_commands=True)
                    await gpt_stat_access_role.edit(
                        permissions=current_perms,
                        reason="Enabling slash commands for GPT STAT ACCESS role"
                    )
                    logging.info(
                        "Updated GPT STAT ACCESS role to allow use of slash commands in guild "
                        f"'{guild.name}'."
                    )
            except Exception as e:
                logging.error(f"Failed to set use_application_commands for GPT STAT ACCESS role: {e}")

        # ----------------------------------------------------------------------
        # 5) Create (or update) #monitor channel (hidden except GPT STAT ACCESS + bot, no reactions)
        # ----------------------------------------------------------------------
        monitor_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                add_reactions=False
            ),
            gpt_stat_access_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True
            )
        }
        monitor_channel = discord.utils.get(guild.text_channels, name=monitor_channel_name)
        if not monitor_channel:
            try:
                monitor_channel = await guild.create_text_channel(
                    name=monitor_channel_name,
                    overwrites=monitor_overwrites,
                    category=category,
                    reason="Monitor channel for GPT STAT ACCESS role"
                )
                logging.info(f"Created channel '#{monitor_channel_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating '#{monitor_channel_name}' in guild '{guild.name}': {e}")
        else:
            try:
                await monitor_channel.edit(category=category, overwrites=monitor_overwrites)
                logging.info(f"Updated '#{monitor_channel_name}' overwrites.")
            except Exception as e:
                logging.warning(f"Could not update '#{monitor_channel_name}' overwrites: {e}")

        # ----------------------------------------------------------------------
        # 6) Create (or update) #stats-log (hidden except GPT STAT ACCESS + bot, no reactions)
        # ----------------------------------------------------------------------
        stats_log_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                add_reactions=False
            ),
            gpt_stat_access_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True
            )
        }
        stats_log_channel = discord.utils.get(guild.text_channels, name=stats_log_channel_name)
        if not stats_log_channel:
            try:
                stats_log_channel = await guild.create_text_channel(
                    name=stats_log_channel_name,
                    overwrites=stats_log_overwrites,
                    category=category,
                    reason="Stats log channel for GPT STAT ACCESS role"
                )
                logging.info(f"Created channel '#{stats_log_channel_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating '#{stats_log_channel_name}' in guild '{guild.name}': {e}")
                return
        else:
            try:
                await stats_log_channel.edit(category=category, overwrites=stats_log_overwrites)
                logging.info(f"Updated '#{stats_log_channel_name}' overwrites.")
            except Exception as e:
                logging.warning(f"Could not update '#{stats_log_channel_name}' overwrites: {e}")

        # ----------------------------------------------------------------------
        # 7) Create (or update) #leaderboard (read-only to everyone except bot)
        # ----------------------------------------------------------------------
        leaderboard_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True
            )
        }
        leaderboard_channel = discord.utils.get(guild.text_channels, name=leaderboard_channel_name)
        if not leaderboard_channel:
            try:
                leaderboard_channel = await guild.create_text_channel(
                    name=leaderboard_channel_name,
                    overwrites=leaderboard_overwrites,
                    category=category,
                    reason="Leaderboard channel (read-only)"
                )
                logging.info(f"Created channel '#{leaderboard_channel_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating '#{leaderboard_channel_name}' in guild '{guild.name}': {e}")
        else:
            try:
                await leaderboard_channel.edit(category=category, overwrites=leaderboard_overwrites)
                logging.info(f"Updated '#{leaderboard_channel_name}' overwrites.")
            except Exception as e:
                logging.warning(f"Could not update '#{leaderboard_channel_name}' overwrites: {e}")

        # ----------------------------------------------------------------------
        # 8) If force_refresh, delete old bot messages in #stats-log, then send new embed
        # ----------------------------------------------------------------------
        if stats_log_channel and force_refresh:
            try:
                deleted_messages = 0
                async for message in stats_log_channel.history(limit=100):
                    if message.author == self.bot.user:
                        await message.delete()
                        deleted_messages += 1
                logging.info(f"Deleted {deleted_messages} old bot messages in '#{stats_log_channel_name}'.")
            except Exception as e:
                logging.error(f"Error deleting old messages in '#{stats_log_channel_name}': {e}")

            # Send a fresh instructions embed
            embed_description = (
                "Welcome to **#stats-log**! Here you submit your mission stats for the alliance leaderboard.\n\n"
                "**How to Submit Stats:**\n\n"
                "**MUST BE A FULL SQUAD - NO INDIVIDUALS OR LESS THAN 4**\n"
                "0. Type in *this* channel: `/extract`\n"
                "1. Use a **full-screen capture** (CTRL+PRINT SCREEN, then CTRL+V into the prompt) and press enter.\n"
                "2. After a few moments, review the scanned results to ensure accuracy.\n"
                "3. If something is wrong, use **EDIT** (Player #, Stat type) to correct it before final submit.\n"
                "4. Only **1280×800**, **1920×1080 and up** resolutions are supported (no wide screens!). Snippets will be rejected.\n"
                "5. After submission, check **#monitor** to verify your stats.\n"
                "6. Mistakes? Simply post in this channel with the screenshot and the error.\n\n"
                "The bot is ~99.9% accurate, but we rely on your diligence to confirm correctness!"
            )
            stats_embed = discord.Embed(
                title="How to Submit Mission Stats",
                description=embed_description,
                color=discord.Color.blue()
            )
            try:
                await stats_log_channel.send(embed=stats_embed)
                logging.info(f"Posted updated instructions embed in '#{stats_log_channel_name}'.")
            except Exception as e:
                logging.error(f"Error sending embed in '#{stats_log_channel_name}': {e}")

        # ----------------------------------------------------------------------
        # 9) Store all relevant data in the DB (Server_Listing) for future use
        # ----------------------------------------------------------------------
        server_listing = self.bot.mongo_db["Server_Listing"]
        update_data = {
            "discord_server_id": guild.id,
            "discord_server_name": guild.name,
            "category_id": category.id if category else None,
            "gpt_channel_id": gpt_channel.id if gpt_channel else None,
            "discord_invite_link": discord_invite_link,
            "gpt_stat_access_role_id": gpt_stat_access_role.id if gpt_stat_access_role else None,
            "monitor_channel_id": monitor_channel.id if monitor_channel else None,
            "stats_log_channel_id": stats_log_channel.id if stats_log_channel else None,
            # new field:
            "leaderboard_channel_id": leaderboard_channel.id if leaderboard_channel else None,
        }

        try:
            await server_listing.update_one(
                {"discord_server_id": guild.id},
                {"$set": update_data},
                upsert=True
            )
            logging.info(f"Upserted server data (channels, role IDs) for guild '{guild.name}'.")
        except Exception as e:
            logging.error(f"Error updating server listing for '{guild.name}': {e}")

        # ----------------------------------------------------------------------
        # 10) Optionally refresh the SOS menu in #gpt-network (original logic)
        # ----------------------------------------------------------------------
        await self.refresh_sos_menu(guild, force_refresh)

    async def refresh_sos_menu(self, guild, force_refresh=False):
        """
        Refresh the SOS menu in the gpt-network channel of the specified guild.
        """
        menu_view_cog = self.bot.get_cog("MenuViewCog")
        if not menu_view_cog:
            logging.warning("MenuViewCog is not loaded. Cannot refresh SOS menu.")
            return

        server_listing = self.bot.mongo_db['Server_Listing']
        server_data = await server_listing.find_one({"discord_server_id": guild.id})
        if not server_data:
            logging.warning(f"Server data for guild '{guild.name}' not found.")
            return

        gpt_channel = guild.get_channel(server_data.get("gpt_channel_id"))
        if not gpt_channel:
            logging.warning(
                f"GPT channel for guild '{guild.name}' not found. "
                f"Channel ID: {server_data.get('gpt_channel_id')}"
            )
            return

        if force_refresh:
            try:
                if not gpt_channel.permissions_for(guild.me).manage_messages:
                    logging.warning(
                        f"Bot lacks 'Manage Messages' permission in '{gpt_channel.name}'. "
                        f"Skipping message deletion."
                    )
                else:
                    deleted_messages = 0
                    async for message in gpt_channel.history(limit=100):
                        if message.author == self.bot.user:
                            await message.delete()
                            deleted_messages += 1
                            if deleted_messages >= 10:
                                break
                    logging.info(f"Deleted {deleted_messages} bot messages in '{gpt_channel.name}'.")
            except Exception as e:
                logging.error(f"Error deleting messages in '{gpt_channel.name}': {e}")

        try:
            await menu_view_cog.send_sos_menu_to_guild(guild)
            logging.info(f"Sent SOS menu to '{guild.name}'.")
        except Exception as e:
            logging.error(f"Error sending SOS menu to '{guild.name}': {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("GuildManagementCog is ready.")
        if not hasattr(self.bot, 'guild_setup_done'):
            self.bot.guild_setup_done = True
            for guild in self.bot.guilds:
                logging.info(f"Checking setup for guild: {guild.name} (ID: {guild.id})")
                try:
                    await self.setup_guild(guild, force_refresh=True)
                except Exception as e:
                    logging.error(f"Error setting up guild '{guild.name}': {e}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """When the bot joins a new guild, set up the guild immediately."""
        logging.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        try:
            await self.setup_guild(guild, force_refresh=True)
        except Exception as e:
            logging.error(f"Error setting up new guild '{guild.name}': {e}")


async def setup(bot):
    await bot.add_cog(GuildManagementCog(bot))
