# Jarvis — standalone morning-brief agent

Runs every weekday morning on GitHub Actions. No Claude app, and your computer doesn't need to be on.

1. Reads today's **Outlook** and **Google** calendars, the last 24 h of **Outlook** and **Gmail** mail, and tasks/priorities from **Notion**.
2. Claude (API, `claude-opus-5-5`) sorts the inbox, writes **draft** replies (it never sends), and picks your top 3.
3. Drafts are saved in Outlook or Gmail, next to the original email.
4. Writes the 6–8 line spoken brief, turns it into audio with Fish Audio, and saves a page in Notion.
5. Publishes the brief to your **Jarvis iPhone app**, encrypted so only your phone can read it, then sends a **push notification**.

Calendar conflicts and focus gaps are worked out in code, not by the model, so they are exact. Each source shows as online, offline or empty in the app's Sources card. A source that fails is reported as offline, never guessed.

## What to edit

- `config/profile.md`: who you are, your projects, ranked priorities, tone. Read fresh on every run.
- `.github/workflows/brief.yml`: the `cron` line sets the time, in UTC.

---

## One-time setup (about 45 minutes)

You need a GitHub account. Do the steps in order.

### 1. Create the repo
Create a **public** repo (free GitHub Pages needs public) and push this folder to it. Only code goes in the repo. Your data is never committed, and the published brief is encrypted.

Then: **Settings → Pages → Source: GitHub Actions**.

> Actions logs on a public repo are public. The agent only ever prints statuses and counts, never email or calendar content, and tokens go straight into secrets.

### 2. GitHub admin token
**Settings (your profile) → Developer settings → Fine-grained tokens → Generate**. Settings:
- Only this repo.
- Permissions: **Secrets: Read and write**, **Variables: Read and write**, **Actions: Read and write**.

Save it as a repo secret named `GH_ADMIN_TOKEN` (**Repo → Settings → Secrets and variables → Actions → New repository secret**). It is used to:
- save sign-in tokens,
- keep Microsoft's token fresh,
- stop GitHub pausing the schedule after 60 days.

### 3. Claude API key
Create a key at console.anthropic.com and save it as the secret `ANTHROPIC_API_KEY`. Expect roughly a few cents to a couple of dollars per month, depending on mail volume.

### 4. Passphrase for the app
Pick a long passphrase you can type on your phone. Save it as the secret `BRIEF_PASSPHRASE`.

### 5. Microsoft 365 (Outlook)
1. Go to portal.azure.com → **Microsoft Entra ID → App registrations → New registration**.
   - Name: `Jarvis`.
   - Supported accounts: *this organizational directory only*.
2. **Authentication**: set **Allow public client flows** to **Yes**.
3. **API permissions → Add → Microsoft Graph → Delegated**: add `Mail.ReadWrite`, `Calendars.Read`, `User.Read`, `offline_access`.
   - If Rotomill's IT blocks user consent, ask them to click **Grant admin consent**.
4. Save these as repo **variables** (not secrets):
   - `MS_CLIENT_ID`: the Application (client) ID.
   - `MS_TENANT_ID`: the Directory (tenant) ID.
5. **Actions → Connect accounts → Run workflow → step: microsoft**. Open the running log. It shows a link and a code. Sign in on your phone, and the token saves itself.

### 6. Google (Gmail + Calendar)
1. Go to console.cloud.google.com and create a project. Enable the **Gmail API** and **Google Calendar API**.
2. **OAuth consent screen**:
   - User type: External.
   - Add yourself as a test user.
   - Then click **Publish app → In production**. If you skip this, Google expires your sign-in every 7 days. You'll see an "unverified app" warning when you sign in; that's fine for your own use.
3. **Credentials → Create → OAuth client ID → Desktop app**. Save:
   - `GOOGLE_CLIENT_ID` as a **variable**.
   - `GOOGLE_CLIENT_SECRET` as a **secret**.
4. **Actions → Connect accounts → step: google-start**. Open the link from the log and approve.
5. Your browser lands on a `localhost` page that doesn't load; that's expected. Copy the value between `code=` and `&scope` from the address bar.
6. **Run workflow → step: google-finish**, and paste that value into **code**.

### 7. Notion
1. Go to notion.so/my-integrations → **New integration** (internal). Copy the token and save it as the secret `NOTION_TOKEN`.
2. In Notion, create a page called **Morning Briefs**.
3. On that page and on your tasks database/priorities pages, open **••• → Connections** and add the integration.

### 8. Voice (optional)
- Save your Fish Audio API key as the secret `FISH_AUDIO_API_KEY`.
- Save your voice's model ID as the variable `FISH_AUDIO_VOICE_ID`.

### 9. Other variables
- `TIMEZONE`, e.g. `America/Toronto`.
- `USER_NAME`: `Satty`.
- `VAPID_SUBJECT`: `mailto:` followed by your email.

### 10. Install the iPhone app
1. **Actions → Connect accounts → step: push-keys**. This creates the notification keys.
2. **Actions → Morning brief → Run workflow**. This is the first real brief.
3. On your iPhone, open `https://<your-github-name>.github.io/<repo-name>/` in **Safari**.
4. Tap **Share → Add to Home Screen**.
5. Open **Jarvis** from the Home Screen and enter your passphrase.
6. Tap **Turn on morning notifications** and allow them. Copy the text shown and save it as the secret `PUSH_SUBSCRIPTIONS`.

From then on you get a notification every weekday morning. Tap it to read the brief or play the audio.

## Run it now
**Actions → Morning brief → Run workflow**. In the GitHub mobile app, this works from your phone too.

## Test locally without any accounts
```bash
pip install -r requirements.txt
BRIEF_PASSPHRASE=test python -m agent.main --demo
cd site && python -m http.server 8000   # open localhost:8000, passphrase "test"
```

## Hard rules built in
- **Draft only.** The code has no send, delete or RSVP calls at all.
- **No drafts for money, passwords or credentials.** Those are listed as "handle yourself".
- **Email content is treated as data, never as instructions.** Any email that tries to instruct the assistant is flagged as suspicious.
- **A source that fails is reported as offline.** Counts for an offline source show "—", not 0.

---

## Jarvis server (talking assistant + new app)

An always-on server on Oracle Cloud's free tier runs:
- the new **Jarvis app**: Today, Ask (chat and voice) and Settings, at `https://<your-name>.duckdns.org`,
- the **talking assistant**: Claude on your subscription with tools for Outlook, Gmail, both calendars and Notion. It can draft replies (never sends), and adding a to-do needs your **Confirm** tap,
- the **morning brief** at 6:45 am on weekdays (`BRIEF_TIME` variable), plus a **refresh** button for a quick, time-aware brief,
- **voice**: speech-to-text on the server (Whisper, free), replies spoken by Fish Audio or the iPhone's own voice.

### Setup
1. Create an Always Free **VM.Standard.A1.Flex** (Ubuntu 24.04) on Oracle. Open ports **80** and **443** in its subnet's security list.
2. Get a free name at **duckdns.org** that points at the server's public IP.
3. Add these to the repo:
   - **Variable** `SERVER_HOST`: e.g. `satty-jarvis.duckdns.org`
   - **Secret** `SERVER_SSH_KEY`: the full contents of the private key file Oracle gave you
   - **Secret** `DUCKDNS_TOKEN`: your DuckDNS token
4. **Actions → Deploy server → Run workflow.** It copies Jarvis to the server, writes your existing secrets into it, and sets up HTTPS and auto-start.
5. On your iPhone, open `https://<your-name>.duckdns.org` in Safari → **Share → Add to Home Screen**. Sign in with your `BRIEF_PASSPHRASE`, then **Settings → Morning notification → Turn on**.
6. Once the server brief works, disable the old GitHub schedule (**Actions → Morning brief → ••• → Disable workflow**), so you don't get two briefs.

### Updates
Upload a `jarvis-update.zip` to the top of the repo. The **Apply update zip** workflow unpacks it into the right folders and redeploys the server. Any change pushed to `agent/`, `server/`, `web/` or `config/` also redeploys.
