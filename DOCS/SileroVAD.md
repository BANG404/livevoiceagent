Silero VAD - pre-trained enterprise-grade Voice Activity Detector (also see our STT models).




Real Time Example

Fast start

Dependencies
Using pip: pip install silero-vad

from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
model = load_silero_vad()
wav = read_audio('path_to_audio_file')
speech_timestamps = get_speech_timestamps(
  wav,
  model,
  return_seconds=True,  # Return speech timestamps in seconds (default is samples)
)
Using torch.hub:

import torch
torch.set_num_threads(1)

model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad')
(get_speech_timestamps, _, read_audio, _, _) = utils

wav = read_audio('path_to_audio_file')
speech_timestamps = get_speech_timestamps(
  wav,
  model,
  return_seconds=True,  # Return speech timestamps in seconds (default is samples)
)

Key Features

Stellar accuracy

Silero VAD has excellent results on speech detection tasks.

Fast

One audio chunk (30+ ms) takes less than 1ms to be processed on a single CPU thread. Using batching or GPU can also improve performance considerably. Under certain conditions ONNX may even run up to 4-5x faster.

Lightweight

JIT model is around two megabytes in size.

General

Silero VAD was trained on huge corpora that include over 6000 languages and it performs well on audios from different domains with various background noise and quality levels.

Flexible sampling rate

Silero VAD supports 8000 Hz and 16000 Hz sampling rates.

Highly Portable

Silero VAD reaps benefits from the rich ecosystems built around PyTorch and ONNX running everywhere where these runtimes are available.

No Strings Attached

Published under permissive license (MIT) Silero VAD has zero strings attached - no telemetry, no keys, no registration, no built-in expiration, no keys or vendor lock.


Typical Use Cases

Voice activity detection for IOT / edge / mobile use cases
Data cleaning and preparation, voice detection in general
Telephony and call-center automation, voice bots
Voice interfaces

Links

Examples and Dependencies
Quality Metrics
Performance Metrics
Versions and Available Models
Further reading
FAQ

Get In Touch

Try our models, create an issue, start a discussion, join our telegram chat, email us, read our news.

Please see our wiki for relevant information and email us directly.

Citations

@misc{Silero VAD,
  author = {Silero Team},
  title = {Silero VAD: pre-trained enterprise-grade Voice Activity Detector (VAD), Number Detector and Language Classifier},
  year = {2024},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/snakers4/silero-vad}},
  commit = {insert_some_commit_here},
  email = {hello@silero.ai}
}

Examples and VAD-based Community Apps

Example of VAD ONNX Runtime model usage in C++

Example of VAD ExecuTorch model usage in C++

Voice activity detection for the browser using ONNX Runtime Web

Rust, Rust (wavekat-vad), Go, Java, C++, C# and other community examples
