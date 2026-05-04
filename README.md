# Marine Agent: SWFL Coastal Intelligence 🌊
**Phase 1: Stable Prototype Complete**

A high-performance, mobile-responsive coastal intelligence platform and AI agent for SWFL paddlers and beachgoers. Integrates real-time government sensors (NOAA, NWS, FWC) and scientific reports (Mote BCRS) for safety and activity planning.

## Phase 1 Achievements [COMPLETE]
- [x] **Unified Backend:** FastAPI + MCP server with a single source of truth (`GLOBAL_DATA_STORE`).
- [x] **Real-Time Sync:** Map markers and dashboards are 100% synchronized for all SWFL beaches.
- [x] **Dynamic Flag System:** Official Florida Beach Flag logic (Green, Yellow, Red, Purple) integrated into map and UI.
- [x] **Activity Status Bar:** Instant Green/Yellow/Red status for **Paddling**, **Swimming**, and **Beach**.
- [x] **Predictive Timing:** Textual forecast parsing to provide "Best Window" timing tips.
- [x] **Mobile-First UX:** Glassy, high-contrast UI optimized for iPhone Safari.

## Roadmap (Phase 2)
- [ ] **Radar Overlay:** Real-time weather radar integration for the Coast Map.
- [ ] **PWA Support:** "Add to Home Screen" capability with manifest and service worker.
- [ ] **Cloud Deployment:** Production build for Vercel/Render.
- [ ] **Advanced AI Agent:** Expanding MCP tools for deeper astronomical and marine analysis.

## Tech Stack
- **Backend:** Python 3.12, FastMCP, FastAPI
- **Frontend:** React, Vite, Mapbox GL, Lucide Icons
- **Data Sources:** NOAA CO-OPS, NWS Weather.gov, FWC-FWRI ArcGIS, Mote Marine Lab.

## Getting Started

### Installation
1. Clone the repository:
   \`\`\`bash
   git clone https://github.com/yourusername/marine-agent.git
   cd marine-agent
   \`\`\`

2. Create and activate a virtual environment:
   \`\`\`bash
   python3 -m venv venv
   source venv/bin/activate
   \`\`\`

3. Install dependencies:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`

### Usage with Gemini CLI
Add the server to your Gemini CLI configuration:
\`\`\`bash
gemini mcp add marine-agent --command "python3" --path "$(pwd)/marine_server.py"
\`\`\`

## License
MIT
