import asyncio
import json
import os
from typing import List

from fastapi import (BackgroundTasks, FastAPI, File, Form, Request,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import HTMLResponse
from video_generator import generate_video

from utils import ConnectionManager, steps, resolution_dimensions, frame_rates


# Create FastAPI app instance
app = FastAPI()



# Instantiate the connection manager
manager = ConnectionManager()




@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serves the main HTML page."""
    with open("templates/index.html") as f:
        return HTMLResponse(content=f.read(), status_code=200)


@app.post("/generate_video")
async def create_video(
        background_tasks: BackgroundTasks,
        prompt: str = Form(...),
        resolution: str = Form(...),
        frame_rate: int = Form(...),
        background_image: UploadFile = File(None),
):
    """
    Receives the form submission, starts the video generation in the background,
    and returns an immediate success response.
    """
    # Start the long-running task in the background
    await manager.broadcast(json.dumps({"step": steps[0]['id'], "status": "in-progress"}))
    await manager.broadcast(json.dumps({
                        "step": steps[0]['id'],
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    print(f"Prompt: {prompt}"
      f" Resolution: {resolution}"
      f" Frame Rate: {frame_rate}")
    await manager.broadcast(json.dumps({
        "step": steps[0]['id'],
        "substep_index": 0,
        "substep_status": "completed"
    }))
    await manager.broadcast(json.dumps({
                        "step": steps[0]['id'],
                        "substep_index": 1,
                        "substep_status": "in-progress"
                    }))
    if resolution not in resolution_dimensions.keys() or frame_rate not in frame_rates or len(prompt)<5:
        await manager.broadcast(json.dumps({
            "step": steps[0]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        return {"failure": True, "message": "Please submit a valid prompt and select resolution and frame rate from the given options."}
    await manager.broadcast(json.dumps({
        "step": steps[0]['id'],
        "substep_index": 1,
        "substep_status": "completed"
    }))
    background_tasks.add_task(generate_video, prompt, frame_rate, resolution, manager, background_image)
    return {"success": True, "message": "Video generation has started."}


@app.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handles the WebSocket connection for sending real-time progress updates.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("Client disconnected")

