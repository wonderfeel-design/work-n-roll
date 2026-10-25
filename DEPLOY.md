# Cloud deployment on Render (branch `cloud`)

This branch deploys the current Work'n'Roll to Render. `main`, the Macs and the landing page at
work-n-roll.tech stay as they are: Render only reads this branch.

| Render service | What it runs | Plan (Frankfurt) |
|---|---|---|
| `workn-roll-console` (web) | Agronomist console, `uvicorn app.web:app` on port 8000 | `0.5c-512mb`, always on |
| `workn-roll-bot` (worker) | Telegram bot, `python -m app.bot` (long polling, no public URL) | `0.5c-512mb` |
| `workn-roll-db` (PostgreSQL 16) | Records, corrections, parcels, vocabulary, UI strings | `0.1c-256mb` |

Everything is defined in [`render.yaml`](render.yaml). The image is the repo's `Dockerfile` (Python 3.12 +
ffmpeg, so voice replies work). Check current prices on render.com/pricing before creating it.

## Before you start

1. **A second Telegram bot.** In Telegram, open @BotFather → `/newbot` → e.g. `wnroll_cloud_bot`. Copy its
   token. Don't reuse the token of @wnroll_bot: only one running copy of a bot gets each message, so the
   cloud bot and a Mac bot would steal each other's messages.
2. **Keys.** `GEMINI_API_KEY` (ideally from the Google AI Studio project that holds the Gemini credit) and
   `ELEVENLABS_API_KEY`. Reusing the Mac keys works, but the copies then share quotas and credits.
3. **A strong console password.** The console is on the public internet; don't use `admin`.

## Create the services

1. Render dashboard → **New** → **Blueprint** → connect the GitHub repo `wonderfeel-design/work-n-roll`.
2. Pick branch **`cloud`**. Render reads `render.yaml` and lists the three resources.
3. Fill in the secrets it asks for (`sync: false` in `render.yaml`):
   - console: `WEB_PASSWORD`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`
   - bot: `TELEGRAM_TOKEN` (the second bot), `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `AGRONOMIST_CHAT_ID`
     (optional; leave empty to skip review notifications)
4. **Apply.** Render creates the database, builds the image, runs `python -m app.seed` before each console
   deploy (parcels, vocabulary, UI strings; records are never touched), then starts the console and the bot.
5. Open the console's `….onrender.com` URL → log in as `agronomist` with your `WEB_PASSWORD`.

## Custom domain `app.work-n-roll.tech`

1. Console service → **Settings** → **Custom Domains** → add `app.work-n-roll.tech`.
2. At the domain registrar (DNS is on the `orderbox-dns.com` name servers), add the record Render shows,
   normally: `CNAME`  `app`  →  `workn-roll-console.onrender.com`.
3. Render issues the HTTPS certificate once DNS resolves (minutes, sometimes up to an hour).

The landing page keeps `work-n-roll.tech` on GitHub Pages; don't change those A records.

## Check it works

1. Send the new bot `/start`, your name, then: "Watered the Gala block today, about 120 cubic metres."
2. Press ✅ on the card.
3. Reload the console: the record is there.
4. Logs: Render dashboard → each service → **Logs**.

## Updating

- `git checkout cloud && git merge main && git push` deploys the latest `main` (auto-deploy on each push
  to `cloud`).
- During a deploy Render starts the new bot before stopping the old one, so for a few seconds two copies
  poll Telegram; the log may show a "Conflict" warning once. Messages aren't lost: Telegram keeps them.

## Good to know

- **Files aren't kept across deploys.** Farmers' audio, the TTS cache, exports and logs under `data/` live
  in the container and are lost on each deploy or restart. Records are safe in PostgreSQL. If the TTS cache
  matters (it saves ElevenLabs credits), add a disk to the console in `render.yaml`
  (`disk: {name: data, mountPath: /app/data, sizeGB: 1}`); a disk serves one service only.
- **The database is private.** `ipAllowList: []` allows connections only from Render's own network. To
  copy data from a Mac (`pg_dump` / `pg_restore`), temporarily add your IP in the database's
  **Access Control** settings, then remove it.
- **Backups.** Check which backup options the database plan includes; otherwise run a periodic `pg_dump`.
- **Gemma on the Gemini API is free-only** (no paid tier), so Gemini credit doesn't raise the bot's limits;
  it does give the console's voice assistant (`gemini-3.5-flash`) paid-tier limits once billing is on.
