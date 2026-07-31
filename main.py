import asyncio
import os

from dotenv import load_dotenv
import discord
from discord.ext import commands

from modules import giveaway_module
from modules import survivalgames_module

load_dotenv()

# ---- token ----
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set")

# ---- intents ----
# Union of what each module needs: giveaway needs members/reactions/message_content,
# survival games needs members/message_content (reactions is already on via default()).
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
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

        if self._managers_started:
            return
        self._managers_started = True

        if hasattr(self, "giveaway_manager"):
            await self.giveaway_manager.start()

        if hasattr(self, "survival_manager"):
            await self.survival_manager.start()


bot = CrownedEvents()


async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass