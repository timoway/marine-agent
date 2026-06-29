# Marine Agent: SWFL Coastal Intelligence 🌊

A mobile-first coastal intelligence PWA and AI agent for Gulf coast paddlers and beachgoers. Integrates NOAA, NWS, FWC, Mote BCRS, and radar data for safety and activity planning.

**Production:** [marine-agent.vercel.app](https://marine-agent.vercel.app) (frontend) · [marine-agent.onrender.com](https://marine-agent.onrender.com) (API)

## Features

- **21 Gulf beaches** — SWFL through Panhandle with live map markers (official water-now flag color)
- **Today's verdict** — unified headline with separate *Water now* (official flag) and *Plan today* (forecast + radar)
- **Activity status** — paddling, swimming, beach with per-activity reasons
- **Nearby ranking** — best beaches within 50 mi of selected beach (`/api/rank`)
- **NWS alerts** — ⚡ storm badge on map when warnings active at beach point
- **Radar proximity** — cyan pulse when precipitation detected within 12 mi (same NEXRAD layer as map)
- **Radar overlay** — live NWS mosaic on map; 60s refresh when enabled
- **MCP agent** — `get_beach_conditions`, `rank_beaches` at `/mcp/sse`
- **PWA** — installable on iPhone/Android with offline shell

## Tech Stack

- **Backend:** Python 3.12, FastAPI, FastMCP, Pillow (radar sampling)
- **Frontend:** React, Vite, Mapbox GL, PWA
- **Deploy:** Vercel (frontend + `/api` proxy) · Render (backend)
- **Data:** NOAA CO-OPS, NWS Weather.gov, FWC HAB, Mote VisitBeaches, Open-Meteo, IEM NEXRAD

## Local Development

```bash
git clone https://github.com/timoway/marine-agent.git
cd marine-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python marine_server.py          # API on :8000

cd web && npm install && npm run dev   # PWA on :5173
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Ready status + cache count |
| `GET /api/beaches_with_flags` | Map markers (flag color, storm/radar badges) |
| `GET /api/conditions/{beach_id}` | Full beach dashboard payload |
| `GET /api/rank?activity=paddling&beach_id=venice&radius_miles=50` | Nearby ranked beaches |

## MCP Setup (Gemini CLI)

```bash
gemini mcp add marine-agent --command "python3" --path "$(pwd)/marine_server.py"
```

## Roadmap

See **[plan.md](./plan.md)** for full session handoff and priorities.

- [ ] In-app chat ("best paddle near Venice today?")
- [x] `when=tomorrow` ranking + tomorrow outlook
- [x] Saved home beach
- [ ] Atlantic coast expansion

## License

MIT