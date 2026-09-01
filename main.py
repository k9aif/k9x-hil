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

_ROOT   = Path(__file__).resolve().parent
_WEBUI  = _ROOT / "webui"
_STATIC = _WEBUI / "static"
_INDEX  = _WEBUI / "index.html"

app = FastAPI(title="k9x HIL", version="1.0.0")
app.include_router(router)

if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
async def startup():
    init_schema()
    Base.metadata.create_all(bind=engine, checkfirst=True)
    ensure_columns()
    seed()
    asyncio.create_task(run_consumer())
    asyncio.create_task(run_ttl_sweep())


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
