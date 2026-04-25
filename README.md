# SeedEstate Agent (Hackathon MVP)

Real-estate video generation agent for the Seed Agents Challenge:

- Input: listing URL or address
- Pipeline: scrape listing -> write script -> polish keyframes (Seedream) -> animate clips (Seedance I2V) -> narration (Seed Speech) -> final walkthrough MP4
- Stack: FastAPI backend + Next.js frontend

## 1) Setup

```bash
cp .env.example .env
```

Update `.env` with your keys. Keep `USE_MOCK_MODE=true` for local dry-runs, then switch to `false` to hit real APIs.

### Recommended key placement

Put all Seedance keys in one comma-separated value:

```env
SEEDANCE_API_KEYS=key1,key2,key3,key4
```

The backend rotates through this pool for each I2V request to spread usage.

## 2) Run backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 3) Run frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## API Endpoints

- `POST /api/generate` queue generation
- `GET /api/jobs/{job_id}` poll status
- `GET /generated/...` static output files

## Notes for Seed Hackathon

- The BytePlus/ModelArk API surface can differ by region/account; base URLs and payload keys are configurable in code under `backend/app/seed_clients.py`.
- If a listing blocks scraping, submit an address instead to generate a fallback demo.
- With limited credits, validate flow with `USE_MOCK_MODE=true` first, then switch to real mode only for final renders.

## Event & submission

- Challenge page: [AI Lab: Seed Agents Challenge with Beta Fund: $70K Cash Prizes](https://luma.com/Seedance-Beta-hackathon?tk=p9kHaA)
- Submission portal: [Betahacks.org](https://betahacks.org)
