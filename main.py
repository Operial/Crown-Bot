import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
import discord
from discord.ext import commands
from modules import giveaway_module
from modules import survivalgames_module
from modules import ai_assistant_module

# ---- token ----
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set")

# ---- Politics and War API ----
PNW_API_KEY = os.getenv("PNW_API_KEY")
if not PNW_API_KEY:
    raise RuntimeError("PNW_API_KEY not set")
# ---- intents ----
# Union of what each module needs: giveaway needs members/reactions/message_content,
# survival games needs members/message_content (reactions is already on via
# default()). The AI assistant module needs message_content too (to read
# questions and index history) but nothing beyond what's already enabled here.
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
intents.message_content = True


class CrownedEvents(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="*",
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self._managers_started = False

    async def setup_hook(self):
        # Each module attaches its own manager (e.g. self.giveaway_manager,
        # self.survival_manager) and registers its own commands/listeners.
        # To add another module later, import it above and add one more
        # line here -- same pattern, no other changes needed.
        await giveaway_module.setup(self)
        await survivalgames_module.setup(self)
        await ai_assistant_module.setup(self)
        await self.tree.sync()

    async def close(self):
        if hasattr(self, "ai_manager"):
            await self.ai_manager.close()
        await super().close()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

        if self._managers_started:
            return
        self._managers_started = True

        if hasattr(self, "giveaway_manager"):
            await self.giveaway_manager.start()

        if hasattr(self, "survival_manager"):
            await self.survival_manager.start()

        if hasattr(self, "ai_manager"):
            await self.ai_manager.start()


bot = CrownedEvents()


async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

