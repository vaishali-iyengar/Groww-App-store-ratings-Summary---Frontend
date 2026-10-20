# Groww Review Pulse Simulator

Frontend built for generating a summary of the latest customer reviews of the **Groww** app from the Google Play Store.

Pick how many recent weeks of reviews to look at (1 to 10). An AI agent groups the reviews into themes and writes a one-page "pulse" that shows:

- **Reviews used, weeks considered and the review dates**
- **Top themes:** the 3 most discussed topics, with share of reviews, average star rating and change since the previous week
- **What users say:** real quotes from reviews, word for word
- **Action items:** 3 next steps, each with an owner (Product, Support or Growth)

## How it works

```
Browser (public/)                Vercel Function (index.py → src/api)
┌──────────────────────┐         ┌─────────────────────────────────────────────┐
│ Week picker, 1–10    │  POST   │ 1. Keep reviews from the last N weeks       │
│ "Run pulse"          │ ──────► │ 2. Group them into themes (k-means on saved │
│                      │         │    embeddings; Groq LLM names the themes)   │
│ Results: themes,     │ ◄────── │ 3. Groq LLM writes the headline, summaries  │
│ quotes, action items │  JSON   │    and actions; quotes are picked verbatim  │
└──────────────────────┘         │ 4. Validate: ≤250 words, exact quotes, no   │
                                 │    personal data                            │
                                 └─────────────────────────────────────────────┘
```

- **Data:** a snapshot of public Play Store reviews (`data/clean/`). Personal details such as emails and phone numbers are masked before the data gets here; raw reviews are never stored in this repo.
- **Embeddings:** pre-computed sentence embeddings (`data/themes/`), so the app needs no large ML model at runtime.
- **Offline mode:** a checkbox on the page skips the LLM and uses keyword theme names and template text. Useful for demos without an API key.
- **No sending:** the simulator only displays results. It doesn't create documents or send email.

## Repository layout

| Path | What it is |
| --- | --- |
| `index.py` | Entry point Vercel runs: creates the FastAPI app |
| `src/api/` | The API (`server.py`) and the simulator logic (`simulate.py`) |
| `src/themes/` | Theme finding: clustering, labelling, ranking |
| `src/pulse/` | Writing the note: quote picking, LLM writer, rendering |
| `src/validate.py`, `src/clean/` | Checks on the note: length, exact quotes, personal data |
| `public/` | The web page (HTML, CSS, JavaScript), served by Vercel's CDN |
| `data/` | Review snapshot and its embeddings |
| `config.yaml` | Settings: number of themes, word limit, LLM model |
| `vercel.json`, `.python-version`, `requirements.txt` | Vercel settings, Python 3.12, dependencies |

## API

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/snapshot` | Snapshot date and review count per week |
| `POST` | `/api/pulse` with `{"weeks": 4, "use_llm": true}` | The pulse: counts, headline, themes, quotes, actions |

`weeks` must be a whole number from 1 to 10; anything else returns 422.

## Deploy on Vercel

1. On [vercel.com/new](https://vercel.com/new), import this repository. The framework is detected as **FastAPI**; keep the root directory as `./`.
2. Add these environment variables:

   | Name | Value | Why |
   | --- | --- | --- |
   | `GROQ_API_KEY` | your Groq API key | The LLM that names themes and writes the note |
   | `PULSE_SYNC` | `1` | Run each pulse inside one request (serverless) |
   | `PULSE_NO_ENCODER` | `1` | Use the saved embeddings only; never load an ML model |

3. Deploy. The first run after the app has been idle takes about 15 seconds while libraries load; later runs take under a second offline and about 5 seconds with the LLM.
4. Recommended: turn on **Settings → Deployment Protection**, because every run uses the Groq quota.

## Run locally

```
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt uvicorn
export GROQ_API_KEY=...  PULSE_SYNC=1  PULSE_NO_ENCODER=1
uvicorn index:app --port 8000
```

This serves the API only. To see the page, run any static server for `public/` against it, or use the full project's `python -m src.api`, which serves both.

## Updating the reviews

This repository is generated. In the main project, the weekly job fetches and cleans new reviews; then `scripts/build_vercel.sh` rebuilds this folder with the newest snapshot. Commit and push, and Vercel redeploys automatically. Don't edit files here by hand, because the next build overwrites them.
