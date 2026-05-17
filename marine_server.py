import os
import datetime
import math
import requests
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
import uvicorn

print("[STARTUP] marine_server.py loading...")

OPENUV_KEY = os.environ.get("OPENUV_KEY", "")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "marine-secret-123")

GLOBAL_DATA_STORE = {}

mcp = FastMCP("MarineAgent", debug=True, auth=None)
sse_app = mcp.sse_app()
print("[STARTUP] sse_app created successfully")

# ... (all your BEACH_CONFIG, helpers, fetchers, refresh_one_beach, etc. stay exactly the same)

async def data_refresher_loop():
    print("[STARTUP] Background refresher loop started (defensive mode)")
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Starting full beach sync...")
            for beach_id in BEACH_CONFIG:
                try:
                    refresh_one_beach(beach_id)
                except Exception as e:
                    print(f"[WARN] refresh {beach_id} failed (non-fatal): {str(e)[:80]}")
            await asyncio.sleep(300)
        except Exception as e:
            print(f"[ERROR] refresher loop error (continuing): {e}")
            await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] lifespan starting - launching background task defensively")
    try:
        asyncio.create_task(data_refresher_loop())
    except Exception as e:
        print(f"[WARN] background task creation failed (non-fatal): {e}")
    yield

app = FastAPI(title="MarineAgent API", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(ProxyHeadersMiddleware)   # ← This is the new important line

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "MarineAgent Live", "mcp_endpoint": "/mcp"}

app.mount("/mcp", sse_app)

@mcp.tool()
def get_beach_conditions(beach: str = "venice") -> dict:
    """Return real-time coastal conditions for any SWFL beach."""
    beach_id = get_beach_key(beach)
    if not beach_id or beach_id not in BEACH_CONFIG:
        beach_id = "venice"
    return refresh_one_beach(beach_id)

print("[STARTUP] FastAPI app created and ready")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
