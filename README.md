# MWBE Procurement Monitor

React + Vite dashboard for monitoring government procurement opportunities in immigration legal services across NYC, NYS, Nassau, and Suffolk County.

## Architecture

```
GitHub Actions (Mon/Thu 7am ET)
  └── scraper/run.py
        ├── NYC Open Data / PASSPort
        ├── Checkbook NYC
        ├── NYS Contract Reporter
        ├── Nassau County Portal
        └── Suffolk County Portal
              ↓ LLM scoring (Ollama)
              ↓ writes public/data/opportunities.json
              ↓ git commit → triggers Vercel redeploy
                    ↓
              React + Vite dashboard
```

## Deploy to Vercel

1. Push repo to GitHub
2. Import in [vercel.com](https://vercel.com) → Framework: Vite → Build: `npm run build` → Output: `dist`
3. Add GitHub secrets (Settings → Secrets → Actions):

| Secret | Description |
|---|---|
| `OLLAMA_BASE_URL` | Your Ollama Cloud endpoint, e.g. `https://ollama.yourhost.com` |
| `OLLAMA_MODEL` | Model name, e.g. `llama3.1:8b` |
| `FIRM_NAME` | Your firm name for LLM context |
| `MIN_FIT_SCORE` | Minimum score to include (default: 5) |

4. Enable GitHub Actions write permissions: Settings → Actions → General → Workflow permissions → Read and write

## Local dev

```bash
npm install
npm run dev
```

Scraper (requires Python 3.11+):
```bash
pip install requests beautifulsoup4
cd scraper && python run.py
```

## Data format

`public/data/opportunities.json` is the single source of truth. The scraper appends new results and retains existing ones up to 90 days. Opportunities score below `MIN_FIT_SCORE` are excluded.

## Customization

- Edit keyword list in `scraper/run.py` → `KEYWORDS`
- Adjust fit score threshold via `MIN_FIT_SCORE` secret
- Add new portal scrapers as functions in `scraper/run.py` and call them in `main()`
