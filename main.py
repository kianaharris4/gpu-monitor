from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
import asyncio
from collectors.factory import get_collector

app = FastAPI()
collector = get_collector()
dashboard_path = Path(__file__).with_name("gpu_monitor_dashboard.html")


@app.get("/")
async def dashboard():
    return FileResponse(dashboard_path)


@app.get("/api/snapshot")
async def snapshot():
    snapshots = collector.collect()
    if not isinstance(snapshots, list):
        snapshots = [snapshots]
    return {"gpus": [s.to_dict() for s in snapshots]}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    while True:
        try:
            snapshots = collector.collect()
            if not isinstance(snapshots, list):
                snapshots = [snapshots]
            await ws.send_json({"gpus": [s.to_dict() for s in snapshots]})
        except Exception as e:
            await ws.send_json({"error": str(e), "gpus": []})
        await asyncio.sleep(1)
