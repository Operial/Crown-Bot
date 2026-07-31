# Crown Bot

Both original bots plus a new AI assistant, merged into one Discord
application, running as three independent modules under a single shared
bot process.

## Structure

```
crown_bot/
├── main.py                          # the only thing you run
├── modules/
│   ├── giveaway_module.py           # from crown.zip
│   ├── survivalgames_module.py      # from survivalgsmes.zip
│   └── ai_assistant_module.py       # new: mention-triggered AI assistant
├── data/
│   ├── giveaway_channels.json
│   ├── active_giveaways.json
│   ├── game_data.json
│   └── ai_assistant_index.sqlite3   # indexed message history (gitignored)
├── .env                             # DISCORD_TOKEN + AI provider config
└── requirements.txt
```

Each module file defines a `<Something>Manager` class holding that
feature's state and logic, plus an `async def setup(bot)` that attaches
the manager to the shared bot and registers that module's commands and
event listeners. `main.py` builds one bot, calls all three modules'
`setup()` in `setup_hook()`, and starts the managers that need it from a
single `on_ready()`. No module imports or knows about the others — to add
a fourth module later, drop it in `modules/` and add one line in
`main.py`.

## Setup

```
pip install -r requirements.txt
python main.py
```

The AI assistant uses a configured model provider in `.env` for general
questions — either a local Ollama model (free, runs on your own machine) or
the Anthropic API (costs money, runs anywhere). Direct "find me this post"
link searches use the local ranked index and still work without a model.
Giveaways and survival games remain independent of either AI provider.

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
- AI assistant: no command — just @-mention the bot with a question
  anywhere in the server, e.g. `@CrownBot find me the Carthago and Aurora
  merge post`. `*aiindex [limit]` (Manage Server permission required)
  backfills the configured archive channels; with no limit supplied it indexes
  all available history. It is safe to re-run whenever needed.

## AI assistant

Mention the bot with a question anywhere in the server. The assistant now has
an entity-aware planning step before it searches, so words such as `first`,
`ever`, `news`, and `alliance` are interpreted as instructions instead of being
used as the main search terms.

Examples:

```text
@Crown give me the first ever news of Citadel (the alliance)
@Crown who is Kev?
@Crown summarize Carthago and Aurora separately
@Crown find the Carthago and Aurora merger
@Crown what is this?   + attach an alliance logo
```

Search results remain restricted to these channel IDs unless
`AI_SEARCH_CHANNEL_IDS` overrides them in `.env`:

```text
821587932644900901
821587932644900902
821587932825124866
821587932644900903
821587932825124865
821587932825124864
```

### What changed

- **Live synchronization:** new messages in the configured channels are indexed
  automatically. Edits replace the indexed copy and deletions remove it.
- **Offline catch-up:** when the bot restarts, it fetches every message posted
  after the newest indexed message in each configured channel. `*aiindex` is
  still available for a complete/manual rebuild.
- **Entity-aware searches:** the assistant resolves official Politics & War
  alliance names, nation names, leader names, IDs, links, and flags before
  searching the archive. This prevents a request for Citadel from returning
  posts that merely contain generic words such as `first`, `ever`, or
  `alliance`.
- **Correct chronology:** `first`, `earliest`, and `oldest` return the oldest
  exact subject match; `latest` and `newest` return the newest.
- **Multiple-subject reasoning:** `Who are A and B?` searches separate profiles,
  while `A and B merger` requires a shared report mentioning both subjects.
- **Name-only summaries:** a message containing only a name is treated as a
  profile/summary request. Discord mentions and exact member display names are
  also used as person aliases.
- **Better message coverage:** plain text, embed titles/descriptions/fields,
  embed links, attachment names, attachment URLs, thumbnails, and images are
  indexed.
- **Logo matching:** official alliance flags are cached and perceptually hashed.
  Uploaded or resized copies can be matched to an alliance. Historical news
  images are also hashed while indexing when `AI_HASH_MEDIA=true`.
- **Optional visual understanding:** set `OLLAMA_VISION_MODEL` to a vision-capable
  Ollama model to analyse screenshots and images that are not exact flag copies.
- **Evidence rules:** event/reputation claims must come from the Orbis Crowned
  News archive. P&W API data is used only to resolve identity and logos. The bot
  refuses unsupported popularity/bias rankings and does not mine someone's
  history for humiliating material.

### Politics & War API setup

The official GraphQL endpoint is called with a POST request and the API key as
an `api_key` query parameter. The code refreshes alliances and paginated nations
in the background and keeps a local fallback cache in
`data/pnw_entity_cache.json`.

```env
PNW_API_KEY=replace-with-your-new-key
PNW_GRAPHQL_URL=https://api.politicsandwar.com/graphql
PNW_REFRESH_SECONDS=21600
PNW_PAGE_SIZE=500
```

The refresh queries request:

```graphql
query {
  alliances(first: 500, page: 1) {
    id
    flag
    name
  }
}
```

and paginated nation pages:

```graphql
query {
  nations(first: 500, page: 1) {
    id
    flag
    nation_name
    leader_name
  }
}
```

Use `*airefreshpnw` (Manage Server permission) to force an immediate refresh.
If the API is unavailable, the bot keeps using the last successful cache.

### Choosing a model

For local Ollama:

```env
AI_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_CTX=8192
OLLAMA_VISION_MODEL=
```

`qwen2.5:7b` handles planning and summaries but is text-only. To inspect images,
set `OLLAMA_VISION_MODEL` to a vision-capable model installed in Ollama. Leave it
blank when GPU/RAM is limited; exact/perceptual flag matching still works.

For Anthropic:

```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=replace-with-key
AI_MODEL=claude-haiku-4-5-20251001
```

Exact `first`, `latest`, and `find` lookups do not depend on a model. When the
model is unavailable, the bot still returns matched Discord source posts instead
of inventing a summary.

### Commands

- `*aiindex [limit]` — manually backfill/rebuild configured channels.
- `*airefreshpnw` — refresh official alliance/nation/leader identity metadata.

Both commands require **Manage Server**.

### Security

- Secrets are read from `.env` and never included in model prompts or the source
  bundle used for “how do you work?” questions.
- Retrieved Discord content, image descriptions, and API metadata are treated as
  untrusted data, not instructions.
- Search results are permission-checked against the member who asked.
- The assistant remains guild-only and has a per-user cooldown.
- Do not hardcode tokens or API keys in Python files or commit `.env`.

## What changed vs. the originals

- `ai_assistant_module.py` is new — it wasn't in either original zip.
- The giveaway and survival games modules' logic is otherwise untouched — same commands, same
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
  
