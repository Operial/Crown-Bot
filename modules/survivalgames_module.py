import asyncio
import json
import math
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks

# ---- paths ----
# This file lives in <project_root>/modules/, so go up two levels to reach
# the project root and share the same top-level data/ folder as every
# other module (e.g. giveaway_module.py).
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GAME_DATA_FILE = os.path.join(DATA_DIR, "game_data.json")

# Game configuration
default_min_participants = 1
default_max_participants = 16
number_of_districts = 5
attack_cooldown = 5
time_to_start = 17
admin_ids = [543584109826408453, 347774188846841856]

def gen_default_state():
    return {
    "start_time": None,
    "participants": [],
    "districts": {},
    "game_started": False,
    "loot_boxes": {},
    "inventory": {},
    "hp": {},
    "max_hp": {},
    "equipped_items": {},
    "defense": {},
    "walking": {},
    "endgame_votes": [],
    "cooldowns": {},
    "attacked_cooldowns": {},
    "knocked_down": [],
    "stats": {
        "kills":{},
        "robs":{},
        "slaps":{},
        "damage_dealt":{},
        "damage_taken":{},
        "crits":{},
    },
    "min_participants": default_min_participants,
    "max_participants": default_max_participants,
    "top_three":[],
    "registration_message_id": None,
}

stat_to_award = {
        "kills":"Bloodthirsty (Most Kills)",
        "robs":"Greedy (Most Robs)",
        "slaps":"Slapmaxxer (Most Slaps)",
        "damage_dealt":"Wrecking Ball (Most Damage Dealt)",
        "damage_taken":"Tank (Most Damage Taken)",
        "crits":"Lucky (Most Crits)",
}

item_details = {
    "Fist": {"type": "weapon", "damage": 1, "rarity": "common"},
    "Toilet Plunger": {"type": "weapon", "damage": 1, "rarity": "common"},
    "Axe": {"type": "weapon", "damage": 2, "rarity": "common"},
    "Sword": {"type": "weapon", "damage": 2, "rarity": "uncommon"},
    "Dual Daggers": {"type": "weapon", "damage": 4, "rarity": "rare"},
    "Bow and Arrows": {"type": "weapon", "damage": 5, "rarity": "rare"},
    "Pistol": {"type": "weapon", "damage": 6, "rarity": "rare"},
    "Leather Helmet": {"type": "defense", "defense": 5, "rarity": "common"},
    "Leather Chestplate": {"type": "defense", "defense": 15, "rarity": "rare"},
    "Leather Pants": {"type": "defense", "defense": 15, "rarity": "uncommon"},
    "Leather Shoes": {"type": "defense", "defense": 5, "rarity": "common"},
    "Healing Potions": {"type": "heal", "heal": 2, "rarity": "rare"}
}

def gen_intro_embed():
    embed = discord.Embed(
        title="Welcome to the Survival Games!",
        description=f"There’s a good chance other players have spawned in this district. You can choose to fight or form a truce.\nThere are **{number_of_districts}** districts in total.\n\nTo travel to another district, use `*travel (district number)`.\nTo view the available commands, type `*commands`.",
        color=discord.Color.from_rgb(195, 73, 32)
    )
    embed.set_image(url="https://i.ibb.co/27JF3tpP/del.webp")

    return embed

def jsonKeys2int(x):
    # Only if the key is a parsable number in a string
    if isinstance(x, dict):
        return {int(k) if k.isdigit() else k: v for k, v in x.items()}
    return x

class SurvivalGamesManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.game_data = gen_default_state()

    async def start(self):
        """Called by main.py's on_ready, once, alongside every other module's start()."""
        await self.bot.change_presence(activity=discord.Game(name="on Orbis Crowned News"))
        if not self.spawn_lootboxes.is_running():
            self.spawn_lootboxes.start()

    def gen_player_list(self):
        return "\n".join([f"<@{user}>" for user in self.game_data["participants"]])

    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return

        if reaction.message.author == self.bot.user and reaction.emoji == "✅" and reaction.message.id == self.game_data["registration_message_id"]:
            if len(self.game_data["participants"]) <= self.game_data["max_participants"] and user.id not in self.game_data["participants"]:
                self.game_data["participants"].append(user.id)
                channel = self.bot.get_channel(reaction.message.channel.id)
                # edit embed field
                newEmbed = self.gen_registration_embed()
                await reaction.message.edit(embed=newEmbed)


                if len(self.game_data["participants"]) >= self.game_data["min_participants"] and not self.game_data.get("timer_started"):
                    timestamp = datetime.now() + timedelta(seconds=time_to_start)
                    self.game_data["timer_started"] = True
                    self.game_data["start_time"] = timestamp
                     # edit emebed to show time remaining
                    await reaction.message.edit(content=f"## Starting <t:{str(timestamp.timestamp()).split('.')[0]}:R>")
                    await asyncio.sleep(time_to_start)

                    if len(self.game_data["participants"]) >= self.game_data["min_participants"]:
                        await reaction.message.delete()
                        await self.start_game(reaction.message.guild)
                    else:
                        await reaction.message.edit(content=":x: Not enough players to start game. Cancelling game.")

        elif reaction.message.author == self.bot.user and reaction.emoji == "🎁":
            if reaction.message.channel.id in self.game_data["loot_boxes"]:
                item_list = list(item_details.keys())
                item_list.remove("Fist")

                if self.game_data["inventory"][user.id].count("Healing Potions") >= 3:
                    item_list.remove("Healing Potions")
                item_name = random.choice(item_list)

                if user.id not in self.game_data["inventory"]:
                    self.game_data["inventory"][user.id] = []


                self.game_data["inventory"][user.id].append(item_name)
                await reaction.message.channel.send(f"{user.mention} got a {item_name} from the lootbox!")
                del self.game_data["loot_boxes"][reaction.message.channel.id]
                await reaction.message.delete()

    async def on_reaction_remove(self, reaction, user):
        if reaction.message.author == self.bot.user and reaction.emoji == "✅":
            if user.id in self.game_data["participants"]:
                self.game_data["participants"].remove(user.id)
                channel = self.bot.get_channel(reaction.message.channel.id)
                # edit embed field
                newEmbed = self.gen_registration_embed()
                await reaction.message.edit(embed=newEmbed)

    @tasks.loop(seconds=10)
    async def save_loop(self):
        with open(GAME_DATA_FILE, "w") as f:
            temp = self.game_data.copy()
            if "start_time" in temp and temp["start_time"] is not None:
                temp["start_time"] = self.game_data["start_time"].isoformat()
            json.dump(temp, f)

    async def kickoff_save(self):
        await self.save_loop.start()

    async def start_game(self, guild):
        # Sanity check, remove duplicate players
        participants = list(set(self.game_data["participants"]))
        self.game_data["participants"] = participants

        print('Starting game...')
        category = await guild.create_category("Hunger Games")

        alert_channel = None
        for channel in guild.channels:
            if channel.name == "🎮│hunger-games":
                alert_channel = channel
                break
        if not alert_channel:
            alert_channel = await category.create_text_channel("🎮│hunger-games")

        self.game_data["districts"]["alerts"] = alert_channel.id

        # Set up alerts channel permissions
        for participant in self.game_data["participants"]:
            user = guild.get_member(participant)
            await alert_channel.set_permissions(user, read_messages=True, send_messages=False)

        # Create district channels
        for i in range(1, number_of_districts + 1):
            district_name = f"district-{i}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
            }
            district_channel = await category.create_text_channel(district_name, overwrites=overwrites, slowmode_delay=1)
            self.game_data["districts"][district_name] = district_channel.id
            intro_embed = gen_intro_embed()
            await district_channel.send(embed=intro_embed)

        # Assign participants to districts
        for participant in self.game_data["participants"]:
            user = guild.get_member(participant)
            assigned_district = random.choice(list(self.game_data["districts"].keys())[1:])  # Exclude alerts
            district_channel = self.bot.get_channel(self.game_data["districts"][assigned_district])

            # Set initial permissions
            await district_channel.set_permissions(user, read_messages=True, send_messages=True)

            # Initialize player data
            self.game_data["inventory"][participant] = ["Fist"]
            self.game_data["max_hp"][participant] = 20
            self.game_data["hp"][participant] = 20
            self.game_data["equipped_items"][participant] = {"weapon": "Fist", "defense": []}
            self.game_data["defense"][participant] = 0

        self.game_data["game_started"] = True
        await alert_channel.send("The Hunger Games have begun! May the odds be ever in your favor!")

    def is_valid_command_context(self, ctx):
        if not self.game_data["game_started"]:
            print("Game not started", self.game_data["game_started"])
            return False
        if ctx.channel.id not in self.game_data["districts"].values():
            try:
                ctx.author.send("Commands can only be used in district channels!")
            except:
                pass
            return False
        if ctx.author.id not in self.game_data["participants"]:
            try:
                ctx.author.send("You're not a participant in the current game!")
            except:
                pass
            return False
        return True

    def is_in_same_district(self, user1, user2):
        for district, ch_id in self.game_data["districts"].items():
            if district == "alerts":
                continue
            channel = self.bot.get_channel(ch_id)
            if channel.permissions_for(user1).read_messages and channel.permissions_for(user2).read_messages:
                return True
        return False

    async def cmd_restore(self, ctx):
        if ctx.author.id not in admin_ids: 
            return

        with open(GAME_DATA_FILE, "r") as f:
            self.game_data = json.load(f, object_hook=jsonKeys2int)
            if self.game_data["start_time"]:
                self.game_data["start_time"] = datetime.fromisoformat(self.game_data["start_time"])

        await ctx.message.reply("Game data restored!")

        # Resend registration embed if game not started
        if not self.game_data["game_started"]:
            embed = self.gen_registration_embed()
            msg = await ctx.send(embed=embed)
            self.game_data["registration_message_id"] = msg.id
            await msg.add_reaction("✅")

            #If game has min players, start game
            if len(self.game_data["participants"]) >= self.game_data["min_participants"]:
                timestamp = datetime.now() + timedelta(seconds=time_to_start)
                time_passed = False
                # See if a timer was started, if so attempt to restore it
                if self.game_data["timer_started"]:
                    time_passed = datetime.now() > self.game_data["start_time"]
                    timestamp = self.game_data["start_time"]
                    print("SIGMA")
                if not time_passed:
                    time_diff = timestamp -  datetime.now()
                    # Get the difference in seconds
                    diff_seconds = time_diff.total_seconds()

                    self.game_data["timer_started"] = True
                        # edit emebed to show time remaining
                    await msg.edit(content=f"## Starting <t:{str(timestamp.timestamp()).split('.')[0]}:R>")
                    print("WAITING")
                    print(diff_seconds)
                    await asyncio.sleep(diff_seconds)

                if len(self.game_data["participants"]) >= self.game_data["min_participants"]:
                    await msg.delete()
                    await self.start_game(msg.guild)
                else:
                    await msg.edit(content=":x: Not enough players to start game. Cancelling game.")


        await self.kickoff_save()

    async def cmd_inventory(self, ctx):
        if not self.is_valid_command_context(ctx):
            return


        items = self.game_data["inventory"].get(ctx.author.id, [])
        equipped = self.game_data["equipped_items"][ctx.author.id]

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=0x00ff00)

        item_counts = {}
        for item in items:
            item_counts[item] = item_counts.get(item, 0) + 1

        for item, count in item_counts.items():
            details = item_details[item]
            equipped_status = ""
            if item == equipped["weapon"] or item in equipped["defense"]:
                equipped_status = " (EQUIPPED)"

            if details["type"] == "weapon":
                info = f"Damage: {details['damage']}"
            elif details["type"] == "defense":
                info = f"Defense: +{details['defense']}"
            else:
                info = f"Heals: {details['heal']} HP"

            embed.add_field(name=f"{item}{equipped_status} x{count}", value=info, inline=False)

        await ctx.message.reply(embed=embed, delete_after=30)

    async def cmd_equip(self, ctx, *, item_name):
        if not self.is_valid_command_context(ctx):
            return

        corrected_item_name = None
        # REALLY BAD BUT WORKS FOR very low and basic size array
        for item in item_details.keys():
            if item.lower().strip() == item_name.lower().strip():
                corrected_item_name = item
                break

        if corrected_item_name is None or corrected_item_name not in item_details:
            await ctx.message.reply(f"Invalid item.", delete_after=5)
            return

        if corrected_item_name not in self.game_data["inventory"][ctx.author.id]:
            await ctx.message.reply("You don't have this item.", delete_after=5)
            return

        item_type = item_details[corrected_item_name]["type"]

        if item_type == "weapon":
            current_equipped = self.game_data["equipped_items"][ctx.author.id]["weapon"]
            self.game_data["equipped_items"][ctx.author.id]["weapon"] = corrected_item_name
            await ctx.message.reply(f"Equipped {corrected_item_name}!", delete_after=5)

        elif item_type == "defense":
            if corrected_item_name in self.game_data["equipped_items"][ctx.author.id]["defense"]:
                self.game_data["equipped_items"][ctx.author.id]["defense"].remove(corrected_item_name)
                self.game_data["defense"][ctx.author.id] -= item_details[corrected_item_name]["defense"]
                await ctx.message.reply(f"Unequipped {corrected_item_name}!", delete_after=5)
            else:
                self.game_data["equipped_items"][ctx.author.id]["defense"].append(corrected_item_name)
                self.game_data["defense"][ctx.author.id] += item_details[corrected_item_name]["defense"]
                await ctx.message.reply(f"Equipped {corrected_item_name}!", delete_after=5)

    async def cmd_hp(self, ctx):
        if not self.is_valid_command_context(ctx):
            return

        hp = self.game_data["hp"][ctx.author.id]
        max_hp = self.game_data["max_hp"][ctx.author.id]
        await ctx.message.reply(f"❤️ HP: {hp}/{max_hp}")

    async def cmd_attack(self, ctx, target: discord.Member):
        if not self.is_valid_command_context(ctx):
            return

        if target.id == ctx.author.id:
            raise commands.UserInputError("You can't attack yourself!")

        if target.id not in self.game_data["participants"]:
            raise commands.UserInputError("Invalid target.")

        if not self.is_in_same_district(ctx.author, target):
            raise commands.UserInputError("Target not in your district!")

        # Check cooldown
        cooldownID = "-".join(sorted([str(ctx.author.id), str(target.id)]))

        battle_started = False
        if cooldownID not in self.game_data["attacked_cooldowns"]:
            self.game_data["attacked_cooldowns"][cooldownID] = 0
            battle_started = True

        # If less than 10 seconds, don't attack
        diff = datetime.now().timestamp() - self.game_data["attacked_cooldowns"][cooldownID] 
        if diff < attack_cooldown:
            raise commands.UserInputError(f"You need to wait {math.ceil(attack_cooldown - diff)} seconds before attacking <@{target.id}>")

        self.game_data["attacked_cooldowns"][cooldownID] = datetime.now().timestamp()

        # Calculate damage
        weapon = self.game_data["equipped_items"][ctx.author.id]["weapon"]
        base_damage = item_details[weapon]["damage"]
        crit_chance = random.randint(1, 100)
        damage = base_damage * 2 if crit_chance > 90 else base_damage

        # Apply defense
        defense_sum = self.game_data["defense"][target.id]
        roll = random.randint(1, 100)

        # Send alerts
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])

        now = datetime.now()
        cooldown_ends = now + timedelta(seconds=attack_cooldown)
        discord_timestamp = f"<t:{str(cooldown_ends.timestamp()).split('.')[0]}:R>"
        footer = f"-# You can attack again in {discord_timestamp}"

        if battle_started:
            await alert_channel.send(f"🔥 {ctx.author.mention} started a battle with {target.mention}!")

        if roll < defense_sum:
            #Blocked!
            await ctx.message.reply(f":shield: You tried to attack {target.mention}, but they blocked your attack!\n{footer}")
        else:
            base_msg = f"⚔️ {ctx.author.mention} attacked {target.mention} for {damage} damage!"

            if crit_chance > 90:
                base_msg += "\n:fire: Critical hit!"
                self.game_data["stats"]["crits"][ctx.author.id] = self.game_data["stats"]["crits"].get(ctx.author.id, 0) + 1

            base_msg += f"\n{footer}"

            self.game_data["hp"][target.id] -= damage
            self.game_data["stats"]["damage_taken"][target.id] = self.game_data["stats"]["damage_taken"].get(target.id, 0) + damage
            self.game_data["stats"]["damage_dealt"][ctx.author.id] = self.game_data["stats"]["damage_dealt"].get(ctx.author.id, 0) + damage
            await ctx.message.reply(base_msg)

        # Handle knockout
        if self.game_data["hp"][target.id] <= 0 and target.id not in self.game_data["knocked_down"]:
            self.game_data["knocked_down"].append(target.id)
            await alert_channel.send(f"💀 {target.mention} has been knocked down!")
            await ctx.message.reply(f"You knocked down {target.mention}!")
            await self.handle_knockdown(ctx, target, ctx.author)

        self.game_data["attacked_cooldowns"][cooldownID] = now.timestamp()

    async def handle_knockdown(self, ctx, target, attacker):
        # remove target from all channels

        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        original_overwrites = {}

        # Store original overwrites and disable send_messages
        for ch_id in self.game_data["districts"].values():
            channel = self.bot.get_channel(ch_id)
            if channel:
                overwrite = channel.overwrites_for(target)
                original_overwrites[ch_id] = overwrite
                await channel.set_permissions(target, send_messages=False)

        # Notify target
        try:
            await target.send("You've been knocked down! Your attacker has 20 seconds to decide your fate...")
        except:
            pass

        # Create options embed
        embed = discord.Embed(title="Knockdown Options", description="React within 20 seconds!")
        embed.add_field(name="1️⃣", value="Kill", inline=True)
        embed.add_field(name="2️⃣", value="Rob", inline=True)
        embed.add_field(name="3️⃣", value="Slap", inline=True)

        msg = await ctx.message.reply(embed=embed)
        for emoji in ["1️⃣", "2️⃣", "3️⃣"]:
            await msg.add_reaction(emoji)

        start_time = datetime.now()
        try:
            reaction, user = await self.bot.wait_for(
                'reaction_add',
                timeout=20.0,
                check=lambda r, u: u.id == attacker.id and not u.bot and u.id in self.game_data["participants"] and str(r.emoji) in ["1️⃣", "2️⃣", "3️⃣"]
            )
        except asyncio.TimeoutError:
            pass
        else:
            if str(reaction.emoji) == "1️⃣":
                await ctx.message.reply(f":crossed_swords: You've killed {target.mention}!")
                # dm target
                try:
                    await target.send(f"You've been killed by {attacker.mention}!")
                except:
                    pass
                self.game_data["stats"]["kills"][attacker.id] = self.game_data["stats"]["kills"].get(attacker.id, 0) + 1
                await self.kill_player(target)
                return  # No need to restore permissions
            elif str(reaction.emoji) == "2️⃣":
                await self.rob_player(ctx.author, target)
                await ctx.message.reply(f":moneybag: You've robbed {target.mention}!\nThey now have 1 hp!")
                self.game_data["stats"]["robs"][attacker.id] = self.game_data["stats"]["robs"].get(attacker.id, 0) + 1
                # dm target
                try:
                    await target.send(f"You've been robbed by {attacker.mention}!\nYou will wake up shortly...")
                except:
                    pass

            elif str(reaction.emoji) == "3️⃣":
                await self.slap_player(target)
                await ctx.message.reply(f"👋 You've slapped {target.mention}!\nThey now have 1 hp and -50% max hp!")
                self.game_data["stats"]["slaps"][attacker.id] = self.game_data["stats"]["slaps"].get(attacker.id, 0) + 1
                # dm target
                try:
                    await target.send(f"You've been slapped by {attacker.mention}!\nYou will wake up shortly...")
                except:
                    pass

        # Wait remaining time and restore permissions
        elapsed = (datetime.now() - start_time).total_seconds()
        remaining = max(0, 20 - elapsed)
        await asyncio.sleep(remaining)

        # Restore permissions if target is still in game
        if target.id in self.game_data["participants"]:
            for ch_id in self.game_data["districts"].values():
                channel = self.bot.get_channel(ch_id)
                if channel:
                    await channel.set_permissions(target, overwrite=original_overwrites.get(ch_id))
            # remove from knocked down
            self.game_data["knocked_down"].remove(target.id)

    async def kill_player(self, target):
        self.game_data["participants"].remove(target.id)
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        # Remove permissions from all channels
        for ch_id in self.game_data["districts"].values():
            channel = self.bot.get_channel(ch_id)
            if channel:
                await channel.set_permissions(target, overwrite=None)
        await alert_channel.send(f"💀 {target.mention} has been eliminated!")

        # Add to top three if only <= 2 players
        if len(self.game_data["participants"]) <= 2:
            #we add to the front always
            self.game_data["top_three"].insert(0, target.id)

        #Only one player left? end game
        if len(self.game_data["participants"]) == 1:
            self.game_data["top_three"].insert(0, self.game_data["participants"][0])
            await self.end_game(self.bot.get_guild(self.game_data["districts"]["alerts"]),True)

    async def rob_player(self, attacker, target):
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        # Transfer items
        self.game_data["inventory"][target.id].remove("Fist")
        self.game_data["inventory"][attacker.id].extend(self.game_data["inventory"][target.id])
        self.game_data["inventory"][target.id] = ["Fist"]
        # Reset equipped and defense
        self.game_data["equipped_items"][target.id] = {"weapon": "Fist", "defense": []}
        self.game_data["defense"][target.id] = 0
        # Set HP to 1
        self.game_data["hp"][target.id] = 1
        await alert_channel.send(f"🎒 {attacker.mention} robbed {target.mention}! Their HP is now 1!")

    async def slap_player(self, target):
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        # Halve max HP and set current to 1
        self.game_data["max_hp"][target.id] = max(1, self.game_data["max_hp"][target.id] // 2)
        self.game_data["hp"][target.id] = 1
        embed = discord.Embed()
        embed.set_image(url="https://files.catbox.moe/8357zd.gif")
        await alert_channel.send(embed=embed)
        await alert_channel.send(f"👋 {target.mention} was slapped! Max HP reduced to {self.game_data['max_hp'][target.id]}!")

    async def cmd_explore(self, ctx):
        if not self.is_valid_command_context(ctx):
            return

        chance = random.randint(1, 100)

        if chance <= 30:
            if ctx.channel.id not in self.game_data["loot_boxes"]:
                msg = await ctx.send("🎁 A lootbox has appeared!")
                await msg.add_reaction("🎁")
                self.game_data["loot_boxes"][ctx.channel.id] = msg.id
        elif chance <= 50:
            damage = random.randint(1, 3)
            self.game_data["hp"][ctx.author.id] -= damage
            await ctx.message.reply(f"🐺 You encountered a wolf! Took {damage} damage!")
            # handle death
            if self.game_data["hp"][ctx.author.id] <= 0:
                await self.kill_player(ctx.author)
                # dm target
                try:
                    await ctx.author.send(f":wolf: You've been killed by a wolf!")
                except:
                    pass

        else:
            await ctx.message.reply("🌲 You found nothing...")

    async def cmd_heal(self, ctx):
        if not self.is_valid_command_context(ctx):
            return

        if "Healing Potions" not in self.game_data["inventory"][ctx.author.id]:
            await ctx.message.reply("No potions!", delete_after=5)
            return

        self.game_data["hp"][ctx.author.id] = min(
            self.game_data["hp"][ctx.author.id] + 2,
            self.game_data["max_hp"][ctx.author.id]
        )
        self.game_data["inventory"][ctx.author.id].remove("Healing Potions")
        await ctx.message.reply("+2 HP!", delete_after=5)

    async def cmd_travel(self, ctx, *district):
        if not self.is_valid_command_context(ctx):
            return
        district = "".join(district)
        #remove everything but numbers
        district = re.sub(r'[^0-9]', '', district)
        district = f"district-{district}"
        if district not in self.game_data["districts"]:
            raise commands.UserInputError("Invalid district!")
        # Find current district
        current_district = ctx.channel

        try:
            await ctx.author.send(f"🚶 Traveling to {district}... (30 seconds)")
            # Remove from current district
            if current_district:
                await current_district.set_permissions(ctx.author, overwrite=None)
        except:
            pass

        # delete command message
        await ctx.message.delete()
        # Wait for 30 seconds before moving
        await asyncio.sleep(30)
        # Add to new district
        new_channel = self.bot.get_channel(self.game_data["districts"][district])
        await new_channel.set_permissions(ctx.author, read_messages=True, send_messages=True)

        try:
            await new_channel.send(f"{ctx.author.mention}, you've arrived at {district}!")
            await ctx.author.send(f"✅ Arrived at {district}!")
        except:
            pass

    @tasks.loop(seconds=0)
    async def spawn_lootboxes(self):
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(random.randint(120, 600))  # 2-10 minutes
            if not self.game_data["game_started"]:
                continue

            # Spawn lootboxes in random districts
            for district, ch_id in self.game_data["districts"].items():
                if district == "alerts" or random.random() > 0.3:
                    continue

                channel = self.bot.get_channel(ch_id)
                if ch_id not in self.game_data["loot_boxes"] and channel:
                    try:
                        msg = await channel.send("🎁 A lootbox has appeared!")
                        await msg.add_reaction("🎁")
                        self.game_data["loot_boxes"][ch_id] = msg.id
                    except Exception as e:
                        print(f"Error spawning lootbox: {e}")

    async def cmd_endgamevote(self, ctx):
        if not self.is_valid_command_context(ctx):
            return

        if ctx.author.id not in self.game_data["endgame_votes"] and ctx.author.id in self.game_data["participants"]:
            self.game_data["endgame_votes"].append(ctx.author.id)
            alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
            await alert_channel.send(f"🗳️ {ctx.author.mention} has voted to end the game! ({len(self.game_data['endgame_votes'])}/{len(self.game_data['participants'])//2+1})")

            if (len(self.game_data["endgame_votes"]) >= len(self.game_data["participants"]) // 2 + 1):
                await self.end_game(ctx.guild,False)

    async def end_game(self, guild, finished):
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        await alert_channel.send("🏁 Ending game...")

        # Delete all game channels
        district_channel = self.bot.get_channel(self.game_data["districts"]["district-1"])
        category = district_channel.category
        for channel in category.channels:
            await channel.delete()
        await category.delete()



        #if alert channel still exists, send message
        msg = "🔥 The Hunger Games have concluded! 🔥"
        top_three = "**THE TOP 3 WINNERS**\n"

        winners = self.game_data['top_three']
        for i, winner in enumerate(winners):
            place_emoji = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, "🏅")
            top_three += f"{place_emoji} <@{winner}>\n"

        if not finished:
            top_three = "**DRAW GAME!**"
        award_embed = self.gen_awards_embed()
        alert_channel = self.bot.get_channel(self.game_data["districts"]["alerts"])
        if alert_channel:
            await alert_channel.send(msg + "\n" + top_three, embed=award_embed)
        else:
            await guild.system_channel.send(msg, embed=award_embed)

        # Reset game state
        self.game_data = gen_default_state()

    async def on_command_error(self, ctx, error):
        print(error)
        if isinstance(error, commands.UserInputError):
            ctx.command.reset_cooldown(ctx)
            await ctx.message.reply(f":x: {error}", delete_after=10)
            await ctx.message.delete()
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.message.reply(f"⌛ Command on cooldown! Try again in {error.retry_after:.1f} seconds.", delete_after=5)
            await ctx.message.delete()
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            print(f"Unhandled error: {type(error)} - {error}")

    def gen_registration_embed(self):
        embed = discord.Embed(
            title="Hunger Games Registration",
            description=f"React with ✅ to join!\nMinimum players: {self.game_data['min_participants']}\nMaximum players: {self.game_data['max_participants']}",
            color=0xff0000
        )
        # add field
        embed.add_field(name="Players", value=self.gen_player_list())
        return embed

    def gen_awards_embed(self):
        embed = discord.Embed(title="Awards", color=0x00ff00)
        #Find best mention for each stat
        for stat, name in stat_to_award.items():
            best_mention = None
            for user_id, value in self.game_data["stats"][stat].items():
                if not best_mention or value > self.game_data["stats"][stat][best_mention]:
                    best_mention = user_id
            if best_mention:
                embed.add_field(name=name, value=f"<@{best_mention}>")

        return embed

    async def cmd_gamestart_hungergames(self, ctx, min_participants, max_participants):
        if ctx.author.id not in admin_ids: 
            return

        if self.game_data["game_started"]:
            await ctx.message.reply("A game is already in progress!", delete_after=10)
            return

        self.game_data["min_participants"] = max(int(min_participants), 1)
        self.game_data["max_participants"] = int(max_participants)

        embed = self.gen_registration_embed()

        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        self.game_data["registration_message_id"] = msg.id
        await self.kickoff_save()

    async def cmd_commands(self, ctx):
        embed = discord.Embed(title="Available Commands", color=0x00ff00)
        embed.add_field(name="Gameplay", value="\n".join([
            "`*inventory` - View your items",
            "`*equip <item>` - Equip an item",
            "`*hp` - Check your health",
            "`*attack @player` - Attack another player",
            "`*explore` - Search for loot (1min cooldown)",
            "`*heal` - Use a healing potion",
            "`*travel <district>` - Move districts (5min cooldown)",
            "`*endgamevote` - Vote to end the game"
        ]), inline=False)

        await ctx.message.reply(embed=embed, delete_after=60)

async def setup(bot: discord.Client):
    manager = SurvivalGamesManager(bot)
    bot.survival_manager = manager

    bot.add_listener(manager.on_reaction_add, 'on_reaction_add')
    bot.add_listener(manager.on_reaction_remove, 'on_reaction_remove')
    bot.add_listener(manager.on_command_error, 'on_command_error')

    @bot.command()
    async def restore(ctx):
        await manager.cmd_restore(ctx)

    @bot.command()
    async def inventory(ctx):
        await manager.cmd_inventory(ctx)

    @bot.command()
    async def equip(ctx, *, item_name):
        await manager.cmd_equip(ctx, item_name=item_name)

    @bot.command()
    async def hp(ctx):
        await manager.cmd_hp(ctx)

    @bot.command()
    async def attack(ctx, target: discord.Member):
        await manager.cmd_attack(ctx, target)

    @bot.command()
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def explore(ctx):
        await manager.cmd_explore(ctx)

    @bot.command()
    async def heal(ctx):
        await manager.cmd_heal(ctx)

    @bot.command()
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def travel(ctx, *district):
        await manager.cmd_travel(ctx, *district)

    @bot.command()
    async def endgamevote(ctx):
        await manager.cmd_endgamevote(ctx)

    @bot.command()
    async def gamestart_hungergames(ctx, min_participants, max_participants):
        await manager.cmd_gamestart_hungergames(ctx, min_participants, max_participants)

    @bot.command(name="commands")
    async def sg_commands(ctx):
        await manager.cmd_commands(ctx)
