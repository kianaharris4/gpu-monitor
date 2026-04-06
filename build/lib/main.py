import argparse
import asyncio
import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse

from collectors.factory import get_collector

app = FastAPI()
collector = None


def resolve_dashboard_path() -> Path:
    local_path = Path(__file__).with_name("gpu_monitor_dashboard.html")
    if local_path.exists():
        return local_path

    try:
        dist = distribution("gpu-monitor")
    except PackageNotFoundError as exc:
        raise FileNotFoundError("gpu_monitor_dashboard.html could not be located") from exc

    for dist_file in dist.files or []:
        if Path(dist_file).name != "gpu_monitor_dashboard.html":
            continue
        candidate = Path(dist.locate_file(dist_file))
        if candidate.exists():
            return candidate

    raise FileNotFoundError("gpu_monitor_dashboard.html could not be located")


def get_cached_collector():
    global collector
    if collector is None:
        collector = get_collector()
    return collector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the GPU monitor dashboard")
    parser.add_argument(
        "--host",
        default=os.getenv("GPU_MONITOR_HOST", "0.0.0.0"),
        help="Host interface to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GPU_MONITOR_PORT", "8000")),
        help="TCP port to listen on",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for local development",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("GPU_MONITOR_LOG_LEVEL", "info"),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level",
    )
    return parser


dashboard_path = resolve_dashboard_path()


@app.get("/")
async def dashboard():
    return FileResponse(dashboard_path)


@app.get("/api/snapshot")
async def snapshot():
    active_collector = get_cached_collector()
    snapshots = active_collector.collect()
    if not isinstance(snapshots, list):
        snapshots = [snapshots]
    return {"gpus": [s.to_dict() for s in snapshots]}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    active_collector = get_cached_collector()
    await ws.accept()
    while True:
        try:
            snapshots = active_collector.collect()
            if not isinstance(snapshots, list):
                snapshots = [snapshots]
            await ws.send_json({"gpus": [s.to_dict() for s in snapshots]})
        except Exception as e:
            await ws.send_json({"error": str(e), "gpus": []})
        await asyncio.sleep(1)


def main(argv=None):
    args = build_parser().parse_args(argv)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
