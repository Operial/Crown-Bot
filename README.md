# Crown Bot

Both bots merged into one Discord application, running as two independent
modules under a single shared bot process.

## Structure

```
crown_bot/
├── main.py                          # the only thing you run
├── modules/
│   ├── giveaway_module.py           # from crown.zip
│   └── survivalgames_module.py      # from survivalgsmes.zip
├── data/
│   ├── giveaway_channels.json
│   ├── active_giveaways.json
│   └── game_data.json
├── .env                             # DISCORD_TOKEN
└── requirements.txt
```

Each module file defines a `<Something>Manager` class holding that
feature's state and logic, plus an `async def setup(bot)` that attaches
the manager to the shared bot and registers that module's commands and
event listeners. `main.py` builds one bot, calls both modules' `setup()`
in `setup_hook()`, and starts both managers from a single `on_ready()`.
Neither module imports or knows about the other — to add a third module
later, drop it in `modules/` and add one line in `main.py`.

## Setup

```
pip install -r requirements.txt
python main.py
```

## The token

Two different bot tokens existed (one per zip). A running process can only
log in as one Discord bot user, so `.env` is set to the **Crown** bot's
token — it's the one already invited to your servers with giveaway channels
configured (11 servers, from `giveaway_channels.json`). Practically, this
means:

- Giveaways keep working immediately, no re-invite needed.
- For the survival games commands (`*gamestart_hungergames`, etc.) to work
  in a given server, the **Crown** bot needs to be present there with
  **Manage Channels** and **Manage Roles** permissions (survival games
  creates a category and per-district channels and sets permission
  overwrites on them — giveaway alone never needed that).
- The old survivalgsmes bot's own token still exists if you ever want to
  run that one standalone again; it's just not used here.

If you'd rather run everything under the survival-games bot's identity
instead, swap the value in `.env` for that token — nothing else changes.

## Commands

- Giveaway: all slash commands, under `/giveaway` (`setchannel`,
  `removechannel`, `create`, `cancel`, `info`).
- Survival games: prefix commands with `*` (`*gamestart_hungergames`,
  `*inventory`, `*equip`, `*attack`, `*explore`, `*heal`, `*travel`,
  `*endgamevote`, `*restore`, `*commands`, `*hp`) — same prefix and names
  as the original standalone bot.

## What changed vs. the originals

- Both modules' logic is otherwise untouched — same commands, same
  messages, same behavior.
- `survivalgames_module.py`'s save file moved from a bare `game_data.json`
  in the working directory to `data/game_data.json`, so it lives alongside
  the giveaway data files instead of wherever the process happens to be
  launched from.
- A couple of pre-existing quirks in the survival games code (e.g. a
  DM-on-error path missing an `await`, and an `end_game` call after the
  last elimination passing a channel ID where a guild ID looks intended)
  were left exactly as they were rather than silently "fixed" — happy to
  patch either if you want them changed.