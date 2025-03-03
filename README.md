Discord Matchmaking Bot
Overview
This Discord bot facilitates matchmaking for 4-man squads within a Discord community. Users can sign up for squads and post requests for additional members, enhancing community engagement and gameplay coordination.

Features
Squad Matchmaking: Allows users to sign up for 4-man squads and post requests for more members.
Leaderboard: Tracks user activities and provides a leaderboard based on interaction metrics.
Leveling System: Built-in leveling system based on user interactions to encourage community engagement.
Data Retention Policy
In compliance with Discord's Terms of Service:

User data is stored for a maximum of 30 days, excluding necessary Discord IDs for community management.
Setup Instructions
Prerequisites
Python 3.10 or higher installed on your system.
MongoDB Atlas account for database storage.
Discord bot token obtained from Discord Developer Portal.
Installation
Clone this repository to your local machine:

bash
Copy code
git clone https://github.com/your-username/matchmaking-bot.git
cd matchmaking-bot
Install dependencies using pip:

bash
Copy code
pip install -r requirements.txt
Configuration
Create a .env file in the root directory and add your Discord bot token and MongoDB connection URI:

makefile
Copy code
DISCORD_TOKEN=your_discord_bot_token_here
MONGODB_URI=your_mongodb_uri_here
Running the Bot
Activate the virtual environment:

bash
Copy code
source .venv/bin/activate   # On Windows use .venv\Scripts\activate
Start the bot:

bash
Copy code
python main.py
Usage
Once the bot is running, users can:
Sign up for 4-man squads.
Post requests for additional members to join their squad.
Interact with the leaderboard and leveling system based on their activities within the Discord server.
Support
For questions, issues, or feature requests, please open an issue on GitHub.

Contributing
Contributions are welcome! Fork the repository and submit a pull request with your enhancements.

License
This project is licensed under the Apache 2.0 License.