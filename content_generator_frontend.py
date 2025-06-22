import json
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile


from fastapi import (BackgroundTasks, FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from utils import ConnectionManager, video_generation_steps, resolution_dimensions, frame_rates, audio_generation_steps
from content_generator import generate_video, generate_audio

# Create FastAPI app instance
app = FastAPI()
audio_dir = Path("generated_audios")
video_dir = Path("generated_videos")
audio_dir.mkdir(parents=True, exist_ok=True)
video_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audios", StaticFiles(directory=audio_dir), name="audios")
app.mount("/videos", StaticFiles(directory=video_dir), name="videos")


# Instantiate the connection manager
manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def read_video_root():
    """Serves the video generator HTML page."""
    with open("templates/home_page.html") as home_page_html:
        return HTMLResponse(content=home_page_html.read(), status_code=200)


@app.get("/generate_video", response_class=HTMLResponse)
async def read_video_root():
    """Serves the video generator HTML page."""
    with open("templates/video_generator.html") as video_generator_html:
        return HTMLResponse(content=video_generator_html.read(), status_code=200)


@app.get("/generate_audio", response_class=HTMLResponse)
async def read_audio_root():
    """Serves the audio generator HTML page."""
    with open("templates/audio_generator.html") as audio_generator_html:
        return HTMLResponse(content=audio_generator_html.read(), status_code=200)


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
    await manager.broadcast(json.dumps({"step": video_generation_steps[0]['id'], "status": "in-progress"}))
    await manager.broadcast(json.dumps({
                        "step": video_generation_steps[0]['id'],
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    print(f"Prompt: {prompt}"
      f" Resolution: {resolution}"
      f" Frame Rate: {frame_rate}")
    await manager.broadcast(json.dumps({
        "step": video_generation_steps[0]['id'],
        "substep_index": 0,
        "substep_status": "completed"
    }))
    await manager.broadcast(json.dumps({
                        "step": video_generation_steps[0]['id'],
                        "substep_index": 1,
                        "substep_status": "in-progress"
                    }))
    if resolution not in resolution_dimensions.keys() or frame_rate not in frame_rates or len(prompt)<5:
        await manager.broadcast(json.dumps({
            "step": video_generation_steps[0]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        return {"failure": True, "message": "Please submit a valid prompt and select resolution and frame rate from the given options."}
    await manager.broadcast(json.dumps({
        "step": video_generation_steps[0]['id'],
        "substep_index": 1,
        "substep_status": "completed"
    }))
    if background_image:
        suffix = Path(background_image.filename).suffix
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            shutil.copyfileobj(background_image.file, tmp_file)
            background_image_path = tmp_file.name
    else:
        background_image_path = r"C:\Users\anike\Downloads\backgrounds\pexels-no-name-14543-66997.jpg"  # Set your background image path

    background_tasks.add_task(generate_video, prompt, frame_rate, resolution, manager, background_image_path)
    return {"success": True, "message": "Video generation has started."}



@app.post("/generate_audio")
async def create_audio(
        background_tasks: BackgroundTasks,
        prompt: str = Form(...),
):
    """
    Receives the form submission, starts the audio generation in the background,
    and returns an immediate success response.
    """
    await manager.broadcast(json.dumps({"step": audio_generation_steps[0]['id'], "status": "in-progress"}))
    await manager.broadcast(json.dumps({
                        "step": audio_generation_steps[0]['id'],
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    await manager.broadcast(json.dumps({
        "step": audio_generation_steps[0]['id'],
        "substep_index": 0,
        "substep_status": "completed"
    }))
    print(f"Prompt for audio generation: {prompt}")
    await manager.broadcast(json.dumps({
        "step": audio_generation_steps[0]['id'],
        "substep_index": 1,
        "substep_status": "in-progress"
    }))
    if len(prompt) < 5:

        return {"failure": True, "message": "Please submit a valid prompt (at least 5 characters)."}
    await manager.broadcast(json.dumps({
        "step": "audio-generation-start",
        "substep_index": 1,
        "substep_status": "completed"
    }))
    background_tasks.add_task(generate_audio, prompt, manager)
    print("Audio generation has started.")
    return {"success": True, "message": "Audio generation has started."}


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

