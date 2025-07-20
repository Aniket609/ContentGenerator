"""
content_generator.py

This module implements the core logic for automated video and audio content generation for the Automated Video Generator project.

Features:
    - Asynchronous orchestration of video/audio generation steps using a message graph workflow
    - Script writing, critique, sectioning, and subsectioning using LLM chains
    - Audio synthesis and video composition using MoviePy and Azure TTS
    - Real-time progress updates via WebSocket for frontend feedback
    - Utility functions for zipping, cleaning up, and managing temporary files
    - Telemetry and request tracking for analytics and debugging

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
import re

from PIL import Image
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import MessageGraph, END
from langgraph.graph.state import CompiledStateGraph
from moviepy import AudioFileClip, concatenate_audioclips
from moviepy.video.VideoClip import TextClip, ImageClip
from moviepy.video.compositing.CompositeVideoClip import (
    concatenate_videoclips,
    CompositeVideoClip,
)
from fastapi import WebSocket
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from typing_extensions import TypedDict, Annotated
from langgraph.graph import StateGraph
from google.api_core.exceptions import InternalServerError, ResourceExhausted

from utils import (
    get_audio_clip,
    resolution_dimensions,
    video_generation_steps,
    generate_unique_request_id,
    audio_generation_steps,
    section_finder,
    get_font_size,
    get_stroke_width,
)
from telemetry_utils import (
    insert_request_stub,
    update_request_final_status,
    telemetry_step,
)
from content_generator_chains import (
    script_writer_chain,
    script_critique_chain,
    section_splitter_chain,
    script_section_classifier_chain,
)

WRITER = "Writer"
CRITIQUE = "Critique"
SECTION_SPLITTER = "Section Splitter"
SUBSECTION_SPLITTER = "Subsection Splitter"
AUDIO_GENERATOR = "Audio Generator"
VIDEO_GENERATOR = "Video Generator"
criticised = 0
semaphore = asyncio.Semaphore(10)


class ContentGeneratorMessageGraph(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    connection_manager: WebSocket
    criticised: int


async def writer_node(state):
    """
    Generate a script for a video or audio based on the provided state using the script_writer_chain.
    Sends progress updates to the client via the connection manager.

    Args:
        state (dict): The current state, including messages and connection manager.

    Returns:
        dict: A dictionary with the generated transcript message.
    """
    if len(state["messages"]) == 1:
        await state["connection_manager"].send_text(
            json.dumps(
                {
                    "step": video_generation_steps[1][
                        "id"
                    ],  # scripting steps are the same for both audio and video generation
                    "substep_index": 0,
                    "substep_status": "in-progress",
                }
            )
        )
    while True:
        try:
            transcript = await script_writer_chain.ainvoke(
                {"messages": state["messages"]}
            )
            break
        except ResourceExhausted as model_err:
            await process_model_error(model_err=model_err)
        except InternalServerError as internal_err:
            await process_internal_error(internal_err=internal_err)
            return {"messages": [HumanMessage(content="")]}

    print("In Writer Node", transcript)
    if len(state["messages"]) == 1:
        await state["connection_manager"].send_text(
            json.dumps(
                {
                    "step": video_generation_steps[1][
                        "id"
                    ],  # scripting steps are the same for both audio and video generation
                    "substep_index": 0,
                    "substep_status": "completed",
                }
            )
        )
    return {"messages": [transcript]}


async def critique_node(state):
    """
    Critique the last script in the state using the script_critique_chain.
    If the critique is long, returns a HumanMessage and increments the 'criticised' count.
    Otherwise, returns a short HumanMessage.

    Args:
        state (dict): The current state, including messages and 'criticised' count.

    Returns:
        dict: Critique result and updated 'criticised' count, or just the critique message.
    """
    while True:
        try:
            criticism = await script_critique_chain.ainvoke(
                {"messages": state["messages"]}
            )
            break
        except ResourceExhausted as model_err:
            await process_model_error(model_err=model_err)
        except InternalServerError as internal_err:
            await process_internal_error(internal_err=internal_err)
            return {"messages": [HumanMessage(content="")]}

    print("In Critique Node", criticism)
    if len(criticism.content) > 100:
        return {
            "messages": [HumanMessage(content=criticism.content)],
            "criticised": state["criticised"] + 1,
        }
    else:
        return {"messages": [HumanMessage(content=criticism.content)]}


async def section_splitter_node(state):
    """
    Split the script into sections using the script_section_classifier_chain.

    Args:
        state (dict): The current state, including messages.

    Returns:
        dict: The sections as a message, or the original message if no sections found.
    """
    while True:
        try:
            sections = await script_section_classifier_chain.ainvoke(
                {"messages": state["messages"]}
            )
            break
        except ResourceExhausted as model_err:
            await process_model_error(model_err=model_err)
        except InternalServerError as internal_err:
            await process_internal_error(internal_err=internal_err)
            return {"messages": [HumanMessage(content="")]}

    print(
        "In Section splitter Node",
        sections,
    )
    if len(sections.content) == 0:
        return {"messages": [HumanMessage(sections.content)]}
    return {"messages": [sections]}


async def subsection_splitter_node(state):
    """
    Split each section into subsections asynchronously using section_finder and process_section_to_subsection.

    Args:
        state (dict): The current state, including messages.

    Returns:
        dict: A message containing the processed subsections.
    """
    print("In Subsection splitter Node", flush=True)
    sections = await section_finder(content=state["messages"][-1].content)
    print(f"Number of sections: {len(sections)}", flush=True)
    tasks = [
        process_section_to_subsection(title, content)
        for title, content in sections.items()
    ]
    subsections = await asyncio.gather(*tasks)
    return {
        "messages": [
            SystemMessage(f"Process completed successfully: {dict(subsections)}")
        ]
    }


async def should_criticise(state):
    """
    Determine whether to send the script for critique or move to the next step based on the 'criticised' count.
    Sends progress updates to the client.

    Args:
        state (dict): The current state, including messages, 'criticised' count, and connection manager.

    Returns:
        str: The next node to transition to ('Critique' or 'Section Splitter').
    """
    if len(state["messages"]) == 2:
        await state["connection_manager"].send_text(
            json.dumps(
                {
                    "step": video_generation_steps[1][
                        "id"
                    ],  # scripting steps are the same for both audio and video generation
                    "substep_index": 1,
                    "substep_status": "in-progress",
                }
            )
        )
    if state["criticised"] == 2:
        await state["connection_manager"].send_text(
            json.dumps(
                {
                    "step": video_generation_steps[1][
                        "id"
                    ],  # scripting steps are the same for both audio and video generation
                    "substep_index": 1,
                    "substep_status": "completed",
                }
            )
        )
        await state["connection_manager"].send_text(
            json.dumps(
                {
                    "step": video_generation_steps[1][
                        "id"
                    ],  # scripting steps are the same for both audio and video generation
                    "substep_index": 2,
                    "substep_status": "in-progress",
                }
            )
        )
        return SECTION_SPLITTER
    return CRITIQUE


async def should_rewrite(state):
    """
    Determine whether the script should be rewritten based on the length of the last message.

    Args:
        state (dict): The current state, including messages.

    Returns:
        str: The next node to transition to ('Writer' or 'Critique').
    """
    if len(state["messages"][-1].content) > 100:
        return WRITER
    await asyncio.sleep(3)
    return CRITIQUE


async def should_split(state):
    """
    Determine whether to split a section into subsections based on the length of the last message.

    Args:
        state (dict): The current state, including messages.

    Returns:
        str: The next node to transition to ('Subsection Splitter' or 'Section Splitter').
    """
    if len(state["messages"][-1].content) > 200:
        return SUBSECTION_SPLITTER
    await asyncio.sleep(3)
    return SECTION_SPLITTER


async def should_end(state):
    """
    Determine whether to end the process or continue splitting sections based on the length of the last message.

    Args:
        state (dict): The current state, including messages.

    Returns:
        str: The next node to transition to ('END' or 'Section Splitter').
    """
    if len(state["messages"][-1].content) > 200:
        return END
    await asyncio.sleep(3)
    return SECTION_SPLITTER


@telemetry_step(step_id=2)
async def audio_generator_node(subsections: Dict, request_id: str):
    """
    Generate audio files for each subsection using a thread pool for concurrency.
    Stores audio files in a temporary directory structure.

    Args:
        subsections (Dict): Dictionary mapping section titles to lists of subsection contents.
        request_id (str): Unique request identifier for file storage.

    Returns:
        dict or str: Dictionary mapping section titles to lists of audio file paths, or an error message on failure.
    """
    try:
        audio_file_names = {}
        for section_title, section_contents in subsections.items():
            folder_name = rf"temp_audios/{request_id}/{re.sub(r'[<>:"/\\|?*]', '', section_title)}"
            os.mkdir(folder_name)
            results = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        process_section,
                        index,
                        section_contents[index],
                        folder_name,
                        section_title,
                    )
                    for index in range(len(section_contents))
                ]
            )
            audio_file_names[section_title] = results
        print(f"audio_file_names: {audio_file_names}", flush=True)
        return audio_file_names
    except Exception as e:
        print_exc()
        return "Failed to generate audio files"


def process_section(index, content, folder_name, section_title):
    """
    Generate an audio file for a given subsection and return the file path.

    Args:
        index (int): Index of the subsection.
        content (str): Text content of the subsection.
        folder_name (str): Directory to save the audio file.
        section_title (str): Title of the section.

    Returns:
        str: Path to the generated audio file.
    """
    file_name = f"{folder_name}/{section_title}_{index}.wav"
    file_name = get_audio_clip(input_phrase=content, filename=file_name)
    return file_name


async def process_section_to_subsection(title, content):
    """
    Process a section's content into subsections using the section_splitter_chain.
    Retries on failure with a delay.

    Args:
        title (str): Title of the section.
        content (str): Content of the section.

    Returns:
        tuple: (title, list of subsections)
    """
    async with semaphore:
        retries = 5
        for attempt in range(retries):
            try:
                print(f"Processing {title} at {time.time()}")
                raw = await section_splitter_chain.ainvoke(
                    {"messages": [HumanMessage(content)]}
                )
                cleaned = raw.content[raw.content.index("["):raw.content.index("]")+1]
                try:
                    parsed = ast.literal_eval(cleaned)
                    print(f"Section {title} successfully converted to subsections", flush=True)
                    return title, parsed
                except Exception as parse_err:
                    print(
                        f"⚠️ Parsing failed on attempt {attempt + 1}: {parse_err}",
                        flush=True,
                    )
                    print(f"🔎 Raw model output: {cleaned}", flush=True)
            except ResourceExhausted as model_err:
                await process_model_error(model_err=model_err)
            except InternalServerError as internal_err:
                await process_internal_error(internal_err=internal_err)
        raise RuntimeError(
            f"Failed to process section '{title}' after {retries} attempts."
        )


@telemetry_step(step_id=3)
async def video_file_generator_node(
    frame_rate: int,
    resolution: str,
    connection_manager: WebSocket,
    background_image_path: str,
    subsections: Dict,
    audio_file_names: Dict,
    request_id: str,
):
    """
    Generate a video file by combining video clips for each subsection and synchronizing them with audio.
    Sends progress updates to the client and saves the final video file.

    Args:
        frame_rate (int): Frame rate for the output video.
        resolution (str): Resolution key (e.g., '720p').
        connection_manager (WebSocket): WebSocket for sending progress updates.
        background_image_path (str): Path to the background image.
        subsections (Dict): Dictionary mapping section titles to lists of subsection contents.
        audio_file_names (Dict): Dictionary mapping section titles to lists of audio file paths.
        request_id (str): Unique request identifier for file storage.

    Returns:
        str or None: Name of the generated video file, or None on failure.
    """
    try:
        video_file_name = f"./generated_videos/{request_id}.mp4"
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": video_generation_steps[3]["id"],
                    "substep_index": 0,
                    "substep_status": "in-progress",
                }
            )
        )
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
            folder_name = rf"temp_videos/{section_title}"
            folder_name = re.sub(r'[*?:"<>|]', "_", folder_name)
            os.makedirs(folder_name, exist_ok=True)
            section_video_clips = []
            if section_title.lower() not in ["intro", "outro"]:
                text_clip = TextClip(
                    text=section_title,
                    font="comic",
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,
                    text_align="center",
                    stroke_color=stroke_color,
                    stroke_width=stroke_width,
                ).with_duration(3)
                bg_clip = ImageClip("temp_bg.jpg").with_duration(3)
                composite_clip = CompositeVideoClip(
                    [bg_clip, text_clip.with_position(text_position)]
                )
                section_video_clips.append(composite_clip)
            for index in range(len(section_contents)):
                print(type(audio_file_names))
                print(f"Loading audio: {audio_file_names[section_title][index]}")
                audio_clip = AudioFileClip(audio_file_names[section_title][index])
                text_content = section_contents[index]
                text_clip = TextClip(
                    text=text_content,
                    font="comic",
                    font_size=font_size,
                    color=font_color,
                    method="caption",
                    size=video_resolution,
                    text_align="center",
                    stroke_color=stroke_color,
                    stroke_width=stroke_width,
                ).with_duration(audio_clip.duration)
                bg_clip = ImageClip("temp_bg.jpg").with_duration(audio_clip.duration)
                composite_clip = CompositeVideoClip(
                    [bg_clip, text_clip.with_position(text_position)]
                ).with_audio(audio_clip)

                section_video_clips.append(composite_clip)
                # file_name = f'{folder_name}/{section_title}_{index}.mp4'
                # composite_clip.write_videofile(file_name, fps=24, codec="libx264")

            section_video = concatenate_videoclips(
                section_video_clips, method="compose"
            )
            video_clips.append(section_video)
            # section_video.write_videofile(f'{folder_name}/{section_title}.mp4', fps=frame_rate, codec="libx264",
            #                               preset="ultrafast")
        os.remove("temp_bg.jpg")
        video_file = concatenate_videoclips(video_clips, method="compose")
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": video_generation_steps[3]["id"],
                    "substep_index": 0,
                    "substep_status": "completed",
                }
            )
        )
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": video_generation_steps[3]["id"],
                    "substep_index": 1,
                    "substep_status": "in-progress",
                }
            )
        )
        video_file.write_videofile(
            video_file_name, fps=frame_rate, codec="libx264", preset="ultrafast"
        )
        print(f"Success! Video generated and saved")
        return video_file_name
    except Exception as e:
        print(f"Error while generating video clips:")
        print_exc()
        return None


@telemetry_step(step_id=2)
async def audio_file_generator_node(
    connection_manager: WebSocket,
    sections: Dict,
    request_id: str,
):
    """
    Generate a single audio file by concatenating audio clips for each section.
    Sends progress updates to the client and saves the final audio file.

    Args:
        connection_manager (WebSocket): WebSocket for sending progress updates.
        sections (Dict): Dictionary mapping section titles to section contents.
        request_id (str): Unique request identifier for file storage.

    Returns:
        str or None: Name of the generated audio file, or None on failure.
    """
    try:
        ssml_prompts = [
            (
                f"<speak><break time='500ms'/> {title} <break time='500ms'/> {content}</speak>",
                f"./temp_audios/{request_id}/{re.sub(r'[<>:"/\\|?*]', '', title).strip()}.mp3",
            )
            for title, content in sections.items()
        ]

        audio_file_names = await asyncio.gather(
            *[
                asyncio.to_thread(get_audio_clip, ssml, file_path)
                for ssml, file_path in ssml_prompts
            ]
        )
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": audio_generation_steps[2]["id"],
                    "substep_index": 0,
                    "substep_status": "completed",
                }
            )
        )
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": audio_generation_steps[2]["id"],
                    "substep_index": 1,
                    "substep_status": "in-progress",
                }
            )
        )
        if None in audio_file_names:
            return None
        audio_file_path = f"./generated_audios/{request_id}.mp3"
        clips = [AudioFileClip(path) for path in audio_file_names]
        final_clip = concatenate_audioclips(clips)
        final_clip.write_audiofile(audio_file_path)
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": audio_generation_steps[2]["id"],
                    "substep_index": 1,
                    "substep_status": "completed",
                }
            )
        )
        return audio_file_path
    except Exception as e:
        print(f"Error while generating audio clips:")
        print_exc()
        return None


async def build_content_generator_graph(content_type: Literal["video", "audio"]):
    """
    Build and compile a content generation graph for either video or audio generation.

    Args:
        content_type (Literal["video", "audio"]): Type of content to generate ('video' or 'audio').

    Returns:
        MessageGraph: The compiled message graph for the specified content type.
    """
    builder = StateGraph(state_schema=ContentGeneratorMessageGraph)
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


async def zip_folder(folder_path, zip_name):
    """
    Zip the contents of a folder into a zip file.

    Args:
        folder_path (str): Path to the folder to zip.
        zip_name (str): Name of the output zip file.
    """
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, folder_path))


async def clear_folder(folder_path):
    """
    Clear all files and subdirectories in the specified folder.

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


async def process_model_error(model_err):
    """
    Handle model errors (e.g., rate limits) by waiting and retrying.

    Args:
        model_err (Exception): The model error exception.
    """
    error_str = str(model_err)
    match = re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", error_str)
    if match:
        delay = int(match.group(1))
    else:
        delay = 5  # fallback delay
    print(f"⏱️ Rate limit reached. Waiting {delay} seconds...", flush=True)
    await asyncio.sleep(delay)
    print(f"Wait of {delay} seconds is over, trying again", flush=True)


async def process_internal_error(internal_err):
    """
    Handle internal server errors by waiting and retrying.

    Args:
        internal_err (Exception): The internal server error exception.
    """
    print("Internal Server error on Gemini, waiting 5 seconds...", flush=True)
    await asyncio.sleep(2)


@telemetry_step(step_id=1)
async def get_video_script(
    request_id: str,
    graph: CompiledStateGraph,
    input_prompt: str,
    connection_manager: WebSocket,
):
    """
    Run the video script generation graph and return the result.

    Args:
        request_id (str): Unique request identifier for file storage.
        graph (CompiledStateGraph): The compiled message graph for video generation.
        input_prompt (str): The prompt for the video topic.
        connection_manager (WebSocket): WebSocket for sending progress updates.

    Returns:
        dict: The result of the graph execution.
    """
    try:
        result = await graph.with_config({"run_name": request_id}).ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=f'Write the script for a video titled "{input_prompt}"'
                    )
                ],
                "criticised": 0,
                "connection_manager": connection_manager,
            }
        )
        print("Script written successfully", flush=True)
        return result
    except asyncio.CancelledError as cancel_err:
        print(f"[CANCELLED] LangGraph execution was interrupted: {cancel_err}", flush=True)
        raise


@telemetry_step(step_id=1)
async def get_audio_script(
    request_id: str,
    graph: CompiledStateGraph,
    input_prompt: str,
    connection_manager: WebSocket,
):
    """
    Run the audio script generation graph and return the result.

    Args:
        request_id (str): Unique request identifier for file storage.
        graph (CompiledStateGraph): The compiled message graph for audio generation.
        input_prompt (str): The prompt for the audio topic.
        connection_manager (WebSocket): WebSocket for sending progress updates.

    Returns:
        dict: The result of the graph execution.
    """
    try:
        result = await graph.with_config({"run_name": request_id}).ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=f'Write the script for a podcast titled "{input_prompt}"'
                    )
                ],
                "criticised": 0,
                "connection_manager": connection_manager,
            }
        )
        print("Script written successfully", flush=True)
        return result
    except asyncio.CancelledError as cancel_err:
        print(f"[CANCELLED] LangGraph execution was interrupted: {cancel_err}", flush=True)
        raise


async def generate_video(
    request_id: str,
    input_prompt: str,
    frame_rate: int,
    resolution: str,
    connection_manager: WebSocket,
    background_image_path: str,
):
    """
    Orchestrate the entire video generation process, including script writing, audio generation, video creation, and cleanup.
    Sends progress updates to the client at each step.

    Args:
        request_id (str): Unique request identifier for file storage.
        input_prompt (str): The prompt for the video topic.
        frame_rate (int): Frame rate for the output video.
        resolution (str): Resolution key (e.g., '720p').
        connection_manager (WebSocket): WebSocket for sending progress updates.
        background_image_path (str): Path to the background image.
    """
    try:
        start_time = time.perf_counter()
        insert_request_stub(
            request_id=request_id,
            prompt=input_prompt,
            content_type="video",
            resolution=resolution,
            frame_rate=frame_rate,
        )
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": video_generation_steps[0]["id"],
                    "substep_index": 2,
                    "substep_status": "in-progress",
                }
            )
        )
        video_generator_graph = await build_content_generator_graph(
            content_type="video"
        )
        if video_generator_graph is not None:
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[0]["id"],
                        "substep_index": 2,
                        "substep_status": "completed",
                    }
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[0]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[1]["id"], "status": "in-progress"}
                )
            )
            result = await get_video_script(
                request_id=request_id,
                graph=video_generator_graph,
                input_prompt=input_prompt,
                connection_manager=connection_manager,
            )
            print('Script generated successfully.', flush=True)
            subsections = ast.literal_eval(
                result["messages"][-1]
                .content.replace("Process completed successfully: ", "")
                .strip()
            )
            print(f"Subsections: {subsections}", flush=True)
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[1]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[2]["id"], "status": "in-progress"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[2]["id"],
                        "substep_index": 0,
                        "substep_status": "in-progress",
                    }
                )
            )
            audio_file_names = await audio_generator_node(
                request_id=request_id, subsections=subsections
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[2]["id"],
                        "substep_index": 0,
                        "substep_status": "completed",
                    }
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[2]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[3]["id"], "status": "in-progress"}
                )
            )
            await video_file_generator_node(
                frame_rate=frame_rate,
                resolution=resolution,
                connection_manager=connection_manager,
                background_image_path=background_image_path,
                subsections=subsections,
                audio_file_names=audio_file_names,
                request_id=request_id,
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[3]["id"],
                        "substep_index": 1,
                        "substep_status": "completed",
                    }
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[3]["id"],
                        "substep_index": 2,
                        "substep_status": "in-progress",
                    }
                )
            )
            print("Success")
            video_url = f"/videos/{request_id}.mp4"
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[3]["id"],
                        "substep_index": 2,
                        "substep_status": "completed",
                    }
                )
            )
            final_payload = {"status": "complete", "video_url": video_url}
            await connection_manager.send_text(
                json.dumps(
                    {"step": video_generation_steps[3]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(json.dumps(final_payload))
            print(f"Process complete. Video available at URL: {video_url}")
            duration = round(time.perf_counter() - start_time, 2)
            update_request_final_status(
                request_id=request_id, status="completed", duration_seconds=duration
            )
    except Exception as e:
        duration = round(time.perf_counter() - start_time, 2)
        update_request_final_status(
            request_id=request_id, status="failed", duration_seconds=duration
        )
        raise e


async def generate_audio(
    request_id: str, input_prompt: str, connection_manager: WebSocket
):
    """
    Orchestrate the entire audio generation process, including script writing, section splitting, audio creation, and cleanup.
    Sends progress updates to the client at each step.

    Args:
        request_id (str): Unique request identifier for file storage.
        input_prompt (str): The prompt for the audio topic.
        connection_manager (WebSocket): WebSocket for sending progress updates.
    """
    try:
        start_time = time.perf_counter()
        insert_request_stub(
            request_id=request_id,
            prompt=input_prompt,
            content_type="audio",
        )
        await connection_manager.send_text(
            json.dumps(
                {
                    "step": audio_generation_steps[0]["id"],
                    "substep_index": 2,
                    "substep_status": "in-progress",
                }
            )
        )
        audio_generator_graph = await build_content_generator_graph(
            content_type="audio"
        )
        print("Built audio generator graph")

        if audio_generator_graph is not None:
            print(audio_generator_graph)
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[0]["id"],
                        "substep_index": 2,
                        "substep_status": "completed",
                    }
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": audio_generation_steps[0]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": audio_generation_steps[1]["id"], "status": "in-progress"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[1]["id"],
                        "substep_index": 0,
                        "substep_status": "in-progress",
                    }
                )
            )
            result = await get_audio_script(
                request_id=request_id,
                graph=audio_generator_graph,
                input_prompt=input_prompt,
                connection_manager=connection_manager,
            )
            sections = await section_finder(content=result["messages"][-1].content)
            print(f"Sections: {sections}, type: {type(sections)}")
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": video_generation_steps[1][
                            "id"
                        ],  # scripting steps are the same for both audio and video generation
                        "substep_index": 2,
                        "substep_status": "completed",
                    }
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": audio_generation_steps[1]["id"], "status": "completed"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {"step": audio_generation_steps[2]["id"], "status": "in-progress"}
                )
            )
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[2]["id"],
                        "substep_index": 0,
                        "substep_status": "in-progress",
                    }
                )
            )
            audio_file_name = await audio_file_generator_node(
                connection_manager=connection_manager,
                sections=sections,
                request_id=request_id,
            )
            if audio_file_name is None:
                await connection_manager.send_text(
                    json.dumps(
                        {
                            "step": audio_generation_steps[2]["id"],
                            "substep_index": 1,
                            "substep_status": "failed",
                        }
                    )
                )
                return None
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[2]["id"],
                        "substep_index": 1,
                        "substep_status": "completed",
                    }
                )
            )
            print("Audio generation success")
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[2]["id"],
                        "substep_index": 2,
                        "substep_status": "in-progress",
                    }
                )
            )
            audio_url = f"/audios/{request_id}.mp3"
            final_payload = {"status": "complete", "audio_url": audio_url}
            await connection_manager.send_text(json.dumps(final_payload))
            await connection_manager.send_text(
                json.dumps(
                    {
                        "step": audio_generation_steps[2]["id"],
                        "substep_index": 2,
                        "substep_status": "completed",
                    }
                )
            )

            await connection_manager.send_text(
                json.dumps(
                    {"step": audio_generation_steps[2]["id"], "status": "completed"}
                )
            )
            print(f"Process complete. Audio available at URL: {audio_url}")
            duration = round(time.perf_counter() - start_time, 2)
            update_request_final_status(
                request_id=request_id, status="completed", duration_seconds=duration
            )
    except Exception as e:
        duration = round(time.perf_counter() - start_time, 2)
        update_request_final_status(
            request_id=request_id, status="failed", duration_seconds=duration
        )
        raise e
