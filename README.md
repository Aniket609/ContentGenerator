# Automated Content Generator

An AI-powered web application that automatically generates high-quality video and audio content from text prompts. The system uses advanced language models to create scripts, synthesizes speech with Azure TTS, and generates videos with text overlays on customizable backgrounds.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database Setup](#database-setup)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [WebSocket Communication](#websocket-communication)

## Overview

The Automated Content Generator is a full-stack application built with FastAPI that enables users to:

- **Generate Videos**: Create complete videos with script, narration, and visuals from a simple text prompt
- **Generate Audio**: Produce podcast-style audio content with structured sections and natural speech
- **Real-time Progress Tracking**: Monitor generation progress through WebSocket connections
- **Telemetry**: Comprehensive logging and analytics for requests and generation steps

The system uses LangGraph for orchestrating complex workflows, Google's Gemini models for script generation, and Azure Cognitive Services for text-to-speech synthesis.

## Features

### Video Generation
- ✅ Automatic script writing with AI critique and refinement
- ✅ Script sectioning and subsectioning for structured content
- ✅ Text-to-speech audio generation using Azure TTS
- ✅ Video composition with customizable background images
- ✅ Multiple resolution options (144p to 8K)
- ✅ Adjustable frame rates (12-120 fps)
- ✅ Text overlays with dynamic font sizing based on resolution
- ✅ Real-time progress tracking via WebSocket

### Audio Generation
- ✅ Podcast-style script generation
- ✅ Automatic section identification (intro, main content, outro)
- ✅ High-quality speech synthesis
- ✅ Audio concatenation and encoding
- ✅ Real-time progress updates

### Additional Features
- 🎨 Modern, responsive web UI with Bootstrap
- 📊 Telemetry and logging system with Azure SQL Database
- 🔄 Automatic error handling and retry mechanisms
- 💾 Temporary file management and cleanup
- 🔐 Unique request ID generation
- 📡 WebSocket-based real-time communication

## Architecture

The application follows a modular architecture with clear separation of concerns:

```
┌─────────────────┐
│   Web Browser   │
│  (Frontend UI)  │
└────────┬────────┘
         │ HTTP/WebSocket
         │
┌────────▼──────────────────────────────┐
│        FastAPI Backend                │
│  ┌─────────────────────────────────┐ │
│  │  content_generator_frontend.py  │ │
│  │  (Routes, WebSockets, Static)   │ │
│  └──────────┬──────────────────────┘ │
│             │                          │
│  ┌──────────▼──────────────────────┐ │
│  │  content_generator.py            │ │
│  │  (Orchestration, Video/Audio)    │ │
│  └──────────┬──────────────────────┘ │
│             │                          │
│  ┌──────────▼──────────────────────┐ │
│  │  content_generator_chains.py     │ │
│  │  (LangChain Prompts & Chains)   │ │
│  └──────────┬──────────────────────┘ │
│             │                          │
│  ┌──────────▼──────────────────────┐ │
│  │  utils.py                        │ │
│  │  (Azure TTS, Helpers)            │ │
│  └──────────┬──────────────────────┘ │
│             │                          │
│  ┌──────────▼──────────────────────┐ │
│  │  telemetry_utils.py              │ │
│  │  (Database Logging)              │ │
│  └──────────────────────────────────┘ │
└─────────┬─────────────────────────────┘
          │
    ┌─────┴─────┬──────────┬──────────────┐
    │           │          │               │
┌───▼───┐  ┌───▼───┐  ┌───▼───┐    ┌──────▼──────┐
│Gemini │  │Azure  │  │Azure  │    │  MoviePy    │
│ API   │  │ TTS   │  │ SQL   │    │  (FFmpeg)   │
└───────┘  └───────┘  └───────┘    └─────────────┘
```

### Generation Workflow

**Video**: Script generation → Critique & refinement → Sectioning → Audio synthesis → Video composition with text overlays

**Audio**: Script generation → Sectioning → Audio synthesis

## Technology Stack

**Backend**: FastAPI, LangChain, LangGraph, Google Gemini AI, Azure Cognitive Services (TTS), MoviePy, Azure SQL Database

**Frontend**: HTML5/CSS3, Bootstrap 5, JavaScript

## Prerequisites

- **Python 3.8+**
- **FFmpeg** installed and accessible in your PATH
- **Azure Cognitive Services** (Speech Service)
- **Azure SQL Database** (for telemetry)
- **Google Gemini API** key


## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Aniket609/ContentGenerator
   cd ContentGenerator
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   
   # Activate virtual environment
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r ContentGenerator/requirements.txt
   ```

4. **Verify FFmpeg installation:**
   ```bash
   ffmpeg -version
   ```

## Configuration

Create a `.env` file in the `ContentGenerator` directory:

```env
GOOGLE_API_KEY=your_google_api_key_here
AZURE_SPEECH_KEY=your_azure_speech_key_here
AZURE_SPEECH_REGION=your_azure_region_here
AZURE_SQL_CONNECTION_STRING=your_azure_sql_connection_string_here
LANGSMITH_API_KEY='your_langsmith_api_key_here'
LANGSMITH_TRACING='true'
LANGSMITH_PROJECT='content-generation-project'
```

## Database Setup

Run the DDL script (`Content Generator DDL.sql`) in your Azure SQL Database to create the required tables for telemetry logging.

## Usage

### Starting the Server

```bash
cd ContentGenerator
uvicorn content_generator_frontend:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

### Generating Content

#### Video Generation

1. Click **"Start Generating Video"** on the homepage
2. Enter a video prompt (e.g., "How to save money effectively")
3. Select resolution (default: 720p)
4. Choose frame rate (default: 24 fps)
5. (Optional) Upload a background image
6. Click **"Generate Video"**
7. Monitor progress in the progress tracker
8. Download the generated video when complete

#### Audio Generation

1. Click **"Start Generating Audio"** on the homepage
2. Enter an audio/podcast prompt
3. Click **"Generate Audio"**
4. Track progress in real-time
5. Download the generated audio file

### WebSocket Connection

The application automatically establishes a WebSocket connection when you load the video or audio generation pages. Connection status is displayed in the progress tracker.

## Project Structure

```
ContentGenerator/
│
├── content_generator_frontend.py    # FastAPI app, routes, WebSocket handlers
├── content_generator.py            # Core orchestration, video/audio generation
├── content_generator_chains.py     # LangChain prompts and chains
├── utils.py                        # Utilities, Azure TTS, helpers
├── telemetry_utils.py              # Database logging, telemetry decorators
├── image_converter.py              # Image conversion utility (example)
├── requirements.txt                # Python dependencies
├── Content Generator DDL.sql       # Database schema
│
├── templates/                      # HTML templates
│   ├── home_page.html              # Landing page
│   ├── video_generator.html        # Video generation UI
│   └── audio_generator.html        # Audio generation UI
│
├── generated_videos/               # Output directory for videos
├── generated_audios/               # Output directory for audio
├── background_images/              # User-uploaded background images
│   └── default/                    # Default background images
├── temp_audios/                    # Temporary audio files (per request)
└── temp_videos/                    # Temporary video files (per request)
```

## API Endpoints

### GET Endpoints

| Endpoint | Description | Response |
|----------|-------------|----------|
| `/` | Home page | HTML |
| `/generate_video` | Video generator page | HTML |
| `/generate_audio` | Audio generator page | HTML |
| `/videos/{filename}` | Serve generated video | Video file |
| `/audios/{filename}` | Serve generated audio | Audio file |

### POST Endpoints

| Endpoint | Description | Request Body | Response |
|----------|-------------|--------------|----------|
| `/generate_video` | Start video generation | Form data (prompt, resolution, frame_rate, background_image, client_id) | JSON `{success: bool, message: str}` |
| `/generate_audio` | Start audio generation | Form data (prompt, client_id) | JSON `{success: bool, message: str}` |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws/progress/{client_id}` | Real-time progress updates |

WebSocket messages include step status updates and a final completion message with the output file URL.

## WebSocket Communication

The application uses WebSockets for real-time progress updates. The browser connects to `/ws/progress/{client_id}` when pages load. Progress steps include initialization, script generation, audio synthesis, and video composition.

---

For issues, questions, or contributions, please open an issue on the [GitHub repository](https://github.com/Aniket609/ContentGenerator).
