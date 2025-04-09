import ast
from utils import get_audio_clip
import os

with open('subsections.txt', 'r') as subsections_file:
    subsections = ast.literal_eval(subsections_file.read())
    print(subsections)

file_names = {}
for section_title, section_contents in subsections.items():
    section_audio_paths = []
    folder_name = rf'generated_audios/{section_title}'
    os.mkdir(folder_name)
    for index in range(len(section_contents)):
        content = section_contents[index]
        file_name = f'{folder_name}/{section_title}_{index}.wav'
        audio_clip = get_audio_clip(input_phrase=content,filename=file_name)
        section_audio_paths.append(file_name)
    file_names[section_title] = section_audio_paths

with open('output_audio_path.txt', 'w') as output_audio_file:
    output_audio_file.write(str(file_names))

