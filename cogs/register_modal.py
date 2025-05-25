import discord
from discord.ext import commands
from datetime import datetime
import logging
import asyncio

class RegisterModal(discord.ui.Modal, title="Register as a Helldiver"):
    """
    A modal for user registration.
    """
    helldiver_name = discord.ui.TextInput(
        label="Helldiver Name",
        placeholder="Enter your Helldiver Name...",
        required=True,
        max_length=100
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        # Add the SOS LFG role select menu
        self.sos_lfg_role_select = None  # Initialize to None
        asyncio.create_task(self._add_role_select()) # Run role select creation asynchronously

    async def _add_role_select(self):
        # This method needs to be async because it interacts with the database
        if hasattr(self.bot, 'mongo_db') and self.bot.mongo_db is not None:
            server_listing = self.bot.mongo_db['Server_Listing']
            server_data = await server_listing.find_one({"discord_server_id": self.helldiver_name.view.interaction.guild_id})
            if server_data and 'sos_lfg_role_id' in server_data:
                role_id = server_data['sos_lfg_role_id']
                guild = self.bot.get_guild(self.helldiver_name.view.interaction.guild_id)
                if guild:
                    role = guild.get_role(role_id)
                    if role:
                        options = [discord.SelectOption(label=role.name, value=str(role.id))]
                        self.sos_lfg_role_select = discord.ui.Select(
                            placeholder="Select SOS LFG Role (Optional)",
                            options=options,
                            required=False
                        )
                        self.add_item(self.sos_lfg_role_select)

    async def on_submit(self, interaction: discord.Interaction):
        """
        Handle the modal submission.
        """
        try:
            # Collect user data
            discord_id = interaction.user.id
            discord_server_id = interaction.guild.id
            server_name = interaction.guild.name
            server_nickname = interaction.user.display_name
            player_name = self.helldiver_name.value

            # Prepare the document
            player_data = {
                "discord_id": discord_id,
                "discord_server_id": discord_server_id,
                "server_name": server_name,
                "server_nickname": server_nickname,
                "player_name": player_name,
                "registered_at": datetime.utcnow()
            }

            # Insert into the Alliance collection
            alliance_collection = self.bot.mongo_db['Alliance']
            await alliance_collection.update_one(
                {"discord_id": discord_id},
                {"$set": player_data},
                upsert=True
            )

            # Handle role assignment if a role was selected
            selected_role_id = None
            if self.sos_lfg_role_select and self.sos_lfg_role_select.values:
                selected_role_id = int(self.sos_lfg_role_select.values[0])

            if selected_role_id:
                guild = interaction.guild
                role = guild.get_role(selected_role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role)
                        await interaction.followup.send(
                            f"Registration successful! Welcome, **{player_name}**! You have been assigned the **{role.name}** role.",
                            ephemeral=True
                        )
                        logging.info(f"Assigned role {role.name} to user {player_name} ({discord_id}).")
                        return # Exit after sending followup
                    except discord.Forbidden:
                        logging.warning(f"Bot lacks permissions to assign role {role.name} to user {player_name} ({discord_id}).")
                        # Fall through to send registration success message without role mention
                    except Exception as role_e:
                        logging.error(f"Error assigning role {role.name} to user {player_name} ({discord_id}): {role_e}")
                        # Fall through to send registration success message without role mention

            await interaction.response.send_message(
                f"Registration successful! Welcome, **{player_name}**!",
                ephemeral=True
            ) # Send this if no role was selected or role assignment failed
            logging.info(f"User {player_name} ({discord_id}) registered successfully{', without role assignment due to error' if selected_role_id else ''}.")

        except Exception as e: # Catch errors during the initial registration process
            logging.error(f"Error during registration: {e}")
            await interaction.response.send_message(
                "An error occurred while registering. Please try again later.",
                ephemeral=True
            )

class RegisterModalCog(commands.Cog):
    """
    A cog to manage the RegisterModal.
    """
    def __init__(self, bot):
        self.bot = bot

    def get_register_modal(self):
        """
        Returns an instance of RegisterModal.
        """
        return RegisterModal(self.bot)

async def setup(bot):
    await bot.add_cog(RegisterModalCog(bot))
