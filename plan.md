# Marine Agent Development Plan

## Current Status
- MCP server: `marine_server.py` with coastal data tools (NOAA, NWS, etc.)
- React + Vite dashboard in `/web/`
- Built with Gemini CLI

## Goal
Add conversational functionality so users can chat with the Marine Agent (e.g., "Is it safe to paddle at Siesta Key tomorrow?")

## Recommended Plan (Phased)

### Phase 1: Immediate Conversational Access (Today - 10 mins)
- Use Cursor or Gemini CLI with MCP connected
- Chat directly with Grok/Gemini using your MCP tools
- No new code needed

### Phase 2: Dedicated Chat Frontend (1-2 hours)
- Use **Streamlit** for a quick Python-based chat UI
- Connects directly to your MCP server
- Can embed or link to existing React dashboard

### Phase 3: Enhanced Options
- Add chat sidebar to React dashboard
- Telegram/SMS bot for texting
- [IN PROGRESS] Grok or Gemini integration via Remote MCP

### Detailed Options
1. **Streamlit Chat** (recommended start)
2. **Extend React Dashboard**
3. **Telegram Bot**
4. **Grok Remote MCP** (Endpoint enabled at `/mcp/sse`)

## AI Collaboration Instructions for Grok (Important)

**Always use the GitHub connector tools** for any repository operations:
- Listing commits, reading file contents, creating/updating/pushing files.
- Verification of deploys and history.
- Force pushes when restoring full code.

**Do NOT** rely on raw.githubusercontent.com URLs for verification or status checks.
- Use `github___list_commits`, `github___get_file_contents`, `github___push_files`, etc. via the connected tool.
- This ensures accurate SHAs, proper history, and reliable updates.

Update this plan as we progress.