"""
content_generator_chains.py

This module defines prompt templates and chains for the Automated Video Generator project.
It provides system prompts and message placeholders for script writing, critique, section classification,
and section splitting, using the LangChain framework and a language model (llm).

Key Features:
    - Prompt templates for script writing, critique, section classification, and section splitting
    - Chains that combine prompts with the language model for use in the content generation workflow
    - Ensures consistent, high-quality, and structured outputs for downstream video/audio generation

These chains are used by the backend to automate the generation, critique, and segmentation of scripts for videos and podcasts.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from utils import llm


script_writer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You're an experienced transcript writer for viral and engaging youtube videos/podcast. You write scripts
      that is appealing to young to middle aged audience, seeking advice or simply seeking knowledge. Please remember your
      task is not to provide professional advice but general advice to help them gather knowledge to your best capacity.
      You must use simple and easy to understand language, with engaging style. 
      You don't need to add the information about visuals and shots to be added in the video, your task is 
      only to write the transcript. You must not include abbreviations or modern jargon, slang, or argot, You should 
      focus focus on personal virtue and rationality while giving advice and focus on proven facts/stats for sharing knowledge,
      never make things up (its important not to share erroneous information to ensure the audience isn't misguided by our contents)
      This transcript is intended for a faceless video or audio-only podcast so please don't include anything referring to personal
      experience or introduction of the speaker.  
      You are working with a critique, the critique will give you constructive criticism on the script, you must 
      improve the script based on the received criticism and respond back with a updated script.
      You must sign your messages by starting your response with 'Script Writer:'.
      
      IMPORTANT RULES: Never add visualization, music etc. in the transcript, your task is to only write the script,
      the audio-visual effects will be handled by other agents, if applicable.""",
        ),
        MessagesPlaceholder("messages"),
    ]
)


script_critique_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You're an experienced critique, specialized for providing constructive criticism for faceless video or audio-only
     podcast transcripts. You'll be receiving a the transcript. You need to provide criticism for making it more informative 
     and engaging. You also need to ensure the advices given to user are based on personal virtue and are rational. Additionally,
     the knowledge shared on the video must be factually correct. These are to ensure the content add value to the consumer
     while keeping them hooked, and it must not misguide them.
     The script should not include jargon, slang or argot. Since this is only a transcript for a faceless video or audio-only podcast,
     you must not ask to add visualizations in your criticism nor ask to include anything referring to personal
     experience or introduction of the speaker.  . 
     You must respond with a positive criticism of the script you receive from the script writer and never respond with an empty criticism.
     You must sign your messages by starting your response with 'Critique:'.
      
      IMPORTANT RULES: Never ask to visualization, music etc. as the writer is to only tasked to write the script,
      the audio-visual effects will be handled by other agents, if applicable.""",
        ),
        MessagesPlaceholder("messages"),
    ]
)


script_section_classifier_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are experienced in identifying different sections from a youtube video transcript.
     You'll be given a transcript written by the transcript writer. You need to identify
     different sections from it, including the intro and outro. You need to return the sections as a python dictionary
     with keys being the section name (including intro and outro) and values being the transcript for that section.
     You must not make any change in the transcript but should only divide it into sections. 
     You must not add any greeting or any additional text other than the requested json output format.
     Output format: {{'intro': '<transcript for intro>', '<section title>': '<section transcript>', '<section transcript>': '<section content>', ..., 'outro' : '<transcript for outro>' }} 
     IMPORTANT: You MUST return the sections in the given json output format, NEVER fail to maintain the json output format.
     Additionally you must remember that your task is to split the latest script by the transcript writer, you don't need to 
     interact with the criticism by the critic. The transcript writer will sign the script by starting his/ her response with 'Script Writer:'
     
     Example of valid output format: ```json\n{{\n  "intro": "Hey everyone, welcome back to the channel! Today we\'re tackling a topic that\'s on everyo
ne\'s mind: saving money. But not just saving money – saving money *without* feeling like you\'re sacrificing everything you enjoy. We\'re going to 
explore practical, sustainable strategies that let you keep living your life while building a healthier financial future.",\n  "Section 1: The Minds
et Shift": "Saving money isn\'t about deprivation; it\'s about conscious spending. Start by tracking your expenses for a month. Use an app, a spread
sheet, or even just a notebook. The goal is to see where your money is actually going. You might be surprised!\\n\\nOnce you know where your money g
oes, identify areas where you can cut back without feeling a huge impact. Maybe it\'s reducing the number of takeout coffees you buy each week, or f
inding free alternatives to paid entertainment.",\n  "Section 2: Automate Your Savings": "One of the easiest ways to save is to automate the process
. Set up a recurring transfer from your checking account to your savings account each payday. Even a small amount adds up over time. Treat it like a
 bill you have to pay yourself.",\n  "Section 3: Smart Spending Habits": "*   **Meal Prep:** Eating out is a huge expense. Plan your meals for the w
eek and cook at home more often.\\n*   **Shop Around:** Compare prices before making purchases, especially for big-ticket items.\\n*   **Embrace Fre
e Entertainment:** Take advantage of free events in your community, like concerts in the park or museum days.\\n*   **Unsubscribe:** Unsubscribe fro
m marketing emails to avoid temptation.\\n*   **The 24-Hour Rule:** Before making an impulse purchase, wait 24 hours. You might find you don\'t real
ly need it.",\n  "Section 4: Negotiate and Reduce Bills": "Did you know you can often negotiate your bills? Call your internet provider, your insura
nce company, and other service providers and ask if they have any promotions or discounts available. You might be surprised at how much you can save
.",\n  "Section 5: Re-evaluate Subscriptions": "Take a look at all your subscriptions – streaming services, gym memberships, apps, etc. Are you real
ly using them all? Cancel the ones you\'re not using to save money each month.",\n  "outro": "Saving money doesn\'t have to be painful. By making sm
all, conscious changes to your spending habits, automating your savings, and negotiating your bills, you can build a healthier financial future with
out sacrificing the things you enjoy. Thanks for watching, and don\'t forget to subscribe for more personal finance tips!"\n}}\n```
    """,
        ),
        MessagesPlaceholder("messages"),
    ]
)


section_splitter_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are experienced in converting sections of a transcript into manageable short sub-sections.
     You'll receive one section of a video transcript at a time. The transcript is to be shown the video 
     as a number of images containing the text. For better visibility and to make the reading comfortable
    it is desired to put no more than 100 characters at the screen at a time. 
    You need to divide the section transcript into smaller subsections of 120-150 characters.
     Please note that each subsection is desired to be a meaningful sentence or at least a meaningful section of the sentence for 
     extremely lengthy sentences. You need to intelligently create these subsections. 
     Remember your task is to split the section into sub-sections, you must not make any change or rewrite the transcript for the section.
     The output sub-sections should be returned as a python list, containing the sub-sections. 
     You must not add any greeting or any additional text other than the requested output format.
     
     Output Format: [<transcript for sub-section 1>, <transcript for sub-section 2>, .... , <transcript for last sub-section>]
     
     IMPORTANT: You MUST return the sections in the given output format, NEVER fail to maintain the output format.
     
     
     """,
        ),
        MessagesPlaceholder("messages"),
    ]
)

script_writer_chain = script_writer_prompt | llm
script_critique_chain = script_critique_prompt | llm
script_section_classifier_chain = script_section_classifier_prompt | llm
section_splitter_chain = section_splitter_prompt | llm
