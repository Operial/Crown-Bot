import asyncio
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---- paths ----
# This file lives in <project_root>/modules/, so go up two levels to reach
# the project root and keep sharing the same top-level data/ folder as
# every other module.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
os.environ["DATA_DIR"] = str(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# CONFIG
OWNER_ID = 347774188846841856
GIVEAWAY_EMOJI = "🎉"

CHANNELS_FILE = os.path.join(DATA_DIR, "giveaway_channels.json")
GIVEAWAYS_FILE = os.path.join(DATA_DIR, "active_giveaways.json")
EMBED_IMAGE_URL = "https://cdn.discordapp.com/attachments/821587932401106953/1414893958970081361/Untitled83_20250526222841.png"

# Helpers
def load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def parse_duration(s: str) -> Optional[int]:
    m = re.match(r"^\s*(\d+)\s*([smhd])\s*$", s, re.I)
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2).lower()
    mults = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return num * mults[unit]

def _now_ts() -> int:
    return int(time.time())

class GiveawayManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.giveaway_channels = load_json(CHANNELS_FILE)
        self.active_giveaways = load_json(GIVEAWAYS_FILE)
        self.scheduled_tasks: dict[str, asyncio.Task] = {}
        self.debounced_update_tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        """Called by main.py on_ready to start tasks and reconcile state."""
        for gid, data in list(self.active_giveaways.items()):
            if not data.get("running"):
                continue

            # 1. Rebuild entries + user_map from actual message reactions
            rebuilt_entries = set()
            rebuilt_user_map = {}
            for msginfo in data.get("messages", []):
                try:
                    ch = self.bot.get_channel(int(msginfo.get("channel")))
                    if not ch:
                        try:
                            ch = await self.bot.fetch_channel(int(msginfo.get("channel")))
                        except Exception:
                            continue

                    msg = await ch.fetch_message(int(msginfo.get("message_id")))
                    for reaction in msg.reactions:
                        if str(reaction.emoji) == GIVEAWAY_EMOJI:
                            async for user in reaction.users():
                                if user.bot:
                                    continue
                                rebuilt_entries.add(user.id)
                                if msg.guild and str(user.id) not in rebuilt_user_map:
                                    rebuilt_user_map[str(user.id)] = str(msg.guild.id)
                            break
                except Exception:
                    pass

            old_entries = set(data.get("entries", []))
            old_user_map = data.get("user_map", {}) or {}
            if rebuilt_entries or rebuilt_user_map:
                changed = False
                if rebuilt_entries != old_entries:
                    changed = True
                else:
                    for uid, gid_val in rebuilt_user_map.items():
                        if old_user_map.get(uid) != gid_val:
                            changed = True
                            break

                if changed:
                    data["entries"] = list(rebuilt_entries)
                    data["user_map"] = rebuilt_user_map
                    save_json(GIVEAWAYS_FILE, self.active_giveaways)

            # 2. Schedule finish tasks
            end_time = data.get("end_time", 0)
            if end_time <= _now_ts():
                asyncio.create_task(self._finish_giveaway(gid))
                continue
            if gid not in self.scheduled_tasks:
                self.scheduled_tasks[gid] = asyncio.create_task(self._schedule_finish(gid))

    async def _schedule_finish(self, gid: str):
        try:
            data = self.active_giveaways.get(gid)
            if not data:
                return
            delay = data["end_time"] - _now_ts()
            if delay > 0:
                await asyncio.sleep(delay)
            if self.active_giveaways.get(gid, {}).get("running"):
                await self._finish_giveaway(gid)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _finish_giveaway(self, gid: str):
        if gid in self.debounced_update_tasks:
            self.debounced_update_tasks.pop(gid).cancel()

        data = self.active_giveaways.get(gid)
        if not data or not data.get("running"):
            return

        final_entrants = set()
        for msginfo in data.get("messages", []):
            try:
                ch = self.bot.get_channel(int(msginfo.get("channel")))
                if not ch:
                    try:
                        ch = await self.bot.fetch_channel(int(msginfo.get("channel")))
                    except Exception:
                        continue

                msg = await ch.fetch_message(int(msginfo.get("message_id")))
                for reaction in msg.reactions:
                    if str(reaction.emoji) == GIVEAWAY_EMOJI:
                        async for user in reaction.users():
                            if not user.bot:
                                final_entrants.add(user.id)
                        break
            except Exception:
                continue

        entries = list(final_entrants)
        winners_count = max(1, int(data.get("winners", 1)))
        prize = data.get("title", "Prize")
        winners: list[int] = []
        if entries:
            k = min(winners_count, len(entries))
            winners = random.sample(entries, k=k)

        for srv_id, ch_id in data.get("channels", {}).items():
            ch = self.bot.get_channel(int(ch_id))
            if not ch:
                continue
            try:
                if winners:
                    winner_lines = []
                    for uid in winners:
                        orig_gid = data.get("user_map", {}).get(str(uid), "")
                        gname = "Unknown Server"
                        if orig_gid:
                            try:
                                gobj = self.bot.get_guild(int(orig_gid))
                                gname = gobj.name if gobj else f"Server {orig_gid}"
                            except Exception:
                                gname = f"Server {orig_gid}"
                        winner_lines.append(f"<@{uid}> from **{gname}**")

                    embed = discord.Embed(
                        title=f"🎉 {prize} 🎉",
                        description="Congratulations to the winner(s)!\n\n" + "\n".join(winner_lines),
                        color=discord.Color.gold(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text="Thanks to everyone for participating!")
                    embed.set_thumbnail(url=EMBED_IMAGE_URL)
                    await ch.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
                else:
                    embed = discord.Embed(
                        title=f"Giveaway Ended: {prize}",
                        description="Unfortunately, there were no participants in this giveaway.",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_thumbnail(url=EMBED_IMAGE_URL)
                    await ch.send(embed=embed)
            except Exception:
                pass

        for uid in winners:
            try:
                user = await self.bot.fetch_user(uid)
                dm_embed = discord.Embed(
                    title="🎉 You won!",
                    description=f"Congratulations — you won **{prize}**. Please send <@{OWNER_ID}> (*operial*) a message telling him you won, also send a screenshot of this message as evidence.",
                    color=discord.Color.gold(),
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.set_thumbnail(url=EMBED_IMAGE_URL)
                await user.send(embed=dm_embed)
            except Exception:
                pass

        self.active_giveaways.pop(gid, None)
        save_json(GIVEAWAYS_FILE, self.active_giveaways)

        t1 = self.scheduled_tasks.pop(gid, None)
        if t1 and not t1.done():
            t1.cancel()

    def _render_participants_field(self, data: dict) -> str:
        entries = data.get("entries", [])
        user_map = data.get("user_map", {})
        if not entries:
            return "*No participants yet*"
        counts_by_server = {}
        for user_id in entries:
            guild_id = user_map.get(str(user_id))
            if guild_id:
                counts_by_server[guild_id] = counts_by_server.get(guild_id, 0) + 1
        if not counts_by_server:
            return f"**Total Entrants**: {len(entries)}"
        parts = []
        def guild_name_key(item):
            gid = item[0]
            try:
                gobj = self.bot.get_guild(int(gid))
                return gobj.name.lower() if gobj else ""
            except Exception:
                return ""
        sorted_guilds = sorted(counts_by_server.items(), key=guild_name_key)
        for gid, count in sorted_guilds:
            guild_obj = None
            try:
                guild_obj = self.bot.get_guild(int(gid))
            except Exception:
                pass
            gname = guild_obj.name if guild_obj else f"Server {gid}"
            parts.append(f"**{gname}**: {count} entrants")
        return "\n".join(parts)

    async def _update_giveaway_embeds(self, gid: str):
        data = self.active_giveaways.get(gid)
        if not data or not data.get("running"):
            return
        participants_text = self._render_participants_field(data)
        emb = discord.Embed(
            title=data.get("title", "Giveaway"),
            description=data.get("description", "") or "React to enter!",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        emb.add_field(name="Ends", value=f"<t:{data['end_time']}:R>", inline=True)
        emb.add_field(name="Winners", value=str(data.get("winners", 1)), inline=True)
        emb.add_field(name="Participants by Server", value=participants_text, inline=False)
        emb.set_footer(text=f"Giveaway ID: {gid}")
        emb.set_thumbnail(url=EMBED_IMAGE_URL)
        for msginfo in data.get("messages", []):
            ch = self.bot.get_channel(int(msginfo.get("channel")))
            if not ch:
                continue
            try:
                msg = await ch.fetch_message(int(msginfo.get("message_id")))
                await msg.edit(embed=emb)
            except Exception:
                continue

    async def _trigger_debounced_update(self, gid: str):
        if gid in self.debounced_update_tasks:
            self.debounced_update_tasks[gid].cancel()
        async def debounced_task_wrapper():
            await asyncio.sleep(1.5)
            try:
                await self._update_giveaway_embeds(gid)
            except Exception:
                pass
        task = asyncio.create_task(debounced_task_wrapper())
        self.debounced_update_tasks[gid] = task

    # ---------------------------------------------------------
    # COMMAND LOGIC
    # ---------------------------------------------------------
    async def cmd_setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("You need Manage Server permission...", ephemeral=True)

        self.giveaway_channels[str(interaction.guild.id)] = channel.id
        save_json(CHANNELS_FILE, self.giveaway_channels)
        await interaction.response.send_message(f"Giveaway channel set to {channel.mention}", ephemeral=True)

    async def cmd_removechannel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("You need Manage Server permission...", ephemeral=True)

        gid = str(interaction.guild.id)
        if gid in self.giveaway_channels:
            del self.giveaway_channels[gid]
            save_json(CHANNELS_FILE, self.giveaway_channels)
            return await interaction.response.send_message("Giveaway channel removed for this server.", ephemeral=True)
        return await interaction.response.send_message("This server does not have a giveaway channel set.", ephemeral=True)

    async def cmd_create(self, interaction: discord.Interaction, prize: str, duration: str, winners: int, description: str):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != OWNER_ID:
            return await interaction.followup.send("Only the bot owner can start global giveaways.")

        dur_seconds = parse_duration(duration)
        if dur_seconds is None or dur_seconds <= 0:
            return await interaction.followup.send("Invalid duration. Use formats like 30s, 5m, 2h, 1d.")

        channels_to_post = {gid: cid for gid, cid in self.giveaway_channels.items()}
        if not channels_to_post:
            return await interaction.followup.send("No servers have set giveaway channels...")

        gid = f"g{_now_ts()}{random.randint(1000,9999)}"
        end_time = _now_ts() + dur_seconds
        data = {"title": prize, "description": description, "end_time": end_time, "winners": winners, "running": True, "entries": [], "user_map": {}, "channels": channels_to_post, "messages": []}
        server_names = []

        for srv_id, ch_id in channels_to_post.items():
            ch = self.bot.get_channel(int(ch_id))
            if not ch:
                continue
            try:
                emb = discord.Embed(
                    title=prize,
                    description=description or "React to enter!",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                )
                emb.add_field(name="Ends", value=f"<t:{end_time}:R>", inline=True)
                emb.add_field(name="Winners", value=str(winners), inline=True)
                emb.set_footer(text=f"Giveaway ID: {gid}")
                emb.set_thumbnail(url=EMBED_IMAGE_URL)
                msg = await ch.send(embed=emb)
                await msg.add_reaction(GIVEAWAY_EMOJI)
                data["messages"].append({"channel": ch_id, "message_id": msg.id})
                if msg.guild:
                    server_names.append(msg.guild.name)
            except Exception:
                pass

        if not data["messages"]:
            return await interaction.followup.send("Could not post the giveaway to any server channels...")

        self.active_giveaways[gid] = data
        save_json(GIVEAWAYS_FILE, self.active_giveaways)
        self.scheduled_tasks[gid] = asyncio.create_task(self._schedule_finish(gid))

        servers_list = "\n".join(f"- {name}" for name in server_names)
        await interaction.followup.send(f"✅ Global giveaway **{prize}** started (ID `{gid}`).\nPosted to:\n{servers_list}")

    async def cmd_cancel(self, interaction: discord.Interaction, giveaway_id: str):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Only the owner can cancel giveaways.", ephemeral=True)

        gid = giveaway_id
        if gid not in self.active_giveaways:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)

        data = self.active_giveaways.pop(gid)
        save_json(GIVEAWAYS_FILE, self.active_giveaways)

        if gid in self.scheduled_tasks:
            self.scheduled_tasks.pop(gid).cancel()
        if gid in self.debounced_update_tasks:
            self.debounced_update_tasks.pop(gid).cancel()

        # 1. Delete the original giveaway embeds
        for msginfo in data.get("messages", []):
            try:
                ch = self.bot.get_channel(int(msginfo.get("channel")))
                if ch:
                    msg = await ch.fetch_message(int(msginfo.get("message_id")))
                    await msg.delete()
            except Exception:
                pass  # Ignore if the message or channel was already deleted

        # 2. Send the new announcement to all servers that have a giveaway channel set
        title = data.get("title", "Unknown Prize")
        for srv_id, ch_id in self.giveaway_channels.items():
            ch = self.bot.get_channel(int(ch_id))
            if ch:
                try:
                    await ch.send(f"⚠️ The giveaway for **{title}** has been cancelled by Xaria.")
                except Exception:
                    pass

        return await interaction.response.send_message(f"Giveaway `{gid}` cancelled, embeds deleted, and servers informed.", ephemeral=True)

    async def cmd_info(self, interaction: discord.Interaction, giveaway_id: str):
        data = self.active_giveaways.get(giveaway_id)
        if not data:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)

        embed = discord.Embed(title=f"Giveaway: {data.get('title')}", color=discord.Color.blue(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="ID", value=giveaway_id, inline=False)
        embed.add_field(name="Ends", value=f"<t:{data['end_time']}:R>", inline=True)
        embed.add_field(name="Winners", value=str(data.get("winners", 1)), inline=True)
        embed.add_field(name="Entries", value=str(len(data.get("entries", []))), inline=True)
        embed.set_footer(text=f"Running: {data.get('running', False)}")
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------------------------------------------------
    # EVENT LISTENERS
    # ---------------------------------------------------------
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != GIVEAWAY_EMOJI:
            return

        for gid, data in self.active_giveaways.items():
            if not data.get("running"):
                continue
            for m in data.get("messages", []):
                if int(m["message_id"]) == payload.message_id:
                    uid = payload.user_id

                    if uid in data.get("entries", []):
                        try:
                            orig_gid = data.get("user_map", {}).get(str(uid))
                            gname = None
                            if orig_gid:
                                guild_obj = self.bot.get_guild(int(orig_gid))
                                gname = guild_obj.name if guild_obj else f"Server {orig_gid}"
                            else:
                                gname = "the original server"

                            user = await self.bot.fetch_user(uid)
                            await user.send(f"You have already entered the giveaway in **{gname}**.")

                            try:
                                ch = self.bot.get_channel(payload.channel_id)
                                if ch:
                                    msg = await ch.fetch_message(payload.message_id)
                                    await msg.remove_reaction(payload.emoji, user)
                            except Exception:
                                pass
                        except Exception:
                            pass
                        return

                    data.setdefault("entries", []).append(uid)
                    data.setdefault("user_map", {})[str(uid)] = str(payload.guild_id) if payload.guild_id else ""
                    save_json(GIVEAWAYS_FILE, self.active_giveaways)
                    await self._trigger_debounced_update(gid)

                    try:
                        user = await self.bot.fetch_user(uid)
                        embed = discord.Embed(
                            title="✅ You've Entered the Giveaway!",
                            description=f"You have successfully entered to win **{data.get('title', 'a prize')}**!",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.set_footer(text="Good luck!")
                        embed.set_thumbnail(url=EMBED_IMAGE_URL)
                        await user.send(embed=embed)
                    except Exception:
                        pass
                    return

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != GIVEAWAY_EMOJI:
            return

        for gid, data in self.active_giveaways.items():
            if not data.get("running"):
                continue
            for m in data.get("messages", []):
                if int(m["message_id"]) == payload.message_id:
                    uid = payload.user_id
                    if uid in data.get("entries", []):
                        orig_gid = data.get("user_map", {}).get(str(uid))
                        if orig_gid and str(payload.guild_id) != orig_gid:
                            try:
                                user = await self.bot.fetch_user(uid)
                                guild_obj = self.bot.get_guild(int(orig_gid)) if orig_gid else None
                                gname = guild_obj.name if guild_obj else f"Server {orig_gid}"
                                await user.send(f"To leave the giveaway you must unreact on the giveaway message in **{gname}** (the server where you originally entered).")
                                try:
                                    ch = self.bot.get_channel(payload.channel_id)
                                    if ch:
                                        msg = await ch.fetch_message(payload.message_id)
                                        await msg.add_reaction(GIVEAWAY_EMOJI)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            return

                        data["entries"].remove(uid)
                        data.get("user_map", {}).pop(str(uid), None)
                        save_json(GIVEAWAYS_FILE, self.active_giveaways)
                        await self._trigger_debounced_update(gid)

                        try:
                            user = await self.bot.fetch_user(uid)
                            await user.send(f"You have withdrawn your entry from the giveaway for **{data.get('title', 'a prize')}**.")
                        except Exception:
                            pass
                    return

    async def on_member_remove(self, member: discord.Member):
        left_guild_id = getattr(member.guild, "id", None)
        if left_guild_id is None:
            return

        for gid, data in list(self.active_giveaways.items()):
            if member.id not in data.get("entries", []):
                continue

            orig_gid = data.get("user_map", {}).get(str(member.id))
            try:
                if orig_gid:
                    try:
                        orig_gid_int = int(orig_gid)
                    except Exception:
                        orig_gid_int = None

                    if orig_gid_int is not None and orig_gid_int == left_guild_id:
                        try:
                            data["entries"].remove(member.id)
                        except ValueError:
                            pass
                        data.get("user_map", {}).pop(str(member.id), None)
                        save_json(GIVEAWAYS_FILE, self.active_giveaways)
                        await self._trigger_debounced_update(gid)

                        try:
                            for msginfo in data.get("messages", []):
                                ch = self.bot.get_channel(int(msginfo.get("channel")))
                                if not ch or not ch.guild or ch.guild.id != member.guild.id:
                                    continue
                                try:
                                    msg = await ch.fetch_message(int(msginfo.get("message_id")))
                                    user_obj = await self.bot.fetch_user(member.id)
                                    await msg.remove_reaction(GIVEAWAY_EMOJI, user_obj)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        try:
                            await member.send(f"You have been automatically removed from the giveaway for **{data.get('title', 'a prize')}** because you left **{member.guild.name}** (the server where you entered).")
                        except Exception:
                            pass
            except Exception:
                continue

async def setup(bot: discord.Client):
    manager = GiveawayManager(bot)
    bot.giveaway_manager = manager

    bot.add_listener(manager.on_raw_reaction_add, 'on_raw_reaction_add')
    bot.add_listener(manager.on_raw_reaction_remove, 'on_raw_reaction_remove')
    bot.add_listener(manager.on_member_remove, 'on_member_remove')

    giveaway_group = app_commands.Group(name="giveaway", description="Global giveaway commands")

    @giveaway_group.command(name="setchannel", description="Set this server's giveaway posting channel (requires Manage Guild).")
    @app_commands.describe(channel="Channel to post giveaways in")
    async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
        await manager.cmd_setchannel(interaction, channel)

    @giveaway_group.command(name="removechannel", description="Remove this server's giveaway channel.")
    async def removechannel(interaction: discord.Interaction):
        await manager.cmd_removechannel(interaction)

    @giveaway_group.command(name="create", description="Create a global giveaway (owner only).")
    @app_commands.describe(prize="What is the prize?", duration="Duration (e.g. 30s, 5m, 2h, 1d)", winners="Number of winners", description="Short description")
    async def create(interaction: discord.Interaction, prize: str, duration: str, winners: int = 1, description: str = ""):
        await manager.cmd_create(interaction, prize, duration, winners, description)

    @giveaway_group.command(name="cancel", description="Cancel a running giveaway (owner only).")
    @app_commands.describe(giveaway_id="Giveaway ID")
    async def cancel(interaction: discord.Interaction, giveaway_id: str):
        await manager.cmd_cancel(interaction, giveaway_id)

    @giveaway_group.command(name="info", description="Show information about an active giveaway.")
    @app_commands.describe(giveaway_id="Giveaway ID")
    async def info(interaction: discord.Interaction, giveaway_id: str):
        await manager.cmd_info(interaction, giveaway_id)

    bot.tree.add_command(giveaway_group)
