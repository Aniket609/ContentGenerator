import ast
import os

from PIL import Image
from moviepy import AudioFileClip
from moviepy.video.VideoClip import TextClip, ImageClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips, CompositeVideoClip

BACKGROUND_IMAGE_PATH = r"C:\Users\anike\Downloads\backgrounds\pexels-no-name-14543-66997.jpg"  # Set your background image path
VIDEO_RESOLUTION = (1280, 720)  # Use 1080p resolution
FONT_SIZE = 48  # Increased font size for better readability
FONT_COLOR = "white"
TEXT_POSITION = ("center", "center")
bg_image = Image.open(BACKGROUND_IMAGE_PATH)
bg_image = bg_image.resize(VIDEO_RESOLUTION)  # Resize to match video resolution
bg_image.save("temp_bg.jpg")

with open('subsections.txt', 'r') as subsections_file:
    subsections = ast.literal_eval(subsections_file.read())
    print(subsections)

with open('output_audio_path.txt', 'r') as audio_path_file:
    audio_paths = ast.literal_eval(audio_path_file.read())
    print(audio_paths)

video_clips = []
for section_title, section_contents in subsections.items():
    section_video_paths = []
    folder_name = rf'generated_videos/{section_title}'
    os.makedirs(folder_name, exist_ok=True)
    section_video_clips = []

    for index in range(len(section_contents)):
        audio_clip = AudioFileClip(audio_paths[section_title][index])

        # Create text clip
        text_content = section_contents[index]
        text_clip = TextClip(
            text=text_content,
            font='comic',
            font_size=FONT_SIZE,
            color=FONT_COLOR,
            method="caption",
            size=VIDEO_RESOLUTION,  # Match video resolution
            text_align="center"
        ).with_duration(audio_clip.duration)

        # Create background image clip
        bg_clip = ImageClip("temp_bg.jpg").with_duration(audio_clip.duration)
        composite_clip = CompositeVideoClip([
            bg_clip,
            text_clip.with_position(TEXT_POSITION)
        ]).with_audio(audio_clip)

        section_video_clips.append(composite_clip)
        file_name = f'{folder_name}/{section_title}_{index}.mp4'
        #composite_clip.write_videofile(file_name, fps=24, codec="libx264")

        # Concatenate section clips
    section_video = concatenate_videoclips(section_video_clips, method="compose")
    video_clips.append(section_video)
    section_video.write_videofile(f'{folder_name}/{section_title}.mp4', fps=24, codec="libx264", preset="ultrafast")

# Clean up temporary background
os.remove("temp_bg.jpg")

# Final video composition
video_file = concatenate_videoclips(video_clips, method="compose")
video_file.write_videofile('generated_video.mp4', fps=24, codec="libx264",  preset="ultrafast")

