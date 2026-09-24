import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from backend.database import engine, init_schema, ensure_columns, SCHEMA
from backend.models import Base
from backend.routes import router
from backend.seed import seed
from backend.kafka_consumer import run_consumer
from backend.ttl_sweep import run_ttl_sweep
from backend.outbox_sweep import run_outbox_sweep

_ROOT   = Path(__file__).resolve().parent
_WEBUI  = _ROOT / "webui"
_STATIC = _WEBUI / "static"
_INDEX  = _WEBUI / "index.html"


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that always sends an explicit Cache-Control header.

    The origin previously sent none for /static/* -- which let Cloudflare's
    own default Browser Cache TTL (commonly 4h for .js/.css) silently take
    over, so a rebuilt app.js could sit invisible in someone's browser for
    hours after a real deploy (confirmed live, 2026-09-19: identical etag/
    last-modified/content-length from both hil.k9x.ai and the origin IP --
    the server was never stale, only browsers were). An explicit origin
    Cache-Control overrides that Cloudflare default. no-cache (not no-store)
    still lets ETag-based conditional GETs return a cheap 304, so this costs
    almost nothing while guaranteeing every load revalidates.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="k9x HIL", version="1.0.0")
app.include_router(router)

if _STATIC.exists():
    app.mount("/static", NoCacheStaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
async def startup():
    init_schema()
    Base.metadata.create_all(bind=engine, checkfirst=True)
    ensure_columns()
    seed()
    asyncio.create_task(run_consumer())
    asyncio.create_task(run_ttl_sweep())
    asyncio.create_task(run_outbox_sweep())


@app.get("/health")
def health():
    return {"status": "ok", "schema": SCHEMA}


@app.get("/{full_path:path}")
def serve_ui(full_path: str):
    if _INDEX.exists():
        return FileResponse(str(_INDEX))
    return {"error": "webui not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8086, reload=True)
