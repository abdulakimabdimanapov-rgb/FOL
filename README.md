# FOL

FOL is an AI assistant for your Mac. It lives in the notch (top of the screen) and helps you with everyday tasks. It can open apps, search the web, write letters, remember things, and more.

## What FOL can do

- **Open apps and control your computer** — just say "open Safari" or "close Chrome"
- **Search the internet** — ask anything and FOL will find the answer
- **Write things** — letters, emails, notes
- **Remember things** — FOL saves notes to Obsidian so you don't forget
- **Talk to you** — you can type or use voice (microphone button)
- **Works in Russian and English** — you can mix both languages

## How to install

### What you need

- Mac with Apple Silicon (M1, M2, M3, or M4)
- macOS 14 or newer
- Python 3 (install with `brew install python@3.12` if you don't have it)

### Step 1: Download

```bash
git clone <repo-url> fol-app
cd fol-app
```

### Step 2: Set up

```bash
cp .env.template .env
```

Open `.env` in any text editor and add your API key. You need at least one:

```env
# Choose one of these:
LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
# LLM_MODEL=openai/gpt-4o-mini
# LLM_MODEL=claude-sonnet-4-20250514
```

Get a free API key at [openrouter.ai](https://openrouter.ai) — it takes 2 minutes.

### Step 3: Install

```bash
pip install -r requirements.txt
```

### Step 4: Run

```bash
./run_all.sh
```

That's it! FOL is now running.

### What happens when you run

Three servers start:
- **Port 8420** — the brain (processes your messages)
- **Port 8421** — the hands (controls apps and browser)
- **Port 8754** — the API (for the Swift app)

## If you want the Mac app (optional)

```bash
cd fol-app
swift build
swift run
```

This builds a small app that sits in your MacBook's notch. You can also use the web chat at `http://localhost:3000`.

## How to stop

Press `Ctrl+C` in the terminal where FOL is running.

## Troubleshooting

**"Port already in use"** — something else is using the port. Run:
```bash
lsof -ti :8420 | xargs kill
```

**"Python not found"** — install Python:
```bash
brew install python@3.12
```

**"API key error"** — make sure you put your key in the `.env` file.

## Tests (for developers)

```bash
python3 -m pytest tests/ -v
python3 -m pytest fol/tests/ -v
```

## License

MIT — do whatever you want with it.
                 