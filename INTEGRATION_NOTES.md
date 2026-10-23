# TripWise Copilot Integration

## What changed

- Added `POST /copilot/chat`, which loads the selected saved trip and routes copilot requests through budget/activity tools.
- Added an optional OpenAI-compatible tool-calling agent (`backend/copilot.py`). Configure `OPENAI_API_KEY` and optionally `OPENAI_MODEL` / `OPENAI_BASE_URL` to enable model-powered conversation.
- Added a no-key fallback for budget questions, cheaper/free activity suggestions, and explicit activity replacement prices. It labels catalogue costs as estimates.
- The copilot only previews an itinerary change. The existing **Approve and update itinerary** button performs the actual save.
- Updated the frontend to call the copilot endpoint and preserve the activity index selected for replacement.
- Added `backend/.env.example`. Secrets and the original `.env` are intentionally not included in this archive.

## Run on Windows PowerShell

From the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Optional: edit .env and set OPENAI_API_KEY to enable model-powered copilot
cd ..
python -m uvicorn main:app --app-dir backend --reload
```

In a second PowerShell window:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed in the terminal (usually `http://localhost:5173`). API docs are at `http://127.0.0.1:8000/docs`.

## Configuration

- `OPENAI_API_KEY`: optional. Without it, the deterministic fallback remains usable.
- `OPENAI_MODEL`: optional, defaults to `gpt-4o-mini`.
- `OPENAI_BASE_URL`: optional OpenAI-compatible endpoint override.
- Existing Google Places keys can be configured separately for activity discovery.

The existing transport and hotel scrapers use Selenium/Chrome. Install a compatible Chrome browser and ensure Selenium can launch it in your environment. Scraped prices can change and must be verified with the booking provider; the app does not make bookings.

## Integration boundary

The web copilot invokes the same underlying database and planner functions used by the MCP tools, so budget calculations and saved-trip data stay consistent. The MCP server remains a separate Streamable HTTP service for MCP-capable clients; this change does not claim to be a direct Alexa+ integration.
