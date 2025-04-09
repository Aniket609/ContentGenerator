import os
from langchain_google_genai import ChatGoogleGenerativeAI
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0.1,
)

# print(llm.invoke('Generate an image of a cowboy riding a horse in a meadow in a peaceful sunrise.'))

def get_audio_clip(input_phrase: str, filename: str, voice_name: str = "en-US-BrianMultilingualNeural"):
    speech_config = speechsdk.SpeechConfig(subscription=os.getenv('AZURE_SPEECH_KEY'), region=os.getenv('AZURE_SPEECH_REGION'))
    # Note: the voice setting will not overwrite the voice element in input SSML.
    speech_config.speech_synthesis_voice_name = voice_name
    # use the default speaker as audio output.
    audio_config = speechsdk.audio.AudioOutputConfig(filename=filename)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = speech_synthesizer.speak_text_async(input_phrase).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
       print('Audio synthesized successfully')
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))

