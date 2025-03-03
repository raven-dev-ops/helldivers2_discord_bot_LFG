import discord
from discord.ext import commands
import logging

# Map each clan name to the ID of the guild where we store the invite link
CLAN_SERVER_IDS = {
    "Kai's Commandos": 1261556132640456764,
    "Guardians of Freedom": 1172948128509468742,
    "Fenrir III 'Wolf Pack'": 1208728719963721779,
    "Heck Snorkelers": 1221490168670715936,
    "225th 'Python' SEAF Battalion": 1305994434021687296,
    "Galactic Phantom Taskforce": 1214787549655203862,
    "Hazard Airborne Commandos": 1309714539331325952
}

class SOSMenuView(discord.ui.View):
    """
    A persistent view providing buttons for SOS-related actions.
    """
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="LAUNCH SOS", style=discord.ButtonStyle.danger, custom_id="launch_sos_button")
    async def launch_sos_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sos_cog = self.bot.get_cog("SOSCog")
        if sos_cog:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            try:
                await sos_cog.launch_sos(interaction)
            except Exception as e:
                await interaction.followup.send(
                    "An error occurred while launching SOS. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in launch_sos_button: {e}")
        else:
            await interaction.response.send_message(
                "The SOS system is not available at the moment. Please try again later.",
                ephemeral=True
            )

    @discord.ui.button(label="CREATE MISSION", style=discord.ButtonStyle.primary, custom_id="create_mission_button")
    async def create_mission_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sos_view_cog = self.bot.get_cog("SOSViewCog")
        if sos_view_cog:
            await interaction.response.defer(ephemeral=True)
            try:
                view = sos_view_cog.get_sos_view()
                await interaction.followup.send(
                    "Let's start creating your SOS mission. Please select your options below:",
                    view=view,
                    ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    "An error occurred while creating the mission. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in create_mission_button: {e}")
        else:
            await interaction.response.send_message(
                "The mission creation system is not available at the moment. Please try again later.",
                ephemeral=True
            )

    @discord.ui.button(label="REGISTRATION", style=discord.ButtonStyle.success, custom_id="register_button")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        register_modal_cog = self.bot.get_cog("RegisterModalCog")
        if register_modal_cog:
            try:
                modal = register_modal_cog.get_register_modal()
                await interaction.response.send_modal(modal)
            except Exception as e:
                await interaction.response.send_message(
                    "An error occurred while opening the registration modal. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in register_button: {e}")
        else:
            await interaction.response.send_message(
                "The registration system is not available at the moment. Please try again later.",
                ephemeral=True
            )


class MenuViewCog(commands.Cog):
    """
    A cog to manage and provide the SOSMenuView. It builds a single Markdown 
    string with clickable links for each clan, using the invite link from 
    the clan's corresponding server ID.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sos_menu_view = SOSMenuView(bot)
        self.bot.add_view(self.sos_menu_view)
        logging.info("SOSMenuView registered globally as a persistent view.")

    async def send_sos_menu_to_guild(self, guild: discord.Guild):
        """
        Sends the SOS menu with instructions to a specific guild's designated GPT channel.
        Each clan name links to that clan's server invite link (retrieved from MongoDB).
        """
        try:
            server_listing = self.bot.mongo_db["Server_Listing"]
            server_data = await server_listing.find_one({"discord_server_id": guild.id})

            if not server_data:
                logging.warning(f"No server data found for guild '{guild.name}'. Skipping.")
                return

            # 1) Find the GPT channel for the current guild
            gpt_channel_id = server_data.get("gpt_channel_id")
            if not gpt_channel_id:
                logging.warning(f"Server data for '{guild.name}' does not contain 'gpt_channel_id'.")
                return

            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel:
                logging.warning(f"GPT channel (ID: {gpt_channel_id}) not found in guild '{guild.name}'.")
                return

            # 2) For each clan, retrieve the invite link from the corresponding server in MongoDB
            alliance_link_chunks = []
            for clan_name, clan_server_id in CLAN_SERVER_IDS.items():
                clan_server_data = await server_listing.find_one({"discord_server_id": clan_server_id})
                if clan_server_data and "discord_invite_link" in clan_server_data:
                    # Use the clan's actual invite link
                    invite_link = clan_server_data["discord_invite_link"]
                else:
                    # Fall back to a placeholder if missing
                    invite_link = "https://discord.gg/unknown"

                # Build a clickable link for this clan
                alliance_link_chunks.append(f"[{clan_name}]({invite_link})")

            # Combine them into one Markdown string, e.g.:  [Kai's](...) | [Guardians](...) | ...
            alliance_links_md = " | ".join(alliance_link_chunks)

            # 3) Build the embed description
            embed_description = (
                f"**{alliance_links_md}**\n\n"
                "**Instructions:**\n"
                "- **LAUNCH SOS**: Quickly send an SOS for any mission.\n\n"
                "- **CREATE MISSION**: Customize your SOS mission by selecting various options "
                "(Enemy Type, Difficulty, Play Style, Voice Comms, and Notes).\n\n"
                "- **REGISTER**: Register your Helldivers 2 player name in your allied server to claim your clan.\n\n"
                "**Notes:** Created voice channels/SOS embeds will expire after **60 seconds** of inactivity.\n\n"
                "Click the invite link to join the SOS voice channel!\n\n"
                "*Please choose an option below:*"
            )

            embed = discord.Embed(
                title="Welcome to the Alliance Network!",
                description=embed_description,
                color=discord.Color.blue()
            )

            # 4) Send the embed and attach our persistent view
            await gpt_channel.send(embed=embed, view=self.sos_menu_view)
            logging.info(f"SOS menu (embedded) sent to guild '{guild.name}' in channel '{gpt_channel.name}'.")

        except Exception as e:
            logging.error(f"Error sending SOS menu to guild '{guild.name}': {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MenuViewCog(bot))
