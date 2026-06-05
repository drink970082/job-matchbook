# Full Environment Setup

This guide sets up the **entire** system end to end: the Next.js web app
(`apps/web/`) **and** the semi-automated job-hunt pipeline worker
(`apps/worker/`). If you only want the application tracker without the pipeline,
skip to [Web app only](#option-a--web-app-only).

```
companies ─► fetch (Greenhouse/Lever/Ashby) ─► score (local Ollama)
          ─► tailor 1-page resume (Claude + tectonic) ─► notify (Telegram)
          ─► review in the "Discovered Jobs" tab ─► you apply by hand
          ─► one-click "Mark Applied" ─► becomes a tracked application
```

The web app and the worker **share one SQLite database** (`db/applications.db`).
Prisma owns the schema; the worker only reads/writes rows.

---

## 1. Prerequisites

| Tool | Why | Notes |
|------|-----|-------|
| **Docker + Docker Compose** | run both services | `docker --version` ≥ 24 recommended |
| **Node 20+** | only for local (non-Docker) web dev | Docker image bundles its own |
| **Python 3.11+** | only for local (non-Docker) worker / running tests | |
| **Ollama** + an NVIDIA GPU | local resume scoring (free, no rate limits) | runs on the **host**, not in a container |
| **Anthropic API key** | resume tailoring (Claude writes the LaTeX) | only the high-scoring jobs hit the API |
| **Telegram account** | receive the daily alert + PDF | bot is free to create |

> **Why Ollama on the host?** It uses your GPU (e.g. an RTX 4060) directly. GPU
> pass-through into a container needs `nvidia-container-toolkit` and is fiddly
> under WSL2, so the worker reaches the host Ollama over
> `host.docker.internal:11434` instead.

---

## 2. Clone & pick UID/GID

```bash
git clone <your-repo> ats
cd ats
```

Both containers run as your host user so they can co-write the shared SQLite
file. Export your IDs once (compose reads them):

```bash
export UID=$(id -u) GID=$(id -g)
```

---

## Option A — Web app only

If you don't want the pipeline yet:

```bash
# from the repo root
docker compose up web --build -d      # starts ONLY the web service
```

Open <http://localhost:3000>. The worker service is defined but not started.
(For local dev without Docker, see [`apps/web/README.md`](../apps/web/README.md).)

To add the pipeline later, continue below.

---

## Option B — Full pipeline

### 3. Provide the three config-time inputs

These live in `apps/worker/` and are **gitignored** (they're personal / secret).

#### 3a. `config.yaml` — which boards to scan

Edit [`apps/worker/config.yaml`](../apps/worker/config.yaml):

```yaml
companies:
  - { source: greenhouse, slug: stripe,    name: "Stripe" }
  - { source: lever,      slug: ramp,      name: "Ramp" }
  - { source: ashby,      slug: linear,    name: "Linear" }

filters:
  keywords:  ["engineer", "ml", "backend"]   # keep if title/JD contains ANY
  locations: ["remote", "new york"]          # AND location contains ANY (or empty = all)

threshold: 75              # min Ollama score (0–100) before we tailor a resume
schedule_hours: 24         # how often the worker re-scans
max_single_page_rounds: 3  # max Claude retries to squeeze the resume to 1 page
```

The **`slug`** is the company's handle in the board URL:

| Board | URL you see | slug |
|-------|-------------|------|
| Greenhouse | `boards.greenhouse.io/stripe` | `stripe` |
| Lever | `jobs.lever.co/ramp` | `ramp` |
| Ashby | `jobs.ashbyhq.com/linear` | `linear` |

A bad `source` or missing field is caught at startup with a clear error.

#### 3b. Your resume — two files

Put both in `apps/worker/resume/` (see [`resume/README.md`](../apps/worker/resume/README.md)):

- `master.tex` — your **one-page** LaTeX master resume. Claude tailors a copy per
  high-scoring job (only reorders / rephrases — **never fabricates**), then
  `tectonic` compiles it to PDF.
- `resume.txt` — plain-text version, fed to the Ollama scorer (saves tokens).

#### 3c. `.env` — secrets

```bash
cp apps/worker/.env.example apps/worker/.env
```

Fill in:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_CHAT_ID=123456789
OLLAMA_HOST=http://host.docker.internal:11434   # leave as-is for Docker
```

### 4. Create the Telegram bot (5 minutes)

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts. It returns a
   **bot token** like `123456789:ABCdef...` → that's `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it any message (e.g. "hi"). This is
   required before a bot can message you.
3. Get your **chat id**:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":[0-9-]*'
   ```
   Use the number after `"id":` → that's `TELEGRAM_CHAT_ID`.

### 5. Set up Ollama on the host

```bash
# Install: https://ollama.com/download  (or `curl -fsSL https://ollama.com/install.sh | sh`)
ollama pull qwen2.5:7b        # ~4.7GB Q4; fits 8GB VRAM. llama3.1:8b also works.
ollama serve                  # leave running (systemd unit does this automatically)

# sanity check it answers:
curl http://localhost:11434/api/tags
```

> The default scoring model is `llama3.1` (see `run.py` `DEFAULT_OLLAMA_MODEL`).
> If you pulled `qwen2.5:7b` instead, either also `ollama pull llama3.1` or change
> that default.

### 6. Launch everything

From the repo root:

```bash
UID=$(id -u) GID=$(id -g) docker compose up --build
```

This starts:
- **web** on <http://localhost:3000>
- **worker** — runs one pass immediately, then every `schedule_hours`

Both mount the **`./db` directory** (so SQLite WAL works across both containers)
and the **`./resumes` volume** (worker writes tailored PDFs; the web app's
`/api/resume/[id]` route serves them).

### 7. Verify end-to-end

```bash
# One-off test pass without waiting for the schedule (run inside the worker):
docker compose run --rm worker python -m ats_worker.run --once \
  --config /app/config.yaml --env /app/.env
```

Then:
1. Open <http://localhost:3000> → **Discovered Jobs** tab → you should see scored
   postings (highest first).
2. Click a row's JD icon → the dialog shows matched/missing keywords + reasoning,
   and **Download Resume (PDF)** for tailored ones.
3. Check Telegram for the alert + PDF on high scorers.
4. Click **Mark Applied** → it leaves the queue and appears under **Applications**
   (and in all the charts).

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `docker compose up` errors mounting `apps/worker/.env` | You skipped step 3c. The file must exist (compose mounts it read-only). |
| Worker logs `Connection refused` to Ollama | `ollama serve` isn't running on the host, or `OLLAMA_HOST` is wrong. On Linux confirm `host.docker.internal` resolves — the compose `extra_hosts: host-gateway` handles it. |
| First tailoring hangs for a long time | `tectonic` is downloading its package bundle. The worker image **prewarms** it at build, so this should only happen if you changed the LaTeX to need new packages. |
| Resume download 404/403 in the web UI | `resume_path` must resolve under `RESUME_DIR` (`/resumes`). Confirm both services mount the same `./resumes`. |
| `database is locked` | Should not happen (WAL + busy_timeout). Verify the **directory** `./db` is mounted into both — a single-file mount breaks cross-container WAL. |
| Scores look random / not JSON | The model returned junk; the worker marks that row `failed` with the error rather than crashing. Try a stronger model. |

---

## What runs where (mental model)

| Piece | Runs in | Talks to |
|-------|---------|----------|
| Next.js web app | `web` service (`ats-web` container) | shared SQLite (read postings, write applications) |
| fetch / score / tailor / notify | `worker` service (`ats-worker` container) | board APIs, host Ollama, Anthropic API, Telegram API |
| Ollama | **host** (GPU) | — |
| SQLite db | `./db` (bind-mounted into both) | — |
| Tailored PDFs | `./resumes` (bind-mounted into both) | — |

See [`pipeline-design.md`](./pipeline-design.md) for the original design and
[`apps/worker/README.md`](../apps/worker/README.md) for worker internals.
