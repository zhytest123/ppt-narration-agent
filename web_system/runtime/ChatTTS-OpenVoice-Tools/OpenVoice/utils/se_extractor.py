import os
import glob
import sys
import torch
from glob import glob
import numpy as np


def _conda_tool_path(tool_name):
    exe_name = f"{tool_name}.exe" if os.name == "nt" else tool_name
    for conda_prefix in (os.path.dirname(sys.executable), os.environ.get("CONDA_PREFIX", "")):
        for bin_dir in ("bin", os.path.join("Library", "bin")):
            tool_path = os.path.join(conda_prefix, bin_dir, exe_name)
            if os.path.exists(tool_path):
                return tool_path
    return tool_name


FFMPEG_PATH = _conda_tool_path("ffmpeg")
FFPROBE_PATH = _conda_tool_path("ffprobe")
if os.path.isabs(FFMPEG_PATH):
    os.environ["PATH"] = os.path.dirname(FFMPEG_PATH) + os.pathsep + os.environ.get("PATH", "")
from pydub import AudioSegment
AudioSegment.converter = FFMPEG_PATH
AudioSegment.ffmpeg = FFMPEG_PATH
AudioSegment.ffprobe = FFPROBE_PATH

model_size = "medium"
# Run on GPU with FP16
model = None
def split_audio_whisper(audio_path, target_dir='processed'):
    from faster_whisper import WhisperModel

    global model
    if model is None:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    audio = AudioSegment.from_file(audio_path)
    max_len = len(audio)

    audio_name = os.path.basename(audio_path).rsplit('.', 1)[0]
    target_folder = os.path.join(target_dir, audio_name)
    
    segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)
    segments = list(segments)    

    # create directory
    os.makedirs(target_folder, exist_ok=True)
    wavs_folder = os.path.join(target_folder, 'wavs')
    os.makedirs(wavs_folder, exist_ok=True)

    # segments
    s_ind = 0
    start_time = None
    
    for k, w in enumerate(segments):
        # process with the time
        if k == 0:
            start_time = max(0, w.start)

        end_time = w.end

        # calculate confidence
        if len(w.words) > 0:
            confidence = sum([s.probability for s in w.words]) / len(w.words)
        else:
            confidence = 0.
        # clean text
        text = w.text.replace('...', '')

        # left 0.08s for each audios
        audio_seg = audio[int( start_time * 1000) : min(max_len, int(end_time * 1000) + 80)]

        # segment file name
        fname = f"{audio_name}_seg{s_ind}.wav"

        # filter out the segment shorter than 1.5s and longer than 20s
        save = audio_seg.duration_seconds > 1.5 and \
                audio_seg.duration_seconds < 20. and \
                len(text) >= 2 and len(text) < 200 

        if save:
            output_file = os.path.join(wavs_folder, fname)
            audio_seg.export(output_file, format='wav')

        if k < len(segments) - 1:
            start_time = max(0, segments[k+1].start - 0.08)

        s_ind = s_ind + 1
    return wavs_folder


def split_audio_vad(audio_path, target_dir, split_seconds=10.0):
    audio = AudioSegment.from_file(audio_path)
    audio_dur = audio.duration_seconds
    print(f'audio dur = {audio_dur}')
    audio_name = os.path.basename(audio_path).rsplit('.', 1)[0]
    target_folder = os.path.join(target_dir, audio_name)
    wavs_folder = os.path.join(target_folder, 'wavs')
    os.makedirs(wavs_folder, exist_ok=True)
    start_time = 0.
    count = 0
    assert audio_dur > 0, 'input audio is too short'
    num_splits = max(1, int(np.round(audio_dur / split_seconds)))
    interval = audio_dur / num_splits

    for i in range(num_splits):
        end_time = min(start_time + interval, audio_dur)
        if i == num_splits - 1:
            end_time = audio_dur
        output_file = f"{wavs_folder}/{audio_name}_seg{count}.wav"
        audio_seg = audio[int(start_time * 1000): int(end_time * 1000)]
        audio_seg.export(output_file, format='wav')
        start_time = end_time
        count += 1
    return wavs_folder


    


def get_se(audio_path, vc_model, target_dir='processed', vad=True):
    device = vc_model.device

    audio_name = os.path.basename(audio_path).rsplit('.', 1)[0]
    se_path = os.path.join(target_dir, audio_name, 'se.pth')

    if os.path.isfile(se_path):
        se = torch.load(se_path).to(device)
        return se, audio_name
    if os.path.isdir(audio_path):
        wavs_folder = audio_path
    elif vad:
        wavs_folder = split_audio_vad(audio_path, target_dir)
    else:
        wavs_folder = split_audio_whisper(audio_path, target_dir)
    
    audio_segs = glob(f'{wavs_folder}/*.wav')
    if len(audio_segs) == 0:
        raise NotImplementedError('No audio segments found!')
    
    return vc_model.extract_se(audio_segs, se_save_path=se_path), audio_name

