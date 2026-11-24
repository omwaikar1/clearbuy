# ClearBuy

**A verified spatial commerce compiler.** Upload a photo of your room, and ClearBuy measures it, picks real products that actually fit, renders them into the scene, and hands you a checkout, with every step checked by a deterministic guardrail instead of trusting the model.

**Live demo:** [clearbuy-frontend.onrender.com](https://clearbuy-frontend.onrender.com)

**Stack:** Next.js 15 · FastAPI (SSE) · Google GenAI SDK · Managed Agents (`hooks.json`) · Shopify Shop MCP / UCP

---

## How it works

1. **Measure.** A two-layer scale engine turns a 2D photo into real-world inches.
2. **Plan.** A spec parser extracts `W×D×H` for each candidate product; a guardrail enforces placement rules and the budget.
3. **Shop.** Live Shopify catalog search and variant lookup via Shop MCP.
4. **Render.** Exact-SKU images are composited into the room, then a visual QA pass checks them.
5. **Checkout.** Per-merchant carts with a Shop Pay `continue_url`.

### Scale engine (`backend/scale_engine.py`)

- **Layer 1:** `gemini-4-neon` finds two-tier reference anchors (outlets, doors, etc.), then applies a weighted cross-anchor skew check (flags `>15%` foreshortening) and a 3D depth-ratio plane correction (`Z_zone / Z_anchor`).
- **Layer 2:** `Depth-Anything-V2-Metric-Indoor-Small-hf` with rotation-invariant EXIF pinhole geometry.
- **Measured accuracy:** `5.34"` MAE on unseen NYU Kinect rooms; `0.1"` on clean wall-outlet nooks.

### Spatial guardrail (`.agents/hooks.json`, `.agents/verify_bundle.py`)

Runs inside Google's `antigravity-preview-09-2026` Managed Agents sandbox and in FastAPI.

- Deterministic 2D placement topology: `floor_anchor`, `underlay` (rugs), `paired_tuck` (seating and tables), `surface_top` (lamps, mats), `wall_mount` (art, mirrors).
- `ProtectedAnchor` preservation and SHA-256 constraint tamper protection.
- Strict budget enforcement in integer minor units (cents → USD).

### Spec parsing (`backend/spec_parser.py`)

`gemini-4-hydrogen` batch spec extraction, a `gemini-decision-1` catalog gate, and voice/video helpers.

### Commerce and rendering (`backend/shop_mcp.py`, `adapters.py`, `renderer.py`, `visual_qa.py`)

- Live Shopify **Shop MCP** (`2026-07-28`) and **UCP** (`2026-08-25`): `search_catalog`, `get_product` variants, per-merchant `create_checkout` / `update_checkout`.
- **Exact-SKU render** with `gemini-nano-banana-2.1`, then a 4-rubric visual QA ("pixel lie-detector") by `gemini-decision-1` with one auto-repair attempt.
- **Benchmark:** 14-room NYU Depth V2 Kinect set with a Gemini 4 ablation (`eval/`).

---

## Quickstart

**Prerequisites:** Python 3.12, [`uv`](https://docs.astral.sh/uv/), Node 20+, and a `GEMINI_API_KEY`.

### Backend

```bash
cp .env.example .env.local        # then paste your GEMINI_API_KEY
uv sync --extra dev --extra depth --python 3.12   # drop `--extra depth` to skip the local depth model
uv run pytest tests/ -v
uv run uvicorn backend.main:app --reload --port 8000
```

The API is now at `http://localhost:8000` (health check: `GET /api/health`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to your backend URL, or set `NEXT_PUBLIC_USE_MOCK_SSE=true` to develop the UI against mock data. See `frontend/.env.example`.

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/session/start` | Start a session from a room photo |
| `GET` | `/api/session/{id}/stream` | SSE stream of pipeline progress |
| `GET` | `/api/session/{id}` | Current session state |
| `GET` | `/api/session/{id}/alternatives` | Alternative products for a slot |
| `POST` | `/api/session/{id}/swap` | Swap a product |
| `POST` | `/api/session/{id}/thread` | Natural-language follow-up |
| `PATCH` | `/api/session/{id}/zone` | Override a placement zone |
| `POST` | `/api/session/{id}/checkout/prepare` | Build per-merchant carts |
| `POST` | `/api/session/{id}/checkout/complete` | Finish checkout |
| `GET` | `/api/benchmark` | NYU Depth V2 benchmark results |

---

## Project layout

```
backend/    FastAPI app, scale engine, spec parser, Shop MCP adapters, renderer, visual QA
.agents/    Spatial guardrail: hooks.json, verify_bundle.py, agent skill docs
agents/     Python-importable shim for the guardrail
frontend/   Next.js 15 app (App Router)
eval/       NYU Depth V2 benchmark and stress-test scripts
tests/      pytest suites for the scale engine/guardrail and the orchestrator
scripts/    Smoke tests
```

## Configuration

Copy `.env.example` to `.env.local`. Key variables: `GEMINI_API_KEY`, the four `GEMINI_MODEL_*` names, `SHOP_MCP_URL`, `BACKEND_PORT`, and `FRONTEND_ORIGIN`. Set `GOOGLE_GENAI_USE_VERTEXAI` plus `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` to use Vertex AI instead of an API key. Never commit `.env.local`.

## Deployment

`render.yaml` is a Render Blueprint defining two services: `clearbuy-backend` (Python/FastAPI) and `clearbuy-frontend` (Next.js). A `Dockerfile` for the backend is also included.
