"""Interactive local microphone client for the Twilio-style websocket."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import queue
import shutil
import subprocess
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect

from voice.audio import (
    FRAME_BYTES_PCM16,
    TWILIO_SAMPLE_RATE,
    VoiceActivityDetector,
    build_vad,
    mulaw_payload_to_pcm16,
)
from voice.ws_test_client import build_media_event, build_start_event, build_stop_event


TAIL_FRAME_MS = 20


def tail_silence_frames(tail_silence_ms: int) -> int:
    return max(1, tail_silence_ms // TAIL_FRAME_MS)


def normalize_command(command: str) -> str:
    return command.strip().lower()


@dataclass
class SessionState:
    recording: bool = False
    closed: bool = False


class LocalTurnDetector:
    def __init__(
        self,
        vad: VoiceActivityDetector,
        tail_silence_ms: int,
        min_speech_frames: int = 3,
        interrupt_speech_frames: int = 8,
        preroll_frames: int = 6,
        is_agent_speaking: Callable[[], bool] | None = None,
    ) -> None:
        self.vad = vad
        self.silence_frames_to_close = tail_silence_frames(tail_silence_ms)
        self.min_speech_frames = min_speech_frames
        self.interrupt_speech_frames = interrupt_speech_frames
        self.preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.is_agent_speaking = is_agent_speaking or (lambda: False)
        self.active = False
        self.speech_frames = 0
        self.silence_frames = 0

    def push(self, pcm16: bytes) -> tuple[list[bytes], str | None]:
        speaking = self.vad.is_speech(pcm16)

        if not self.active:
            self.preroll.append(pcm16)
            self.speech_frames = self.speech_frames + 1 if speaking else 0
            required_frames = (
                self.interrupt_speech_frames
                if self.is_agent_speaking()
                else self.min_speech_frames
            )
            if self.speech_frames < required_frames:
                return [], None
            self.active = True
            self.silence_frames = 0
            return list(self.preroll), "start"

        self.silence_frames = 0 if speaking else self.silence_frames + 1
        event = None
        if self.silence_frames >= self.silence_frames_to_close:
            event = "stop"
            self._reset()
        return [pcm16], event

    def _reset(self) -> None:
        self.active = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.preroll.clear()
        self.vad.reset()


class LocalAudioBridge:
    def __init__(
        self,
        input_device: int | None = None,
        output_device: int | None = None,
        channels: int = 1,
        sample_rate: int = TWILIO_SAMPLE_RATE,
        frame_bytes: int = FRAME_BYTES_PCM16,
        max_queue_frames: int = 256,
    ) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is required for the live local voice client. "
                "Run `rtk uv sync --dev --extra voice-local` first."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                "PortAudio is not available on this system. "
                "Install it first, for example on Ubuntu/Debian run "
                "`sudo apt-get install portaudio19-dev`, then retry."
            ) from exc

        self.sd = sd
        self.channels = channels
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self.input_queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_frames)
        self.output_queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_frames)
        self.playback_active = False
        self.input_stream = sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=frame_bytes // 2,
            channels=channels,
            dtype="int16",
            device=input_device,
            callback=self._on_input,
        )
        self.output_stream = sd.RawOutputStream(
            samplerate=sample_rate,
            blocksize=frame_bytes // 2,
            channels=channels,
            dtype="int16",
            device=output_device,
            callback=self._on_output,
        )

    def start(self) -> None:
        self.input_stream.start()
        self.output_stream.start()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.input_stream.stop()
        with contextlib.suppress(Exception):
            self.output_stream.stop()
        with contextlib.suppress(Exception):
            self.input_stream.close()
        with contextlib.suppress(Exception):
            self.output_stream.close()

    def flush_input(self) -> None:
        while not self.input_queue.empty():
            with contextlib.suppress(queue.Empty):
                self.input_queue.get_nowait()

    def play(self, pcm16: bytes) -> None:
        self.playback_active = True
        for offset in range(0, len(pcm16), self.frame_bytes):
            frame = pcm16[offset : offset + self.frame_bytes]
            if len(frame) < self.frame_bytes:
                frame += b"\x00" * (self.frame_bytes - len(frame))
            self._put_output(frame)

    def clear_output(self) -> None:
        while not self.output_queue.empty():
            with contextlib.suppress(queue.Empty):
                self.output_queue.get_nowait()
        self.playback_active = False

    def is_output_active(self) -> bool:
        return self.playback_active

    def _on_input(self, indata: bytes, frames: int, time: Any, status: Any) -> None:
        if status:
            print(f"audio input status: {status}")
        if len(indata) != self.frame_bytes:
            indata = bytes(indata[: self.frame_bytes]).ljust(self.frame_bytes, b"\x00")
        self._put_input(bytes(indata))

    def _on_output(
        self,
        outdata: bytearray,
        frames: int,
        time: Any,
        status: Any,
    ) -> None:
        if status:
            print(f"audio output status: {status}")
        try:
            chunk = self.output_queue.get_nowait()
        except queue.Empty:
            chunk = b"\x00" * len(outdata)
            self.playback_active = False
        outdata[:] = chunk[: len(outdata)].ljust(len(outdata), b"\x00")

    def _put_input(self, frame: bytes) -> None:
        if self.input_queue.full():
            with contextlib.suppress(queue.Empty):
                self.input_queue.get_nowait()
        with contextlib.suppress(queue.Full):
            self.input_queue.put_nowait(frame)

    def _put_output(self, frame: bytes) -> None:
        if self.output_queue.full():
            with contextlib.suppress(queue.Empty):
                self.output_queue.get_nowait()
        with contextlib.suppress(queue.Full):
            self.output_queue.put_nowait(frame)


class PulseAudioBridge:
    def __init__(
        self,
        input_device: str | None = None,
        output_device: str | None = None,
        sample_rate: int = TWILIO_SAMPLE_RATE,
        frame_bytes: int = FRAME_BYTES_PCM16,
        max_queue_frames: int = 256,
    ) -> None:
        if shutil.which("parec") is None or shutil.which("paplay") is None:
            raise RuntimeError(
                "PulseAudio CLI tools are required for the WSL audio fallback. "
                "Install them with `sudo apt-get install pulseaudio-utils`."
            )

        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self.input_queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_frames)
        self.output_queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_frames)
        self.capture_process: subprocess.Popen[bytes] | None = None
        self.playback_process: subprocess.Popen[bytes] | None = None
        self.capture_task: asyncio.Task[None] | None = None
        self.playback_task: asyncio.Task[None] | None = None
        self.playback_active = False

    def start(self) -> None:
        env = os.environ.copy()
        parec_cmd = [
            "parec",
            "--format=s16le",
            "--channels=1",
            f"--rate={self.sample_rate}",
            "--raw",
        ]
        if self.input_device:
            parec_cmd.extend(["--device", self.input_device])

        paplay_cmd = [
            "paplay",
            "--raw",
            "--format=s16le",
            "--channels=1",
            f"--rate={self.sample_rate}",
        ]
        if self.output_device:
            paplay_cmd.extend(["--device", self.output_device])

        self.capture_process = subprocess.Popen(
            parec_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.playback_process = subprocess.Popen(
            paplay_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.capture_task = asyncio.create_task(self._capture_loop())
        self.playback_task = asyncio.create_task(self._playback_loop())

    async def aclose(self) -> None:
        if self.capture_task:
            self.capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.capture_task
        if self.playback_task:
            self.playback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.playback_task
        self._terminate_process(self.capture_process)
        self._terminate_process(self.playback_process)

    def flush_input(self) -> None:
        while not self.input_queue.empty():
            with contextlib.suppress(queue.Empty):
                self.input_queue.get_nowait()

    def play(self, pcm16: bytes) -> None:
        self.playback_active = True
        for offset in range(0, len(pcm16), self.frame_bytes):
            frame = pcm16[offset : offset + self.frame_bytes]
            if len(frame) < self.frame_bytes:
                frame += b"\x00" * (self.frame_bytes - len(frame))
            self._put_output(frame)

    def clear_output(self) -> None:
        while not self.output_queue.empty():
            with contextlib.suppress(queue.Empty):
                self.output_queue.get_nowait()
        self.playback_active = False

    def is_output_active(self) -> bool:
        return self.playback_active

    async def _capture_loop(self) -> None:
        assert self.capture_process is not None
        assert self.capture_process.stdout is not None

        while True:
            chunk = await asyncio.to_thread(
                self.capture_process.stdout.read,
                self.frame_bytes,
            )
            if not chunk:
                await asyncio.sleep(0.01)
                continue
            if len(chunk) < self.frame_bytes:
                chunk = chunk.ljust(self.frame_bytes, b"\x00")
            self._put_input(chunk)

    async def _playback_loop(self) -> None:
        assert self.playback_process is not None
        assert self.playback_process.stdin is not None

        while True:
            self.playback_active = False
            frame = await asyncio.to_thread(self.output_queue.get)
            self.playback_active = True
            await asyncio.to_thread(self.playback_process.stdin.write, frame)
            await asyncio.to_thread(self.playback_process.stdin.flush)
            if self.output_queue.empty():
                self.playback_active = False

    def _put_input(self, frame: bytes) -> None:
        if self.input_queue.full():
            with contextlib.suppress(queue.Empty):
                self.input_queue.get_nowait()
        with contextlib.suppress(queue.Full):
            self.input_queue.put_nowait(frame)

    def _put_output(self, frame: bytes) -> None:
        if self.output_queue.full():
            with contextlib.suppress(queue.Empty):
                self.output_queue.get_nowait()
        with contextlib.suppress(queue.Full):
            self.output_queue.put_nowait(frame)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes] | None) -> None:
        if process is None:
            return
        with contextlib.suppress(Exception):
            process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=1)
        with contextlib.suppress(Exception):
            process.kill()


def is_wsl_pulse_available() -> bool:
    return os.path.exists("/mnt/wslg/PulseServer") and shutil.which("parec") is not None


def choose_audio_bridge(
    input_device: int | str | None = None,
    output_device: int | str | None = None,
) -> tuple[Any, str]:
    try:
        bridge = LocalAudioBridge(
            input_device=input_device if isinstance(input_device, int) else None,
            output_device=output_device if isinstance(output_device, int) else None,
        )
        return bridge, "sounddevice"
    except Exception as exc:
        if not is_wsl_pulse_available():
            raise RuntimeError(
                f"Failed to initialize local audio via sounddevice: {exc}"
            ) from exc

        bridge = PulseAudioBridge(
            input_device=input_device if isinstance(input_device, str) else None,
            output_device=output_device if isinstance(output_device, str) else None,
        )
        return bridge, "pulseaudio"


async def send_microphone_audio(
    websocket: Any,
    audio_bridge: LocalAudioBridge,
    state: SessionState,
    stream_sid: str,
    poll_ms: int,
    *,
    manual_turns: bool,
    tail_silence_ms: int,
    vad_provider: str,
    vad_threshold: float,
    vad_min_silence_ms: int,
    min_speech_frames: int,
    interrupt_speech_frames: int,
    preroll_frames: int,
) -> None:
    if manual_turns:
        await send_microphone_audio_manual(
            websocket,
            audio_bridge,
            state,
            stream_sid,
            poll_ms=poll_ms,
        )
        return

    await send_microphone_audio_auto(
        websocket,
        audio_bridge,
        state,
        stream_sid,
        tail_silence_ms=tail_silence_ms,
        vad_provider=vad_provider,
        vad_threshold=vad_threshold,
        vad_min_silence_ms=vad_min_silence_ms,
        min_speech_frames=min_speech_frames,
        interrupt_speech_frames=interrupt_speech_frames,
        preroll_frames=preroll_frames,
    )


async def send_microphone_audio_manual(
    websocket: Any,
    audio_bridge: LocalAudioBridge,
    state: SessionState,
    stream_sid: str,
    poll_ms: int,
) -> None:
    while not state.closed:
        if not state.recording:
            await asyncio.sleep(poll_ms / 1000)
            continue

        frame = await asyncio.to_thread(audio_bridge.input_queue.get)
        if state.closed:
            return
        if not state.recording:
            continue

        await websocket.send(
            json.dumps(build_media_event(stream_sid, frame), ensure_ascii=False)
        )


async def send_microphone_audio_auto(
    websocket: Any,
    audio_bridge: LocalAudioBridge,
    state: SessionState,
    stream_sid: str,
    *,
    tail_silence_ms: int,
    vad_provider: str,
    vad_threshold: float,
    vad_min_silence_ms: int,
    min_speech_frames: int,
    interrupt_speech_frames: int,
    preroll_frames: int,
) -> None:
    detector = LocalTurnDetector(
        vad=build_vad(
            provider=vad_provider,
            threshold=vad_threshold,
            min_silence_duration_ms=vad_min_silence_ms,
        ),
        tail_silence_ms=tail_silence_ms,
        min_speech_frames=min_speech_frames,
        interrupt_speech_frames=interrupt_speech_frames,
        preroll_frames=preroll_frames,
        is_agent_speaking=audio_bridge.is_output_active,
    )

    while not state.closed:
        frame = await asyncio.to_thread(audio_bridge.input_queue.get)
        if state.closed:
            return

        frames_to_send, event = detector.push(frame)
        if event == "start":
            if audio_bridge.is_output_active():
                audio_bridge.clear_output()
                print("agent interrupted")
            state.recording = True
            print("speech started")

        for item in frames_to_send:
            await websocket.send(
                json.dumps(build_media_event(stream_sid, item), ensure_ascii=False)
            )

        if event == "stop":
            state.recording = False
            print("turn closed")


async def receive_agent_audio(
    websocket: Any,
    audio_bridge: LocalAudioBridge,
    state: SessionState,
) -> None:
    while not state.closed:
        raw = await websocket.recv()
        event = json.loads(raw)
        if event.get("event") == "clear":
            audio_bridge.clear_output()
            print("agent playback cleared")
            continue
        if event.get("event") != "media":
            print(f"recv event: {event.get('event')}")
            continue

        payload = event.get("media", {}).get("payload", "")
        pcm16 = mulaw_payload_to_pcm16(payload)
        audio_bridge.play(pcm16)


async def command_loop(
    websocket: Any,
    audio_bridge: LocalAudioBridge,
    state: SessionState,
    stream_sid: str,
    tail_silence_ms: int,
    *,
    manual_turns: bool,
) -> None:
    if not manual_turns:
        await auto_command_loop(websocket, state, stream_sid)
        return

    silence_frame = b"\x00" * FRAME_BYTES_PCM16
    silence_frames = tail_silence_frames(tail_silence_ms)
    print("commands: r=start recording, s=stop turn, q=quit")

    while not state.closed:
        command = normalize_command(
            await asyncio.to_thread(input, "> ")
        )

        if command == "r":
            audio_bridge.flush_input()
            state.recording = True
            print("recording")
            continue

        if command == "s":
            if not state.recording:
                print("not recording")
                continue
            state.recording = False
            for _ in range(silence_frames):
                await websocket.send(
                    json.dumps(
                        build_media_event(stream_sid, silence_frame),
                        ensure_ascii=False,
                    )
                )
                await asyncio.sleep(TAIL_FRAME_MS / 1000)
            print("turn closed")
            continue

        if command == "q":
            state.closed = True
            state.recording = False
            await websocket.send(json.dumps(build_stop_event(stream_sid), ensure_ascii=False))
            print("closing")
            return

        print("unknown command")


async def auto_command_loop(
    websocket: Any,
    state: SessionState,
    stream_sid: str,
) -> None:
    print("auto mode: speak naturally, q=quit")

    while not state.closed:
        command = normalize_command(await asyncio.to_thread(input, "> "))
        if command == "q":
            state.closed = True
            state.recording = False
            await websocket.send(
                json.dumps(build_stop_event(stream_sid), ensure_ascii=False)
            )
            print("closing")
            return
        if command:
            print("unknown command")


async def run_live_session(
    url: str,
    caller: str = "+8613800001234",
    call_sid: str = "CALIVELOCALTEST",
    stream_sid: str = "MZLIVELOCALTEST",
    input_device: int | str | None = None,
    output_device: int | str | None = None,
    tail_silence_ms: int = 800,
    send_poll_ms: int = 5,
    manual_turns: bool = False,
    vad_provider: str = "silero",
    vad_threshold: float = 0.5,
    vad_min_silence_ms: int = 350,
    min_speech_frames: int = 3,
    interrupt_speech_frames: int = 8,
    preroll_frames: int = 6,
) -> None:
    state = SessionState()
    audio_bridge, backend = choose_audio_bridge(
        input_device=input_device,
        output_device=output_device,
    )
    starter = getattr(audio_bridge, "start")
    close_async = getattr(audio_bridge, "aclose", None)
    close_sync = getattr(audio_bridge, "close", None)
    starter()
    print(f"audio backend: {backend}")

    try:
        async with connect(url, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    build_start_event(stream_sid, call_sid, caller),
                    ensure_ascii=False,
                )
            )
            print(f"connected: {url}")
            print(f"call_sid={call_sid} caller={caller}")

            receiver = asyncio.create_task(receive_agent_audio(websocket, audio_bridge, state))
            sender = asyncio.create_task(
                send_microphone_audio(
                    websocket,
                    audio_bridge,
                    state,
                    stream_sid,
                    poll_ms=send_poll_ms,
                    manual_turns=manual_turns,
                    tail_silence_ms=tail_silence_ms,
                    vad_provider=vad_provider,
                    vad_threshold=vad_threshold,
                    vad_min_silence_ms=vad_min_silence_ms,
                    min_speech_frames=min_speech_frames,
                    interrupt_speech_frames=interrupt_speech_frames,
                    preroll_frames=preroll_frames,
                )
            )

            try:
                await command_loop(
                    websocket,
                    audio_bridge,
                    state,
                    stream_sid,
                    tail_silence_ms=tail_silence_ms,
                    manual_turns=manual_turns,
                )
            finally:
                state.closed = True
                receiver.cancel()
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receiver
                with contextlib.suppress(asyncio.CancelledError):
                    await sender
    finally:
        if close_async is not None:
            await close_async()
        elif close_sync is not None:
            close_sync()


def list_devices() -> int:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is required for device listing. "
            "Run `rtk uv sync --dev --extra voice-local` first."
        ) from exc

    print(sd.query_devices())
    return 0


def list_pulse_devices() -> int:
    if shutil.which("pactl") is None:
        raise RuntimeError("`pactl` is required to list PulseAudio devices.")

    result = subprocess.run(
        ["pactl", "list", "short", "sources"],
        check=True,
        capture_output=True,
        text=True,
    )
    print("sources:")
    print(result.stdout.rstrip())
    result = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        check=True,
        capture_output=True,
        text=True,
    )
    print("sinks:")
    print(result.stdout.rstrip())
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive local microphone client for the voice websocket.",
    )
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8000/twilio/media",
        help="WebSocket endpoint to connect to.",
    )
    parser.add_argument(
        "--caller",
        default="+8613800001234",
        help="Caller number passed in customParameters.",
    )
    parser.add_argument(
        "--call-sid",
        default="CALIVELOCALTEST",
        help="CallSid passed in customParameters.",
    )
    parser.add_argument(
        "--stream-sid",
        default="MZLIVELOCALTEST",
        help="streamSid used in websocket events.",
    )
    parser.add_argument(
        "--input-device",
        help="Optional input device. Integer for sounddevice, string for PulseAudio.",
    )
    parser.add_argument(
        "--output-device",
        help="Optional output device. Integer for sounddevice, string for PulseAudio.",
    )
    parser.add_argument(
        "--tail-silence-ms",
        type=int,
        default=800,
        help="Silence used to close a turn after speech stops.",
    )
    parser.add_argument(
        "--send-poll-ms",
        type=int,
        default=5,
        help="Idle wait while paused between microphone polls.",
    )
    parser.add_argument(
        "--manual-turns",
        action="store_true",
        help="Use legacy manual `r`/`s` turn control instead of automatic VAD.",
    )
    parser.add_argument(
        "--vad-provider",
        default="silero",
        choices=["silero", "energy"],
        help="Local VAD used for automatic turn detection.",
    )
    parser.add_argument(
        "--vad-threshold",
        type=float,
        default=0.5,
        help="Threshold for the selected local VAD.",
    )
    parser.add_argument(
        "--vad-min-silence-ms",
        type=int,
        default=350,
        help="Silence duration before the local VAD marks speech as ended.",
    )
    parser.add_argument(
        "--min-speech-frames",
        type=int,
        default=5,
        help="Speech frames required before opening an automatic turn.",
    )
    parser.add_argument(
        "--interrupt-speech-frames",
        type=int,
        default=8,
        help="Speech frames required to interrupt agent playback.",
    )
    parser.add_argument(
        "--preroll-frames",
        type=int,
        default=6,
        help="Buffered frames sent before automatic speech start is confirmed.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print sounddevice devices and exit.",
    )
    parser.add_argument(
        "--list-pulse-devices",
        action="store_true",
        help="Print PulseAudio sources/sinks and exit.",
    )
    return parser.parse_args(argv)


def parse_device(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_devices:
        return await asyncio.to_thread(list_devices)
    if args.list_pulse_devices:
        return await asyncio.to_thread(list_pulse_devices)

    await run_live_session(
        url=args.url,
        caller=args.caller,
        call_sid=args.call_sid,
        stream_sid=args.stream_sid,
        input_device=parse_device(args.input_device),
        output_device=parse_device(args.output_device),
        tail_silence_ms=args.tail_silence_ms,
        send_poll_ms=args.send_poll_ms,
        manual_turns=args.manual_turns,
        vad_provider=args.vad_provider,
        vad_threshold=args.vad_threshold,
        vad_min_silence_ms=args.vad_min_silence_ms,
        min_speech_frames=args.min_speech_frames,
        interrupt_speech_frames=args.interrupt_speech_frames,
        preroll_frames=args.preroll_frames,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


__all__ = [
    "LocalAudioBridge",
    "LocalTurnDetector",
    "PulseAudioBridge",
    "SessionState",
    "choose_audio_bridge",
    "is_wsl_pulse_available",
    "list_devices",
    "list_pulse_devices",
    "main",
    "normalize_command",
    "parse_device",
    "parse_args",
    "run_live_session",
    "tail_silence_frames",
]
