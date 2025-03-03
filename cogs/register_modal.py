import discord
from discord.ext import commands
from datetime import datetime
import logging

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

            await interaction.response.send_message(
                f"Registration successful! Welcome, **{player_name}**!",
                ephemeral=True
            )
            logging.info(f"User {player_name} ({discord_id}) registered successfully.")
        except Exception as e:
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
