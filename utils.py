import os
import re
import ast
import random
import string
from typing import List
from fastapi import WebSocket
from langchain_google_genai import ChatGoogleGenerativeAI
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()

resolution_dimensions = {
    '144p': (256, 144),
    '240p': (426, 240),
    '360p': (640, 360),
    '480p': (854, 480),
    '720p': (1280, 720),
    '1080p': (1920, 1080),
    '1440p': (2560, 1440),
    '2160p': (3840, 2160),
    '4320p': (7680, 4320),
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
    model="gemini-2.0-flash",
    temperature=0.1,
)


async def get_font_size(resolution: str, base_size=24):
    _, height = resolution_dimensions.get(resolution, (1280, 720))  # default to 720p
    return round(int(base_size * (height / 720)),0)


def get_audio_clip(input_phrase: str,
                   filename: str,
                   voice_name: str = "en-US-BrianMultilingualNeural") -> str :
    speech_config = speechsdk.SpeechConfig(subscription=os.getenv('AZURE_SPEECH_KEY'),
                                           region=os.getenv('AZURE_SPEECH_REGION'))
    # Note: the voice setting will not overwrite the voice element in input SSML.
    speech_config.speech_synthesis_voice_name = voice_name
    # use the default speaker as audio output.
    filename = re.sub(r'[/*?:"<>|]', "_", filename)
    audio_config = speechsdk.audio.AudioOutputConfig(filename=filename)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = speech_synthesizer.speak_text_async(input_phrase).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f'Audio synthesized successfully, clip saved on the path {filename}')
        return filename
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))
        return None


async def generate_unique_request_path(base_path: str):
    while True:
        request_id = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        folder_path = os.path.join(base_path, request_id)

        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            return request_id

async def section_finder(content: str):
    pattern = re.compile(r'\{[^{}]*\}')
    matches = re.findall(pattern, content)
    print('matches', matches)
    longest_match = max(matches, key=lambda s: len(s))
    sections = ast.literal_eval(longest_match)
    return sections

# A simple class to manage active WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepts a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Closes a WebSocket connection."""
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        """Sends a message to all active WebSocket connections."""
        for connection in self.active_connections:
            await connection.send_text(message)
