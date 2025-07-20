"""
content_generator_frontend.py

This module defines the FastAPI web application for the Automated Video Generator project.

Features:
    - Serves HTML pages for video and audio generation
    - Handles video and audio generation requests via POST endpoints
    - Manages real-time progress updates to clients via WebSockets
    - Manages temporary and output directories for generated media
    - Tracks active WebSocket connections for each client

Endpoints:
    - GET /: Serves the home page for the video generator.
    - GET /generate_video: Serves the video generator HTML page.
    - GET /generate_audio: Serves the audio generator HTML page.
    - POST /generate_video: Accepts form submissions to start video generation in the background.
    - POST /generate_audio: Accepts form submissions to start audio generation in the background.
    - WS /ws/progress/{client_id}: WebSocket endpoint for sending real-time progress updates to clients.

The app uses a dictionary (active_client_managers) to track WebSocket connections for each client.
"""

import json
from pathlib import Path
import shutil
from typing import Dict
import asyncio

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from utils import (
    video_generation_steps,
    resolution_dimensions,
    frame_rates,
    audio_generation_steps,
    generate_unique_request_id,
)
from content_generator import generate_video, generate_audio
from telemetry_utils import sql_keep_alive_task


app = FastAPI()

@app.on_event("startup")
async def start_background_tasks():
    """
    Start background tasks required for the application, such as SQL keep-alive.
    """
    asyncio.create_task(sql_keep_alive_task())


origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=[
        "*"
    ],  # Allows all HTTP methods (GET, POST, etc.) and WebSocket methods
    allow_headers=["*"],  # Allows all headers
)

audio_output_dir = Path("generated_audios")
video_output_dir = Path("generated_videos")
background_image_dir = Path("background_images")
temp_audio_dir = Path("temp_audios")
temp_video_dir = Path("temp_videos")
audio_output_dir.mkdir(parents=True, exist_ok=True)
video_output_dir.mkdir(parents=True, exist_ok=True)
background_image_dir.mkdir(parents=True, exist_ok=True)
temp_audio_dir.mkdir(parents=True, exist_ok=True)
temp_video_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audios", StaticFiles(directory=audio_output_dir), name="audios")
app.mount("/videos", StaticFiles(directory=video_output_dir), name="videos")
active_client_managers: Dict[str, WebSocket] = {}


@app.get("/", response_class=HTMLResponse)
async def read_video_root():
    """
    Serve the home page for the video generator.

    Returns:
        HTMLResponse: The HTML content of the home page.
    """
    with open("templates/home_page.html") as home_page_html:
        return HTMLResponse(content=home_page_html.read(), status_code=200)


@app.get("/generate_video", response_class=HTMLResponse)
async def read_video_root():
    """
    Serve the video generator HTML page.

    Returns:
        HTMLResponse: The HTML content of the video generator page.
    """
    with open("templates/video_generator.html") as video_generator_html:
        return HTMLResponse(content=video_generator_html.read(), status_code=200)


@app.get("/generate_audio", response_class=HTMLResponse)
async def read_audio_root():
    """
    Serve the audio generator HTML page.

    Returns:
        HTMLResponse: The HTML content of the audio generator page.
    """
    with open("templates/audio_generator.html") as audio_generator_html:
        return HTMLResponse(content=audio_generator_html.read(), status_code=200)


@app.post("/generate_video")
async def create_video(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    resolution: str = Form(...),
    frame_rate: int = Form(...),
    background_image: UploadFile = File(None),
    client_id: str = Form(...),
):
    """
    Receive the form submission for video generation, start the video generation in the background,
    and return an immediate success or failure response. Sends progress updates to the client via WebSocket.

    Args:
        background_tasks (BackgroundTasks): FastAPI background task manager for running video generation asynchronously.
        prompt (str): The prompt for the video topic.
        resolution (str): The selected video resolution (e.g., '720p').
        frame_rate (int): The selected frame rate for the video.
        background_image (UploadFile, optional): The uploaded background image file.
        client_id (str): The client identifier for WebSocket communication.

    Returns:
        dict: A dictionary indicating success or failure and a message.
    """
    websocket = active_client_managers.get(client_id)
    if not websocket:
        print(
            f"Error: No active WebSocket connection found for client_id: {client_id}. Cannot send progress updates."
        )
        return {
            "failure": True,
            "message": "No active connection for progress updates. Please ensure your browser supports WebSockets and you're connected.",
        }
    await websocket.send_text(
        json.dumps(
            {
                "step": video_generation_steps[0]["id"],
                "substep_index": 0,
                "substep_status": "in-progress",
            }
        )
    )
    print(f"Prompt: {prompt}" f" Resolution: {resolution}" f" Frame Rate: {frame_rate}")
    await websocket.send_text(
        json.dumps(
            {
                "step": video_generation_steps[0]["id"],
                "substep_index": 0,
                "substep_status": "completed",
            }
        )
    )
    await websocket.send_text(
        json.dumps(
            {
                "step": video_generation_steps[0]["id"],
                "substep_index": 1,
                "substep_status": "in-progress",
            }
        )
    )
    if (
        resolution not in resolution_dimensions.keys()
        or frame_rate not in frame_rates
        or len(prompt) < 5
    ):
        await websocket.send_text(
            json.dumps(
                {
                    "step": video_generation_steps[0]["id"],
                    "substep_index": 1,
                    "substep_status": "completed",
                }
            )
        )
        return {
            "failure": True,
            "message": "Please submit a valid prompt and select resolution and frame rate from the given options.",
        }
    await websocket.send_text(
        json.dumps(
            {
                "step": video_generation_steps[0]["id"],
                "substep_index": 1,
                "substep_status": "completed",
            }
        )
    )
    request_id = await generate_unique_request_id(content_type="video")
    if background_image and background_image.filename:
        suffix = Path(background_image.filename).suffix
        destination_path = Path("background_images") / f"{request_id}{suffix}"
        with open(destination_path, "wb") as buffer:
            shutil.copyfileobj(background_image.file, buffer)
        background_image_path = str(destination_path)
    else:
        background_image_path = (
            r"background_images/default/pexels-no-name-14543-66997.jpg"
        )

    background_tasks.add_task(
        generate_video,
        request_id,
        prompt,
        frame_rate,
        resolution,
        websocket,
        background_image_path,
    )
    return {"success": True, "message": "Video generation has started."}


@app.post("/generate_audio")
async def create_audio(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    client_id: str = Form(...),
):
    """
    Receive the form submission for audio generation, start the audio generation in the background,
    and return an immediate success or failure response. Sends progress updates to the client via WebSocket.

    Args:
        background_tasks (BackgroundTasks): FastAPI background task manager for running audio generation asynchronously.
        prompt (str): The prompt for the audio topic.
        client_id (str): The client identifier for WebSocket communication.

    Returns:
        dict: A dictionary indicating success or failure and a message.
    """
    websocket = active_client_managers.get(client_id)
    if not websocket:
        print(
            f"Error: No active WebSocket connection found for client_id: {client_id}. Cannot send progress updates."
        )
        return {
            "failure": True,
            "message": "No active connection for progress updates. Please ensure your browser supports WebSockets and you're connected.",
        }
    await websocket.send_text(
        json.dumps({"step": audio_generation_steps[0]["id"], "status": "in-progress"})
    )
    await websocket.send_text(
        json.dumps(
            {
                "step": audio_generation_steps[0]["id"],
                "substep_index": 0,
                "substep_status": "in-progress",
            }
        )
    )
    await websocket.send_text(
        json.dumps(
            {
                "step": audio_generation_steps[0]["id"],
                "substep_index": 0,
                "substep_status": "completed",
            }
        )
    )
    print(f"Prompt for audio generation: {prompt}")
    await websocket.send_text(
        json.dumps(
            {
                "step": audio_generation_steps[0]["id"],
                "substep_index": 1,
                "substep_status": "in-progress",
            }
        )
    )
    if len(prompt) < 5:
        return {
            "failure": True,
            "message": "Please submit a valid prompt (at least 5 characters).",
        }
    await websocket.send_text(
        json.dumps(
            {
                "step": "audio-generation-start",
                "substep_index": 1,
                "substep_status": "completed",
            }
        )
    )
    request_id = await generate_unique_request_id(content_type="audio")
    background_tasks.add_task(generate_audio, request_id, prompt, websocket)
    print("Audio generation has started.")
    return {"success": True, "message": "Audio generation has started."}


@app.websocket("/ws/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Handle the WebSocket connection for sending real-time progress updates to the client.
    Stores the WebSocket connection in the active_client_managers dictionary using the client_id.
    Removes the connection on disconnect or error.

    Args:
        websocket (WebSocket): The WebSocket connection instance.
        client_id (str): The client identifier for this WebSocket connection.
    """
    await websocket.accept()
    # Create a new ConnectionManager instance for this specific client's WebSocket
    active_client_managers[client_id] = websocket
    print(f"WebSocket client {client_id} connected and its manager stored.")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if client_id in active_client_managers:
            del active_client_managers[client_id]
            print(f"WebSocket client {client_id} disconnected and its manager removed.")
    except Exception as e:
        print(f"An unexpected error occurred for WebSocket client {client_id}: {e}")
        if client_id in active_client_managers:
            del active_client_managers[client_id]
