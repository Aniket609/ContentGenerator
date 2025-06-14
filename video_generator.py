import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import MessageGraph, END
from video_generator_chains import script_writer_chain, script_critique_chain, section_splitter_chain, \
    script_section_classifier_chain
from typing import List
from utils import get_audio_clip, ConnectionManager, resolution_dimensions, steps
from PIL import Image
from moviepy import AudioFileClip
from moviepy.video.VideoClip import TextClip, ImageClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips, CompositeVideoClip
import time
import ast
import re
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil
import zipfile
from fastapi import FastAPI, UploadFile
import  concurrent.futures as futures

WRITER = 'Writer'
CRITIQUE = 'Critique'
SECTION_SPLITTER = 'Section Splitter'
SUBSECTION_SPLITTER = 'Subsection Splitter'
AUDIO_GENERATOR = 'Audio Generator'
VIDEO_GENERATOR = 'Video Generator'
criticised = 0
subsections = {}
audio_file_names = {}
app = FastAPI()


class VideoMessageGraph(MessageGraph):
    connection_manager : ConnectionManager



async def writer_node(state: List[BaseMessage], config):
    if len(state)==1:
        await config['configurable']['connection_manager'].broadcast(json.dumps({
                        "step": steps[1]['id'],
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    transcript = script_writer_chain.invoke({'messages': state})
    print('In Writer Node', transcript, '/n/n')
    with open('transcript.txt', 'w') as transcript_file:
        transcript_file.write(transcript.content)
    if len(state)==1:
        await config['configurable']['connection_manager'].broadcast(json.dumps({
                            "step": steps[1]['id'],
                            "substep_index": 0,
                            "substep_status": "completed"
                        }))
    return transcript


async def critique_node(state: List[BaseMessage], config):
    criticism = script_critique_chain.invoke({'messages': state, 'script': state[-1].content})
    print('In Critique Node', criticism, '/n/n')
    return [HumanMessage(criticism.content)]


async def section_splitter_node(state: List[BaseMessage], config):
    sections = script_section_classifier_chain.invoke({'messages': state})
    print('In Section splitter Node', sections, '/n/n')
    with open('sections.txt', 'w') as section_file:
        section_file.write(str(sections.content.replace('python', '').replace('`', '').strip()))
    if len(sections.content) == 0:
        return HumanMessage(sections.content)
    return sections


async def subsection_splitter_node(state: List[BaseMessage], config):
    global subsections
    print('In Subsection splitter Node')
    pattern = re.compile(r'\{[^{}]*\}')
    matches = re.findall(pattern, str(state[-1].content))
    print('matches', matches)
    longest_match = max(matches, key=lambda s: len(s))
    sections = ast.literal_eval(longest_match)
    print(f'Number of sections: {len(sections)}')
    with open('subsections.txt', 'w') as subsections_file:
        for section_title, section_content in sections.items():
            subsection = str(
                section_splitter_chain.invoke({'messages': [HumanMessage(section_content)]}).content.replace('python',
                                                                                                             '').replace(
                    '`', '').strip())
            subsection = ast.literal_eval(subsection)
            subsections[section_title] = subsection
            time.sleep(3)
        subsections_file.write(str(subsections))
    await config['configurable']['connection_manager'].broadcast(json.dumps({
        "step": steps[1]['id'],
        "substep_index": 1,
        "substep_status": "completed"
    }))
    return [SystemMessage('Process completed successfully')]


async def should_criticise(state: List[BaseMessage], config):
    global criticised
    if len(state)==2:
        await config['configurable']['connection_manager'].broadcast(json.dumps({
            "step": steps[1]['id'],
            "substep_index": 1,
            "substep_status": "in-progress"
        }))
    if criticised == 2:
        await config['configurable']['connection_manager'].broadcast(json.dumps({
            "step": steps[1]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        await config['configurable']['connection_manager'].broadcast(json.dumps({
            "step": steps[1]['id'],
            "substep_index": 2,
            "substep_status": "in-progress"
        }))
        return SECTION_SPLITTER
    return CRITIQUE


async def should_rewrite(state: List[BaseMessage], config):
    global criticised
    if len(state[-1].content) > 100:
        criticised += 1
        return WRITER
    time.sleep(3)
    return CRITIQUE


async def should_split(state: List[BaseMessage], config):
    if len(state[-1].content) > 200:
        return SUBSECTION_SPLITTER
    time.sleep(3)
    return SECTION_SPLITTER


def audio_generator_node(manager: ConnectionManager):
    try:
        global subsections, audio_file_names
        for section_title, section_contents in subsections.items():
            folder_name = rf'generated_audios/{section_title}'
            os.mkdir(folder_name)
            with futures.ThreadPoolExecutor(max_workers=10) as executor:
                section_audio_paths = list(executor.map(lambda args: process_section(*args),
                                                        [(index, section_contents[index], folder_name, section_title)
                                                         for index in range(len(section_contents))]))
            audio_file_names[section_title] = section_audio_paths

        with open('output_audio_path.txt', 'w') as output_audio_file:
            output_audio_file.write(str(audio_file_names))
        return [SystemMessage('Success! Audio clips generated!')]
    except Exception as e:
        return [SystemMessage(f'Error while generating audio clips: {e}')]

def process_section(index, content, folder_name, section_title):
    file_name = f'{folder_name}/{section_title}_{index}.wav'
    get_audio_clip(input_phrase=content, filename=file_name)
    return file_name

def video_generator_node(frame_rate: int, resolution: str, manager: ConnectionManager, background_image: UploadFile):
    try:
        if background_image:
            suffix = Path(background_image.filename).suffix
            with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                shutil.copyfileobj(background_image.file, tmp_file)
                background_image_path = tmp_file.name
        else:
            background_image_path = r"C:\Users\anike\Downloads\backgrounds\pexels-no-name-14543-66997.jpg"  # Set your background image path
        video_resolution = resolution_dimensions[resolution]  # Use 720p resolution
        font_size = 48  # Increased font size for better readability
        font_color = "white"
        text_position = ("center", "center")
        bg_image = Image.open(background_image_path)
        bg_image = bg_image.resize(video_resolution)  # Resize to match video resolution
        bg_image.save("temp_bg.jpg")
        global subsections, audio_file_names

        video_clips = []
        for section_title, section_contents in subsections.items():
            section_video_paths = []
            folder_name = rf'generated_videos/{section_title}'
            os.makedirs(folder_name, exist_ok=True)
            section_video_clips = []

            # Create text clip for section title unless it's intro or outro
            if section_title.lower() not in ['intro', 'outro']:
                text_clip = TextClip(
                    text=section_title,
                    font='comic',
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,  # Match video resolution
                    text_align="center"
                ).with_duration(3)

                # Create background image clip
                bg_clip = ImageClip("temp_bg.jpg").with_duration(3)
                composite_clip = CompositeVideoClip([
                    bg_clip,
                    text_clip.with_position(text_position)
                ])
                section_video_clips.append(composite_clip)

            for index in range(len(section_contents)):
                audio_clip = AudioFileClip(audio_file_names[section_title][index])

                # Create text clip
                text_content = section_contents[index]
                text_clip = TextClip(
                    text=text_content,
                    font='comic',
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,  # Match video resolution
                    text_align="center"
                ).with_duration(audio_clip.duration)

                # Create background image clip
                bg_clip = ImageClip("temp_bg.jpg").with_duration(audio_clip.duration)
                composite_clip = CompositeVideoClip([
                    bg_clip,
                    text_clip.with_position(text_position)
                ]).with_audio(audio_clip)

                section_video_clips.append(composite_clip)
                #file_name = f'{folder_name}/{section_title}_{index}.mp4'
                # composite_clip.write_videofile(file_name, fps=24, codec="libx264")

                # Concatenate section clips
            section_video = concatenate_videoclips(section_video_clips, method="compose")
            video_clips.append(section_video)
            section_video.write_videofile(f'{folder_name}/{section_title}.mp4', fps=frame_rate, codec="libx264",
                                          preset="ultrafast")

        # Clean up temporary background
        os.remove("temp_bg.jpg")

        # Final video composition
        video_file = concatenate_videoclips(video_clips, method="compose")
        video_file.write_videofile('generated_video.mp4', fps=frame_rate, codec="libx264", preset="ultrafast")
        print(f'Success! Video generated and saved')
    except Exception as e:
        print(f'Error while generating video clips: {e}')




# def should_generate_video(state: List[BaseMessage]):
#     if 'success' in state[-1].content.lower():
#         return VIDEO_GENERATOR
#     print(f'Error in Audio Generation: "{state[-1].content}"')
#     return END


# def should_split(state: List[BaseMessage]):
#     if len(state[-1].content) > 200:
#         return SUBSECTION_SPLITTER
#     time.sleep(3)
#     return SECTION_SPLITTER

def build_graph(connection_manager: ConnectionManager):
    builder = VideoMessageGraph()
    builder.add_node(WRITER, writer_node)
    builder.add_node(CRITIQUE, critique_node)
    builder.add_node(SECTION_SPLITTER, section_splitter_node)
    builder.add_node(SUBSECTION_SPLITTER, subsection_splitter_node)
    # builder.add_node(AUDIO_GENERATOR, audio_generator_node)
    # builder.add_node(VIDEO_GENERATOR, video_generator_node)
    builder.set_entry_point(WRITER)
    builder.add_conditional_edges(CRITIQUE, should_rewrite)
    builder.add_conditional_edges(WRITER, should_criticise)
    builder.add_conditional_edges(SECTION_SPLITTER, should_split)
    builder.add_edge(SUBSECTION_SPLITTER, END)
    # builder.add_edge(AUDIO_GENERATOR, END)
    # builder.add_edge(AUDIO_GENERATOR,VIDEO_GENERATOR)
    # builder.add_edge(VIDEO_GENERATOR,END)
    video_generator_graph = builder.compile()
    # video_generator_graph.get_graph().draw_png('video_generator_graph.png')
    # video_generator_graph.get_graph().draw_mermaid_png(output_file_path='Video Generator Graph.png')
    return video_generator_graph

def zip_folder(folder_path, zip_name):
    # Create a ZipFile object
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Walk through the folder
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                # Create the full file path
                file_path = os.path.join(root, file)
                # Add file to the zip file
                zipf.write(file_path, os.path.relpath(file_path, folder_path))


def clear_folder(folder_path):
    # Walk through the folder
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            # Create the full file path
            file_path = os.path.join(root, file)
            # Remove the file
            os.remove(file_path)
        for dir in dirs:
            # Create the full directory path
            dir_path = os.path.join(root, dir)
            # Remove the directory
            shutil.rmtree(dir_path)


async def generate_video(input_prompt: str, frame_rate: int, resolution: str, manager: ConnectionManager,
                   background_image: UploadFile):
    await manager.broadcast(json.dumps({
                        "step": steps[0]['id'],
                        "substep_index": 2,
                        "substep_status": "in-progress"
                    }))
    video_generator_graph = build_graph(manager)
    await manager.broadcast(json.dumps({
        "step": steps[0]['id'],
        "substep_index": 2,
        "substep_status": "completed"
    }))
    await manager.broadcast(json.dumps({"step": steps[0]['id'], "status": "completed"}))
    await manager.broadcast(json.dumps({"step": steps[1]['id'], "status": "in-progress"}))
    result = await video_generator_graph.ainvoke(f'Write the script for a video titled "{input_prompt}"',{"configurable": {"connection_manager": manager}})
    await manager.broadcast(json.dumps({"step": steps[1]['id'], "status": "completed"}))
    await manager.broadcast(json.dumps({"step": steps[2]['id'], "status": "in-progress"}))
    await manager.broadcast(json.dumps({
                        "step": steps[2]['id'],
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    audio_generator_node(manager=manager)
    await manager.broadcast(json.dumps({
                        "step": steps[2]['id'],
                        "substep_index": 0,
                        "substep_status": "completed"
                    }))
    await manager.broadcast(json.dumps({"step": steps[2]['id'], "status": "completed"}))
    await manager.broadcast(json.dumps({"step": steps[3]['id'], "status": "in-progress"}))
    video_generator_node(frame_rate=frame_rate, resolution=resolution, manager=manager,
                         background_image=background_image)
    zip_folder(folder_path='generated_audios', zip_name='audios.zip')
    clear_folder(folder_path='generated_audios')
    zip_folder(folder_path='generated_videos', zip_name='videos.zip')
    clear_folder(folder_path='generated_videos')
    print('Success')

# generate_video(input_prompt="How to stay motivated in tough times")
