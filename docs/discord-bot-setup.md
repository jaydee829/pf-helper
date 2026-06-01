# PF_Helper Discord Bot — Setup & Live Test

A step-by-step guide to get the bot running and verify it, assuming you've
**never set up a Discord bot before**. Should take ~15 minutes.

The bot has three slash commands:
- `/lookup <name>` — look up one rules entry (instant, local, no AI).
- `/search <query>` — search the rules (instant, local, no AI).
- `/ask <question>` — natural-language rules answer (uses Claude on your
  subscription).

---

## Part 1 — Create the Discord bot (in your browser)

1. Go to **https://discord.com/developers/applications** and log in with your
   Discord account.
2. Click **New Application** (top right). Name it something like `PF Helper`,
   accept the terms, and click **Create**.
3. In the left sidebar, click **Bot**.
4. Click **Reset Token** → **Yes, do it!** → **Copy**. This is your
   **bot token** — a long secret string. **Copy it somewhere safe now; Discord
   only shows it once.** Treat it like a password (anyone with it can control
   the bot). You'll paste it in Part 3.
5. Scroll down to **Privileged Gateway Intents**. You do **not** need any of
   these (Message Content, etc.) — slash commands work without them. Leave them
   off.

## Part 2 — Invite the bot to your server

1. Left sidebar → **OAuth2** → **URL Generator**.
2. Under **Scopes**, check **`bot`** and **`applications.commands`**.
3. A **Bot Permissions** box appears below. Check **Send Messages** and
   **Embed Links** (that's all it needs).
4. Copy the **Generated URL** at the bottom, paste it into a new browser tab,
   choose your Discord server, and click **Authorize**.
5. The bot now appears in your server's member list (offline until you run it
   in Part 4).

## Part 3 — Get your Server ID (recommended)

This makes the slash commands appear **instantly**. (Without it, Discord can
take up to an hour to show them.)

1. In Discord: **User Settings** (gear icon) → **Advanced** → turn on
   **Developer Mode**.
2. Right-click your **server icon** (left edge) → **Copy Server ID**. That long
   number is your **guild ID** for Part 4.

---

## Part 4 — Set up and run the bot (on this PC)

Open **PowerShell** in the project folder (`C:\Users\jayde\Documents\PF_Helper`).

1. **Install the bot dependencies** (one time):
   ```powershell
   uv sync --extra bot
   ```

2. **Run first-time setup** — this builds the rules index, stores your bot
   token in the config file, and optionally registers the MCP server:
   ```powershell
   pf-helper setup
   ```
   When prompted for the Discord bot token, paste the token you copied in Part 1.
   When prompted for your guild/server ID, paste the number from Part 3.
   The token is saved to the config file — you won't need to re-enter it each
   session. (Alternatively, skip this and set `DISCORD_BOT_TOKEN` as an
   environment variable in your shell session instead.)

   `pf-helper setup` also offers to configure the `/ask` LLM provider. The
   default is the Claude Agent SDK (your Claude subscription — no API key). If
   you choose `litellm`, you must also install the extra and supply the
   provider's API key env var:
   ```powershell
   uv sync --extra bot --extra litellm
   $env:OPENAI_API_KEY = "sk-..."   # or GEMINI_API_KEY, etc.
   ```
   Local models via Ollama work without any API key.

3. **Sign in to Claude** (needed only for `/ask` — it uses your Claude
   subscription, no API key). You're likely already signed in via Claude Code;
   if `/ask` later says it needs sign-in, run:
   ```powershell
   claude setup-token
   ```
   and export the resulting token:
   ```powershell
   $env:CLAUDE_CODE_OAUTH_TOKEN = "paste-the-setup-token-here"
   ```
   On this machine `claude login` is usually enough and no token is needed.

4. **Run the bot:**
   ```powershell
   pf-helper bot
   ```
   You should see a log line like `Logged in as PF Helper#1234`. The bot is now
   **online** in your server. Leave this window open while you test.
   - If you see a *"file is being used by another process"* error, Claude
     Desktop's background server is holding the shared executable — either fully
     quit Claude Desktop, or run `uv run --no-sync pf-helper bot` instead.

To stop the bot, press **Ctrl+C** in that PowerShell window.

---

## Part 5 — Live test checklist

In any channel the bot can see, type each command and confirm the result:

- [ ] **`/lookup Frightened`** → an embed titled **Frightened** (the title is a
      link to Archives of Nethys), with the condition text and a "Full entry on
      AON" link.
- [ ] **`/search status penalty`** → an embed listing several matching entries,
      each name linking to its AON page.
- [ ] **`/ask How does flanking work?`** → an answer embed, with a **Sources
      (Archives of Nethys)** field of links and a footer like *answered via
      agent*. (First run may take a few seconds — that's normal.)
- [ ] **Ask the exact same `/ask` question again** → it returns almost
      instantly and the footer now says *answered via cache* (no Claude usage).
- [ ] **`/lookup Grabbing`** (an AON-only trait) → confirms the AON supplement
      content is reachable through the bot.
- [ ] *(Optional)* If you ever hit your Claude rate limit, `/ask` should reply
      with a "try `/lookup` or `/search`" message rather than erroring — and
      `/lookup`/`/search` keep working (they never use Claude).

If all of those behave as described, the bot is verified. 🎉

---

## Troubleshooting

- **Slash commands don't appear:** make sure you provided your guild/server ID
  during `pf-helper setup` (or set `PF_HELPER_DISCORD_GUILD_ID` before running);
  without it they're global and take up to an hour. Try re-running the bot, and
  refresh Discord (Ctrl+R).
- **Bot shows offline:** the `pf-helper bot` window must stay open; check it for
  an error. Re-check the bot token (re-run `pf-helper setup` if needed).
- **`/ask` says it needs sign-in:** run `claude setup-token` and set
  `CLAUDE_CODE_OAUTH_TOKEN` (Part 4, step 3). `/lookup` and `/search` work
  regardless.
- **"Rules index not found":** run `pf-helper ingest`.
- **The bot token leaked** (committed, shared, etc.): go back to the Developer
  Portal → Bot → **Reset Token** to invalidate the old one, then re-run
  `pf-helper setup` to store the new token.

## Running it long-term

The steps above run the bot only while the PowerShell window is open and only
in that session. To keep it always online, run it on an always-on machine (a
small VPS or a Raspberry Pi): copy the repo there, run `pf-helper setup` to
build the index and store the token, set `DISCORD_BOT_TOKEN` and
`CLAUDE_CODE_OAUTH_TOKEN` as persistent environment variables (or rely on the
config file written by setup), and run `pf-helper bot` under a process manager.
Same commands — only the host differs.
