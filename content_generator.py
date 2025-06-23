"""
content_generator.py

This module implements the core logic for automated video and audio content generation.
It defines asynchronous workflow functions and message graph nodes for scripting, critiquing,
section/subsection splitting, audio synthesis, and video composition.

Key Features:
    - Asynchronous orchestration of video/audio generation steps
    - MessageGraph-based workflow for script writing, critique, and sectioning
    - Audio synthesis and video composition using MoviePy and Azure TTS
    - Utility functions for zipping, cleaning up, and managing temporary files
    - Real-time progress updates via WebSocket

This module is used by the FastAPI backend to process user requests for video and audio content generation.
"""
import ast
import asyncio
import json
import os
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from traceback import print_exc
from typing import List, Literal, Dict

from PIL import Image
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import MessageGraph, END
from moviepy import AudioFileClip, concatenate_audioclips
from moviepy.video.VideoClip import TextClip, ImageClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips, CompositeVideoClip
from fastapi import WebSocket


from utils import get_audio_clip,resolution_dimensions, video_generation_steps, \
    generate_unique_request_path, audio_generation_steps, section_finder, get_font_size, get_stroke_width
from content_generator_chains import script_writer_chain, script_critique_chain, section_splitter_chain, \
    script_section_classifier_chain

WRITER = 'Writer'
CRITIQUE = 'Critique'
SECTION_SPLITTER = 'Section Splitter'
SUBSECTION_SPLITTER = 'Subsection Splitter'
AUDIO_GENERATOR = 'Audio Generator'
VIDEO_GENERATOR = 'Video Generator'
criticised = 0
semaphore = asyncio.Semaphore(10)



class ContentGeneratorMessageGraph(MessageGraph):
    connection_manager : WebSocket
    criticised : int = 0



async def writer_node(state: List[BaseMessage],
                      config):
    """
    Generates a script for a video or audio based on the provided state using the script_writer_chain.
    Sends progress updates to the client via the connection manager.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.
        config (dict): Configuration dictionary containing the connection manager for sending updates.

    Returns:
        BaseMessage: The generated transcript message.
    """
    if len(state)==1:
        await config['configurable']['connection_manager'].send_text(json.dumps({
                        "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
                        "substep_index": 0,
                        "substep_status": "in-progress"
                    }))
    transcript = await script_writer_chain.ainvoke({'messages': state})
    print('In Writer Node', transcript, '/n/n')
    if len(state)==1:
        await config['configurable']['connection_manager'].send_text(json.dumps({
                            "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
                            "substep_index": 0,
                            "substep_status": "completed"
                        }))
    return transcript


async def critique_node(state: List[BaseMessage],
                        config):
    """
    Critiques the last script in the state using the script_critique_chain.
    If the critique is long, returns a HumanMessage and increments the 'criticised' count.
    Otherwise, returns a short HumanMessage.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.
        config (dict): Configuration dictionary containing the 'criticised' count.

    Returns:
        dict or List[HumanMessage]: Critique result and updated 'criticised' count, or just the critique message.
    """
    criticism = await script_critique_chain.ainvoke({'messages': state,
                                              'script': state[-1].content})
    print('In Critique Node', criticism, '/n/n')
    if len(criticism.content)> 100:
        return {"messages" :[HumanMessage(criticism.content)], 'criticised': config['configurable']['criticised']+1}
    else:
        return [HumanMessage(criticism.content)]


async def section_splitter_node(state: List[BaseMessage]):
    """
    Splits the script into sections using the script_section_classifier_chain.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.

    Returns:
        BaseMessage: The sections as a message, or the original message if no sections found.
    """
    sections = await script_section_classifier_chain.ainvoke({'messages': state})
    print('In Section splitter Node', sections, '/n/n')
    if len(sections.content) == 0:
        return HumanMessage(sections.content)
    return sections


async def subsection_splitter_node(state: List[BaseMessage]):
    """
    Splits each section into subsections asynchronously.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.

    Returns:
        List[SystemMessage]: A message containing the processed subsections.
    """
    print('In Subsection splitter Node')
    sections = await section_finder(content=state[-1].content)
    print(f'Number of sections: {len(sections)}')
    tasks = [process_section_to_subsection(title, content) for title, content in sections.items()]
    subsections = await asyncio.gather(*tasks)
    return [SystemMessage(f'Process completed successfully: {dict(subsections)}')]


async def should_criticise(state: List[BaseMessage],
                           config):
    """
    Determines whether to send the script for critique or move to the next step based on the 'criticised' count.
    Sends progress updates to the client.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.
        config (dict): Configuration dictionary containing the 'criticised' count and connection manager.

    Returns:
        str: The next node to transition to ('Critique' or 'Section Splitter').
    """
    if len(state)==2:
        await config['configurable']['connection_manager'].send_text(json.dumps({
            "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
            "substep_index": 1,
            "substep_status": "in-progress"
        }))
    if config['configurable']['criticised'] == 2:
        await config['configurable']['connection_manager'].send_text(json.dumps({
            "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
            "substep_index": 1,
            "substep_status": "completed"
        }))
        await config['configurable']['connection_manager'].send_text(json.dumps({
            "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
            "substep_index": 2,
            "substep_status": "in-progress"
        }))
        return SECTION_SPLITTER
    return CRITIQUE


async def should_rewrite(state: List[BaseMessage]):
    """
    Determines whether the script should be rewritten based on the length of the last message.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.

    Returns:
        str: The next node to transition to ('Writer' or 'Critique').
    """
    if len(state[-1].content) > 100:
        return WRITER
    time.sleep(3)
    return CRITIQUE


async def should_split(state: List[BaseMessage]):
    """
    Determines whether to split a section into subsections based on the length of the last message.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.

    Returns:
        str: The next node to transition to ('Subsection Splitter' or 'Section Splitter').
    """
    if len(state[-1].content) > 200:
        return SUBSECTION_SPLITTER
    time.sleep(3)
    return SECTION_SPLITTER

async def should_end(state: List[BaseMessage]):
    """
    Determines whether to end the process or continue splitting sections based on the length of the last message.

    Args:
        state (List[BaseMessage]): The current list of messages representing the conversation state.

    Returns:
        str: The next node to transition to ('END' or 'Section Splitter').
    """
    if len(state[-1].content) > 200:
        return END
    time.sleep(3)
    return SECTION_SPLITTER


async def audio_generator_node(subsections: Dict):
    """
    Generates audio files for each subsection using a thread pool for concurrency.
    Stores audio files in a temporary directory structure.

    Args:
        subsections (Dict): Dictionary mapping section titles to lists of subsection contents.

    Returns:
        dict or str: Dictionary mapping section titles to lists of audio file paths, or an error message on failure.
    """
    try:
        audio_file_names= {}
        for section_title, section_contents in subsections.items():
            folder_name = rf'temp_audios/{section_title}'
            os.mkdir(folder_name)
            with ThreadPoolExecutor(max_workers=10) as executor:
                section_audio_paths = list(executor.map(lambda args: process_section(*args),
                                                        [(index, section_contents[index], folder_name, section_title)
                                                         for index in range(len(section_contents))]))
            audio_file_names[section_title] = section_audio_paths
        print(f"audio_file_names: {audio_file_names}")
        return audio_file_names
    except Exception as e:
        return 'Failed to generate audio files'

def process_section(index,
                    content,
                    folder_name,
                    section_title):
    """
    Generates an audio file for a given subsection and returns the file path.

    Args:
        index (int): Index of the subsection.
        content (str): Text content of the subsection.
        folder_name (str): Directory to save the audio file.
        section_title (str): Title of the section.

    Returns:
        str: Path to the generated audio file.
    """
    file_name = f'{folder_name}/{section_title}_{index}.wav'
    file_name = get_audio_clip(input_phrase=content, filename=file_name)
    return file_name


async def process_section_to_subsection(title, content):
    """
    Processes a section's content into subsections using the section_splitter_chain.
    Retries on failure with a delay.

    Args:
        title (str): Title of the section.
        content (str): Content of the section.

    Returns:
        tuple: (title, list of subsections)
    """
    async with semaphore:
        while True:
            try:
                raw = await section_splitter_chain.ainvoke({'messages': [HumanMessage(content)]})
                cleaned = raw.content.replace('python', '').replace('`', '').strip()
                break
            except Exception as e:
                print(e)
                time.sleep(5) #waiting five seconds before trying again
        return title, ast.literal_eval(cleaned)





async def video_file_generator_node(frame_rate: int,
                                    resolution: str,
                                    connection_manager: WebSocket,
                                    background_image_path: str,
                                    subsections: Dict,
                                    audio_file_names: Dict):
    """
    Generates a video file by combining video clips for each subsection and synchronizing them with audio.
    Sends progress updates to the client and saves the final video file.

    Args:
        frame_rate (int): Frame rate for the output video.
        resolution (str): Resolution key (e.g., '720p').
        connection_manager (WebSocket): WebSocket for sending progress updates.
        background_image_path (str): Path to the background image.
        subsections (Dict): Dictionary mapping section titles to lists of subsection contents.
        audio_file_names (Dict): Dictionary mapping section titles to lists of audio file paths.

    Returns:
        str or None: Name of the generated video file, or None on failure.
    """
    try:
        video_file_name= f"{await generate_unique_request_path(base_path='generated_videos')}.mp4"
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 0,
            "substep_status": "in-progress"
        }))
        video_resolution = resolution_dimensions[resolution]
        font_size = await get_font_size(resolution=video_resolution)
        stroke_width = await get_stroke_width(resolution=video_resolution)
        font_color = "white"
        stroke_color = "black"
        text_position = ("center", "center")
        bg_image = Image.open(background_image_path)
        bg_image = bg_image.resize(video_resolution)
        bg_image.save("temp_bg.jpg")
        video_clips = []
        for section_title, section_contents in subsections.items():
            folder_name = rf'temp_videos/{section_title}'
            os.makedirs(folder_name, exist_ok=True)
            section_video_clips = []
            if section_title.lower() not in ['intro', 'outro']:
                text_clip = TextClip(
                    text=section_title,
                    font='comic',
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,
                    text_align="center",
                    stroke_color = stroke_color,
                    stroke_width = stroke_width,
                ).with_duration(3)
                bg_clip = ImageClip("temp_bg.jpg").with_duration(3)
                composite_clip = CompositeVideoClip([
                    bg_clip,
                    text_clip.with_position(text_position)
                ])
                section_video_clips.append(composite_clip)
            for index in range(len(section_contents)):
                print(type(audio_file_names))
                print(f"Loading audio: {audio_file_names[section_title][index]}")
                audio_clip = AudioFileClip(audio_file_names[section_title][index])
                text_content = section_contents[index]
                text_clip = TextClip(
                    text=text_content,
                    font='comic',
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,
                    text_align="center",
                    stroke_color = stroke_color,
                    stroke_width = stroke_width,
                ).with_duration(audio_clip.duration)
                bg_clip = ImageClip("temp_bg.jpg").with_duration(audio_clip.duration)
                composite_clip = CompositeVideoClip([
                    bg_clip,
                    text_clip.with_position(text_position)
                ]).with_audio(audio_clip)

                section_video_clips.append(composite_clip)
                #file_name = f'{folder_name}/{section_title}_{index}.mp4'
                # composite_clip.write_videofile(file_name, fps=24, codec="libx264")

            section_video = concatenate_videoclips(section_video_clips, method="compose")
            video_clips.append(section_video)
            # section_video.write_videofile(f'{folder_name}/{section_title}.mp4', fps=frame_rate, codec="libx264",
            #                               preset="ultrafast")
        os.remove("temp_bg.jpg")
        video_file = concatenate_videoclips(video_clips, method="compose")
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 0,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 1,
            "substep_status": "in-progress"
        }))
        video_file.write_videofile(f"./generated_videos/{video_file_name}", fps=frame_rate, codec="libx264", preset="ultrafast")
        print(f'Success! Video generated and saved')
        return video_file_name
    except Exception as e:
        print(f'Error while generating video clips:')
        print_exc()
        return None



async def audio_file_generator_node(connection_manager: WebSocket,
                                    sections: Dict):
    """
    Generates a single audio file by concatenating audio clips for each section.
    Sends progress updates to the client and saves the final audio file.

    Args:
        connection_manager (WebSocket): WebSocket for sending progress updates.
        sections (Dict): Dictionary mapping section titles to section contents.

    Returns:
        str or None: Name of the generated audio file, or None on failure.
    """
    try:
        ssml_prompts = [
            (
                f"<speak><break time='500ms'/> {title} <break time='500ms'/> {content}</speak>",
                f"{title}.mp3"
            )
            for title, content in sections.items()
        ]
        with ThreadPoolExecutor(max_workers=10) as executor:
            audio_file_names = list(executor.map(lambda args: get_audio_clip(*args), ssml_prompts))
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 0,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 1,
            "substep_status": "in-progress"
        }))
        audio_name= f"{await generate_unique_request_path(base_path='generated_audios')}.mp3"
        if None in audio_file_names:
            return None
        clips = [AudioFileClip(path) for path in audio_file_names]
        final_clip = concatenate_audioclips(clips)
        await clear_folder(folder_path='temp_audios')
        final_clip.write_audiofile(f"./generated_audios/{audio_name}")
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        return audio_name
    except Exception as e:
        print(f'Error while generating audio clips:')
        print_exc()
        return None





async def build_content_generator_graph(content_type: Literal["video", "audio"] ):
    """
    Builds and compiles a content generation graph for either video or audio generation.

    Args:
        content_type (Literal["video", "audio"]): Type of content to generate ('video' or 'audio').

    Returns:
        MessageGraph: The compiled message graph for the specified content type.
    """
    builder = ContentGeneratorMessageGraph()
    builder.add_node(WRITER, writer_node)
    builder.add_node(CRITIQUE, critique_node)
    builder.add_node(SECTION_SPLITTER, section_splitter_node)
    if content_type == "video":
        builder.add_node(SUBSECTION_SPLITTER, subsection_splitter_node)
    builder.set_entry_point(WRITER)
    builder.add_conditional_edges(CRITIQUE, should_rewrite)
    builder.add_conditional_edges(WRITER, should_criticise)
    if content_type == "video":
        builder.add_conditional_edges(SECTION_SPLITTER, should_split)
        builder.add_edge(SUBSECTION_SPLITTER, END)
        video_generator_graph = builder.compile()
        return video_generator_graph
    elif content_type == "audio":
        builder.add_conditional_edges(SECTION_SPLITTER, should_end)
        audio_generator_graph = builder.compile()
        return audio_generator_graph
    return None
    # video_generator_graph.get_graph().draw_png('video_generator_graph.png')
    # video_generator_graph.get_graph().draw_mermaid_png(output_file_path='Video Generator Graph.png')


async def zip_folder(folder_path,
               zip_name):
    """
    Zips the contents of a folder into a zip file.

    Args:
        folder_path (str): Path to the folder to zip.
        zip_name (str): Name of the output zip file.
    """
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, folder_path))


async def clear_folder(folder_path):
    """
    Clears all files and subdirectories in the specified folder.

    Args:
        folder_path (str): Path to the folder to clear.
    """
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            os.remove(file_path)
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            shutil.rmtree(dir_path)


async def generate_video(input_prompt: str,
                         frame_rate: int,
                         resolution: str,
                         connection_manager: WebSocket,
                         background_image_path: str,
                         ):
    """
    Orchestrates the entire video generation process, including script writing, audio generation, video creation, and cleanup.
    Sends progress updates to the client at each step.

    Args:
        input_prompt (str): The prompt for the video topic.
        frame_rate (int): Frame rate for the output video.
        resolution (str): Resolution key (e.g., '720p').
        connection_manager (WebSocket): WebSocket for sending progress updates.
        background_image_path (str): Path to the background image.
    """
    await connection_manager.send_text(json.dumps({
                        "step": video_generation_steps[0]['id'],
                        "substep_index": 2,
                        "substep_status": "in-progress"
                    }))
    video_generator_graph = await build_content_generator_graph(content_type='video')
    if video_generator_graph is not None:
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[0]['id'],
            "substep_index": 2,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[0]['id'], "status": "completed"}))
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[1]['id'], "status": "in-progress"}))
        result = await video_generator_graph.ainvoke(f'Write the script for a video titled "{input_prompt}"', {"configurable": {"connection_manager": connection_manager}})
        subsections = ast.literal_eval(result[-1].content.replace('Process completed successfully: ', '').strip())
        print(f"Subsections: {subsections}")
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[1]['id'], "status": "completed"}))
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[2]['id'], "status": "in-progress"}))
        await connection_manager.send_text(json.dumps({
                            "step": video_generation_steps[2]['id'],
                            "substep_index": 0,
                            "substep_status": "in-progress"
                        }))
        audio_file_names = await audio_generator_node(manager=connection_manager, subsections=subsections)
        await connection_manager.send_text(json.dumps({
                            "step": video_generation_steps[2]['id'],
                            "substep_index": 0,
                            "substep_status": "completed"
                        }))
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[2]['id'],
                                            "status": "completed"}))
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[3]['id'],
                                            "status": "in-progress"}))
        video_file_name = await video_file_generator_node(frame_rate=frame_rate,
                                                          resolution=resolution,
                                                          connection_manager=connection_manager,
                                                          background_image_path=background_image_path,
                                                          subsections=subsections,
                                                          audio_file_names=audio_file_names)
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 2,
            "substep_status": "in-progress"
        }))
        await zip_folder(folder_path='temp_audios', zip_name=rf'video_file_logs/{video_file_name.split(".")[0]}_audio_clips.zip')
        await clear_folder(folder_path='temp_audios')
        await zip_folder(folder_path='temp_videos', zip_name=rf'video_file_logs/{video_file_name.split(".")[0]}_video_clips.zip')
        await clear_folder(folder_path='temp_videos')
        print('Success')
        video_url = f"/videos/{video_file_name}"
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[3]['id'],
            "substep_index": 2,
            "substep_status": "completed"
        }))
        final_payload = {
            "status": "complete",
            "video_url": video_url
        }
        await connection_manager.send_text(json.dumps({"step": video_generation_steps[3]['id'], "status": "completed"}))
        await connection_manager.send_text(json.dumps(final_payload))
        print(f"Process complete. Video available at URL: {video_url}")



async def generate_audio(input_prompt: str,
                         connection_manager: WebSocket):
    """
    Orchestrates the entire audio generation process, including script writing, section splitting, audio creation, and cleanup.
    Sends progress updates to the client at each step.

    Args:
        input_prompt (str): The prompt for the audio topic.
        connection_manager (WebSocket): WebSocket for sending progress updates.
    """
    await connection_manager.send_text(json.dumps({
        "step": audio_generation_steps[0]['id'],
        "substep_index": 2,
        "substep_status": "in-progress"
    }))
    audio_generator_graph = await build_content_generator_graph(content_type="audio")
    print('Built audio generator graph')
    if audio_generator_graph is not None:
        print(audio_generator_graph)
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[0]['id'],
            "substep_index": 2,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({"step": audio_generation_steps[0]['id'], "status": "completed"}))
        await connection_manager.send_text(json.dumps({"step": audio_generation_steps[1]['id'], "status": "in-progress"}))
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[1]['id'],
            "substep_index": 0,
            "substep_status": "in-progress"
        }))
        print(audio_generator_graph.get_graph().print_ascii())
        result = await audio_generator_graph.ainvoke(f'Write the script for a video titled "{input_prompt}"',
                                                     {"configurable": {"connection_manager": connection_manager}})
        sections = await section_finder(content=result[-1].content)
        print(f"Sections: {sections}, type: {type(sections)}")
        await connection_manager.send_text(json.dumps({
            "step": video_generation_steps[1]['id'], #scripting steps are the same for both audio and video generation
            "substep_index": 2,
            "substep_status": "completed"
        }))
        await connection_manager.send_text(json.dumps({"step": audio_generation_steps[1]['id'], "status": "completed"}))
        await connection_manager.send_text(json.dumps({"step": audio_generation_steps[2]['id'], "status": "in-progress"}))
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 0,
            "substep_status": "in-progress"
        }))
        audio_file_name = await audio_file_generator_node(connection_manager=connection_manager, sections=sections)
        if audio_file_name is None:
            await connection_manager.send_text(json.dumps({
                "step": audio_generation_steps[2]['id'],
                "substep_index": 1,
                "substep_status": "failed"
            }))
            return None
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 1,
            "substep_status": "completed"
        }))
        print('Audio generation success')
        await zip_folder(folder_path='temp_audios', zip_name=rf'video_file_logs/{audio_file_name.split(".")[0]}_audio_clips.zip')
        await clear_folder(folder_path='temp_audios')
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 2,
            "substep_status": "in-progress"
        }))
        audio_url = f"/audios/{audio_file_name}"
        final_payload = {
            "status": "complete",
            "audio_url": audio_url
        }
        await connection_manager.send_text(json.dumps(final_payload))
        await connection_manager.send_text(json.dumps({
            "step": audio_generation_steps[2]['id'],
            "substep_index": 2,
            "substep_status": "completed"
        }))

        await connection_manager.send_text(json.dumps({"step": audio_generation_steps[2]['id'], "status": "completed"}))
        print(f"Process complete. Audio available at URL: {audio_url}")
