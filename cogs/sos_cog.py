# sos_cog.py
import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime
from cogs.sos_view import SOSView
import time

class SOSCog(commands.Cog):
    """
    A cog to manage SOS creation and related functionality.
    Now excludes the Discord links in the embed, replacing them with plain text.
    """
    def __init__(self, bot):
        self.bot = bot
        self.voice_channels = {}  # Track created voice channels
        self.sos_data_by_channel = {}  # Map voice channel IDs to SOS data
        self.cleanup_tasks = {}  # Map voice channel IDs to their cleanup tasks

    def get_sos_view(self):
        """Returns an instance of the SOSView."""
        return SOSView(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("SOSCog is ready.")

    async def check_bot_permissions(self, guild: discord.Guild):
        """Verify the bot has the required permissions in a guild."""
        permissions = guild.me.guild_permissions
        required_perms = ["manage_channels", "send_messages", "embed_links"]
        missing_perms = [
            perm for perm in required_perms if not getattr(permissions, perm, False)
        ]
        if missing_perms:
            logging.warning(f"Missing permissions in guild '{guild.name}': {', '.join(missing_perms)}")
            return False
        return True

    async def get_or_create_category(self, guild: discord.Guild, category_name: str = "GPT NETWORK"):
        """Retrieves or creates a dedicated category for GPT voice channels."""
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            try:
                category = await guild.create_category(name=category_name)
                logging.info(f"Created category '{category_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Failed to create category in guild '{guild.name}': {e}")
                return None
        return category

    async def launch_sos(self, interaction: discord.Interaction):
        """Handles the 'Launch SOS' action with OPEN parameters (no defaults)."""
        try:
            sos_view_cog = self.bot.get_cog("SOSViewCog")
            if sos_view_cog:
                view = sos_view_cog.get_sos_view()
            else:
                view = SOSView(self.bot)

            # No default parameters
            view.enemy_type = None
            view.difficulty = None
            view.mission = None
            view.voice = None
            view.notes = None

            # Defer interaction to prevent timeout
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            # Directly process the SOS with all fields open
            await self.process_sos(interaction, view)
        except Exception as e:
            logging.error(f"An unexpected error occurred in launch_sos: {e}")
            await interaction.followup.send(
                "An unexpected error occurred while processing your request. Please try again later.",
                ephemeral=True
            )

    async def process_sos(self, interaction: discord.Interaction, view: SOSView):
        """
        Process the creation of an SOS and broadcast it to all servers' GPT network channels.
        """
        sos_data = None
        try:
            sos_collection = self.bot.mongo_db['User_SOS']

            # Remove the "identical SOS" check to allow multiple identical SOS.
            # -----------------------------------------------------------------
            # existing_sos = await sos_collection.find_one({
            #     "discord_id": interaction.user.id,
            #     "enemy": view.enemy_type,
            #     "difficulty": view.difficulty,
            #     "mission": view.mission,
            #     "voice": view.voice,
            #     "notes": view.notes or ""
            # })
            # if existing_sos:
            #     await interaction.followup.send(
            #         "An identical SOS already exists. No new SOS was created.",
            #         ephemeral=True
            #     )
            #     return
            # -----------------------------------------------------------------

            sos_document = {
                "discord_id": interaction.user.id,
                "user_nickname": interaction.user.display_name,
                "created_at": datetime.utcnow(),
                "enemy": view.enemy_type,
                "difficulty": view.difficulty,
                "mission": view.mission,
                "voice": view.voice,
                "notes": view.notes or ""
            }

            # Insert the new SOS into the database unconditionally
            await sos_collection.insert_one(sos_document)

            host_guild = interaction.guild
            if not await self.check_bot_permissions(host_guild):
                await interaction.followup.send(
                    "Bot is missing necessary permissions to create channels or send messages.",
                    ephemeral=True
                )
                return

            # Get or create GPT category
            category = await self.get_or_create_category(host_guild, "GPT NETWORK")
            if not category:
                await interaction.followup.send(
                    "Unable to create/find the GPT NETWORK category. Please check my permissions.",
                    ephemeral=True
                )
                return

            # Generate unique name for the voice channel
            existing_channels = [
                c.name for c in host_guild.voice_channels if c.name.startswith("SOS QRF#")
            ]
            next_number = (
                max(
                    [
                        int(c.split("#")[-1])
                        for c in existing_channels
                        if c.split("#")[-1].isdigit()
                    ],
                    default=0
                ) + 1
            )
            voice_channel_name = f"SOS QRF#{next_number}"

            overwrites = {
                host_guild.default_role: discord.PermissionOverwrite(
                    connect=True, speak=True, view_channel=True, use_voice_activation=True
                )
            }

            # Create the voice channel under the dedicated category
            voice_channel = await host_guild.create_voice_channel(
                name=voice_channel_name, overwrites=overwrites, user_limit=99, category=category
            )

            # Track the voice channel
            self.voice_channels[voice_channel.id] = voice_channel
            logging.debug(f"Added voice channel {voice_channel.id} to tracking.")

            # Create an invite link (1-hour expiry)
            invite = await voice_channel.create_invite(max_age=3600, max_uses=0)
            invite_url = invite.url

            sos_data = {
                "users": {interaction.user.id: interaction.user.display_name},
                "embed": None,
                "status_index": None,
                "fleet_response_index": None,
                "voice_channel": voice_channel,
                "lock": asyncio.Lock(),
                "sos_messages": {},
                "initiator_id": interaction.user.id,
                "last_activity": time.time(),
                "prompted_users": set(),
                "dm_messages": {}
            }

            fleet_response = '\n'.join(sos_data['users'].values())

            embed = discord.Embed(
                title="SOS ACTIVATED",
                description=(
                    f"**Comms:**: [Join Now]({invite_url})\n\n"
                    f"**Enemy:** {view.enemy_type or 'Open'}\n"
                    f"**Difficulty:** {view.difficulty or 'Open'}\n"
                    f"**Mission Focus:** {view.mission or 'Open'}\n"
                    f"**Voice:** {view.voice or 'Open'}\n"
                    f"**Notes:** {view.notes or 'None'}\n\n"
                ),
                color=discord.Color.red()
            )
            embed.add_field(name="HOST CLAN", value=host_guild.name, inline=False)
            embed.add_field(name="Status", value="**Open**", inline=False)
            status_index = len(embed.fields) - 1
            embed.add_field(name="Fleet Response", value=fleet_response, inline=False)
            fleet_response_index = len(embed.fields) - 1

            sos_data['embed'] = embed
            sos_data['status_index'] = status_index
            sos_data['fleet_response_index'] = fleet_response_index

            # Broadcast to all known GPT channels in the network
            server_listing = self.bot.mongo_db['Server_Listing']
            all_servers = await server_listing.find({}).to_list(None)
            for server_data in all_servers:
                server_guild_id = server_data.get("discord_server_id")
                server_gpt_channel_id = server_data.get("gpt_channel_id")

                server_guild = self.bot.get_guild(server_guild_id)
                if not server_guild:
                    continue

                server_gpt_channel = server_guild.get_channel(server_gpt_channel_id)
                if not server_gpt_channel:
                    continue

                try:
                    sos_message = await server_gpt_channel.send(embed=embed)
                    sos_data['sos_messages'][server_guild.id] = sos_message
                except Exception as e:
                    logging.error(f"Error sending SOS embed to guild '{server_guild.name}': {e}")

            self.sos_data_by_channel[voice_channel.id] = sos_data
            logging.debug(f"Added sos_data for channel {voice_channel.id} to tracking.")

            # Confirm to the user
            await interaction.followup.send(
                f"Your SOS has been launched and broadcast. Voice channel '{voice_channel.name}' is open in '{category.name}'.",
                ephemeral=True
            )

        except Exception as e:
            logging.error(f"Error in process_sos: {e}")
            if sos_data is not None:
                logging.debug(f"sos_data: {sos_data}")
            await interaction.followup.send(
                "An error occurred while processing your SOS request. Please try again later.",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Monitor voice channel activity and manage cleanup timers."""
        # Member joined a voice channel
        if after.channel and after.channel.id in self.voice_channels:
            voice_channel_id = after.channel.id
            # Cancel any pending cleanup task for this channel
            cleanup_task = self.cleanup_tasks.pop(voice_channel_id, None)
            if cleanup_task and not cleanup_task.done():
                cleanup_task.cancel()
                logging.debug(f"Cancelled cleanup task for channel {voice_channel_id} because a member joined.")

            sos_data = self.sos_data_by_channel.get(voice_channel_id)
            if sos_data:
                async with sos_data['lock']:
                    status_field = sos_data['embed'].fields[sos_data['status_index']]
                    if status_field.value != '**Closed**':
                        if member.id not in sos_data['users']:
                            sos_data['users'][member.id] = member.display_name
                            fleet_response = '\n'.join(sos_data['users'].values())
                            sos_data['embed'].set_field_at(
                                index=sos_data['fleet_response_index'],
                                name='Fleet Response',
                                value=fleet_response,
                                inline=False
                            )
                            if len(sos_data['users']) >= 4:
                                sos_data['embed'].set_field_at(
                                    index=sos_data['status_index'],
                                    name='Status',
                                    value='**Closed**',
                                    inline=False
                                )
                            for msg in sos_data['sos_messages'].values():
                                await msg.edit(embed=sos_data['embed'])

        # Member left a voice channel
        if before.channel and before.channel.id in self.voice_channels:
            voice_channel_id = before.channel.id
            voice_channel = self.voice_channels[voice_channel_id]
            if len(voice_channel.members) == 0:
                # Schedule cleanup if it's not already scheduled
                if voice_channel_id not in self.cleanup_tasks:
                    cleanup_task = asyncio.create_task(self.schedule_cleanup(voice_channel_id, 60))
                    self.cleanup_tasks[voice_channel_id] = cleanup_task
                    logging.debug(f"Scheduled cleanup task for channel {voice_channel_id} in 60 seconds.")

    async def schedule_cleanup(self, channel_id, delay):
        try:
            await asyncio.sleep(delay)
            voice_channel = self.voice_channels.get(channel_id)
            if voice_channel and len(voice_channel.members) == 0:
                await self.delete_voice_channel_and_message(channel_id)
                logging.debug(f"Cleaned up channel {channel_id} after {delay} seconds of inactivity.")
                self.cleanup_tasks.pop(channel_id, None)
        except asyncio.CancelledError:
            logging.debug(f"Cleanup task for channel {channel_id} was cancelled.")

    async def delete_voice_channel_and_message(self, channel_id):
        """Delete the voice channel and its associated SOS embeds from all servers."""
        sos_data = self.sos_data_by_channel.pop(channel_id, None)
        voice_channel = self.voice_channels.pop(channel_id, None)
        if not voice_channel:
            logging.warning(f"Voice channel with ID {channel_id} not found. Skipping deletion.")
            return

        if len(voice_channel.members) > 0:
            logging.info(f"Voice channel '{voice_channel.name}' still has members. Skipping deletion.")
            return

        logging.info(f"Deleting inactive voice channel: {voice_channel.name}")

        if sos_data:
            for guild_id, sos_message in sos_data.get("sos_messages", {}).items():
                try:
                    await sos_message.delete()
                    logging.info(f"Deleted SOS embed in guild ID {guild_id}")
                except discord.NotFound:
                    logging.warning(f"Embed in guild ID {guild_id} already deleted or not found.")
                except Exception as e:
                    logging.error(f"Error deleting embed in guild ID {guild_id}: {e}")

        try:
            await voice_channel.delete()
            logging.info(f"Deleted voice channel: {voice_channel.name}")
        except discord.Forbidden:
            logging.error(f"Permission denied to delete voice channel: {voice_channel.name}")
        except discord.NotFound:
            logging.warning(f"Voice channel '{voice_channel.name}' already deleted.")
        except Exception as e:
            logging.error(f"Failed to delete voice channel '{voice_channel.name}': {e}")


async def setup(bot):
    await bot.add_cog(SOSCog(bot))
