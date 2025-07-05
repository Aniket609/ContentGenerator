"""
utils.py

This module provides utility functions and constants for the Automated Video Generator project.
It includes helpers for audio synthesis, video resolution management, random request path generation,
font and stroke size calculation, and section extraction from generated scripts.

Key Features:
    - Video and audio generation step definitions
    - Resolution and frame rate management
    - Azure Cognitive Services integration for text-to-speech
    - Utility functions for font/stroke scaling and section parsing

These utilities are used throughout the backend to support video and audio content generation workflows.
"""

import ast
import json
import os
import random
import re
import string

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

resolution_dimensions = {
    "144p": (256, 144),
    "240p": (426, 240),
    "360p": (640, 360),
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
    "4320p": (7680, 4320),
}

frame_rates = [12, 15, 24, 30, 48, 60, 120]

video_generation_steps = [
    {"id": "initialize", "substep_count": 3},
    {"id": "script", "substep_count": 3},
    {"id": "audio", "substep_count": 1},
    {"id": "visuals", "substep_count": 3},
]

audio_generation_steps = [
    {"id": "initialize", "substep_count": 3},
    {"id": "script", "substep_count": 3},
    {"id": "audio", "substep_count": 1},
    {"id": "visuals", "substep_count": 3},
]

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite-preview-06-17",
    temperature=0.1,
)


async def get_font_size(resolution: str, base_size=12):
    """
    Calculates the font size for text overlays based on the video resolution.

    Args:
        resolution (str): The resolution key (e.g., '720p').
        base_size (int, optional): The base font size for 720p. Defaults to 24.

    Returns:
        int: The calculated font size for the given resolution.
    """
    _, height = resolution_dimensions.get(resolution, (1280, 720))  # default to 720p
    return round(int(base_size * (height / 720)), 0)


async def get_stroke_width(resolution: str, base_stroke=2):
    """
    Calculates the stroke width for text overlays based on the video resolution.

    Args:
        resolution (str): The resolution key (e.g., '720p').
        base_stroke (int, optional): The base stroke width for 720p. Defaults to 2.

    Returns:
        int: The calculated stroke width for the given resolution (minimum 1).
    """
    _, h = resolution_dimensions.get(resolution, (1280, 720))
    return max(1, int(base_stroke * (h / 720)))  # never thinner than 1


def get_audio_clip(
    input_phrase: str, filename: str, voice_name: str = "en-US-BrianMultilingualNeural"
) -> str:
    """
    Generates an audio file from the given input phrase using Azure Cognitive Services.

    Args:
        input_phrase (str): The text or SSML to synthesize into speech.
        filename (str): The path where the audio file will be saved.
        voice_name (str, optional): The name of the voice to use for synthesis. Defaults to 'en-US-BrianMultilingualNeural'.

    Returns:
        str: The path to the generated audio file if successful, otherwise None.
    """
    speech_config = speechsdk.SpeechConfig(
        subscription=os.getenv("AZURE_SPEECH_KEY"),
        region=os.getenv("AZURE_SPEECH_REGION"),
    )
    # Note: the voice setting will not overwrite the voice element in input SSML.
    speech_config.speech_synthesis_voice_name = voice_name
    # use the default speaker as audio output.
    filename = re.sub(r'[*?:"<>|]', "_", filename)
    audio_config = speechsdk.audio.AudioOutputConfig(filename=filename)
    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=audio_config
    )
    result = speech_synthesizer.speak_text_async(input_phrase).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"Audio synthesized successfully, clip saved on the path {filename}")
        return filename
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))
        return None


async def generate_unique_request_id(content_type: str):
    """
    Generates a unique request ID and creates a corresponding directory under the given base path.

    Returns:
        str: The unique request ID (folder name).
    """
    base_path_map = {
        "audio": ("./generated_audios", "./temp_audios"),
        "video": ("./generated_videos", "./temp_videos"),
    }

    assert content_type in base_path_map, f"Unsupported content_type: {content_type}"

    output_dir, temp_dir = base_path_map[content_type]

    while True:
        request_id = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        audio_output_path = os.path.join("./generated_audios", f"{request_id}.mp3")
        video_output_path = os.path.join("./generated_videos", f"{request_id}.mp4")
        audio_temp_path = os.path.join("./temp_audios", request_id)
        video_temp_path = os.path.join("./temp_videos", request_id)

        if (
            not os.path.exists(audio_output_path)
            and not os.path.exists(video_output_path)
            and not os.path.exists(audio_temp_path)
            and not os.path.exists(video_temp_path)
        ):

            os.makedirs(audio_temp_path, exist_ok=True)

            if content_type == "video":
                os.makedirs(video_temp_path, exist_ok=True)

            return request_id


async def section_finder(content: str):
    """
    Finds and parses the largest dictionary-like section from the given content string.

    Args:
        content (str): The string content containing one or more dictionary representations.

    Returns:
        dict: The largest dictionary found in the content.
    """
    cleaned = (
        content.replace("```json", "").replace("```", "").replace("\n", "").strip()
    )
    print(cleaned)
    sections = json.loads(cleaned)
    return sections
