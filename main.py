import asyncio
import argparse
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse

from collectors.factory import get_collector
from importlib.resources import as_file, files

app = FastAPI()
collector = None


def _resolve_dashboard_ref():
    local_dashboard = Path(__file__).with_name("gpu_monitor_dashboard.html")
    if local_dashboard.is_file():
        return local_dashboard

    packaged_dashboard = files("collectors").joinpath("gpu_monitor_dashboard.html")
    if packaged_dashboard.is_file():
        return packaged_dashboard

    raise FileNotFoundError("gpu_monitor_dashboard.html could not be located")


dashboard_ref = _resolve_dashboard_ref()


def get_cached_collector():
    global collector
    if collector is None:
        collector = get_collector()
    return collector


@app.get("/")
async def dashboard():
    if isinstance(dashboard_ref, Path):
        return FileResponse(dashboard_ref)

    with as_file(dashboard_ref) as dashboard_path:
        return FileResponse(dashboard_path)


@app.get("/api/snapshot")
async def snapshot():
    snapshots = get_cached_collector().collect()
    if not isinstance(snapshots, list):
        snapshots = [snapshots]
    return {"gpus": [s.to_dict() for s in snapshots]}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    while True:
        try:
            snapshots = get_cached_collector().collect()
            if not isinstance(snapshots, list):
                snapshots = [snapshots]
            await ws.send_json({"gpus": [s.to_dict() for s in snapshots]})
        except Exception as e:
            await ws.send_json({"error": str(e), "gpus": []})
        await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Run the GPU Monitor dashboard server.")
    parser.add_argument(
        "--host",
        default=os.getenv("GPU_MONITOR_HOST", "0.0.0.0"),
        help="Host interface to bind.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GPU_MONITOR_PORT", "8000")),
        help="Port to listen on.",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development.")
    parser.add_argument(
        "--log-level",
        default=os.getenv("GPU_MONITOR_LOG_LEVEL", "info"),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level.",
    )
    args = parser.parse_args()

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload, log_level=args.log_level)


if __name__ == "__main__":
    main()
