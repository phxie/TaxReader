# TaxReader

A dashboard for uploading tax notice PDFs and extracting structured
fields (tax year, notice type, amount due, issuing agency, summary)
with GPT-4o. Flask backend + React (Vite/TypeScript) frontend.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python package/env manager)
- Node.js (for the frontend)
- An OpenAI API key with GPT-4o access

## Setup

```
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY`.

## Running

Backend (from the repo root):

```
uv run app.py
```

Serves the API on `http://localhost:5000`.

Frontend:

```
cd frontend
npm install
npm run dev
```

Serves the dashboard on `http://localhost:5173`, proxying `/api` requests
to the Flask backend.

## Project layout

- `app.py` — Flask app: upload, list, and file-download routes
- `extract.py` — sends uploaded PDFs to GPT-4o and returns extracted fields
- `db.py` — SQLite storage (`taxreader.db`, path configurable via `DB_PATH`)
- `frontend/` — React + TypeScript dashboard
- `taxdocs/` — uploaded PDFs are stored here (not committed)
