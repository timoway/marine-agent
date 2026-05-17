import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from contextlib import asynccontextmanager
import uvicorn

# Config
OPENUV_KEY = os.environ.get("OPENUV_KEY", "")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "marine-secret-123")

# MCP Setup - Root mount for Grok
mcp = FastMCP("MarineAgent", debug=True, auth=None)
sse_app = mcp.sse_app()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="MarineAgent API", lifespan=lifespan)

# Mount MCP at ROOT for Grok compatibility
app.mount("/", sse_app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check (does not override MCP discovery)
@app.get("/health")
async def health():
    return {"status": "MarineAgent Live", "mcp_endpoint": "/", "tools": ["get_beach_conditions"]}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
