import subprocess

import pytest

from voice.live_ws_client import (
    LocalTurnDetector,
    PulseAudioBridge,
    normalize_command,
    parse_args,
    parse_device,
    tail_silence_frames,
)


def test_tail_silence_frames_uses_20ms_chunks() -> None:
    assert tail_silence_frames(800) == 40
    assert tail_silence_frames(1) == 1


def test_normalize_command_strips_and_lowercases() -> None:
    assert normalize_command("  R  ") == "r"


def test_parse_args_for_live_ws_client() -> None:
    args = parse_args(
        [
            "--url",
            "ws://localhost:8000/twilio/media",
            "--input-device",
            "1",
            "--output-device",
            "2",
            "--tail-silence-ms",
            "600",
            "--send-poll-ms",
            "7",
        ]
    )

    assert args.url == "ws://localhost:8000/twilio/media"
    assert args.input_device == "1"
    assert args.output_device == "2"
    assert args.tail_silence_ms == 600
    assert args.send_poll_ms == 7
    assert args.manual_turns is False
    assert args.vad_provider == "silero"
    assert args.min_speech_frames == 5
    assert args.interrupt_speech_frames == 8


class ScriptedVad:
    def __init__(self, states: list[bool]) -> None:
        self.states = iter(states)
        self.reset_calls = 0

    def is_speech(self, _pcm16: bytes) -> bool:
        return next(self.states)

    def reset(self) -> None:
        self.reset_calls += 1


def test_local_turn_detector_streams_preroll_and_closes_after_silence() -> None:
    detector = LocalTurnDetector(
        vad=ScriptedVad([False, True, True, False, False]),
        tail_silence_ms=40,
        min_speech_frames=2,
        preroll_frames=3,
    )
    frame = b"\x01" * 320

    frames, event = detector.push(frame)
    assert frames == []
    assert event is None

    frames, event = detector.push(frame)
    assert frames == []
    assert event is None

    frames, event = detector.push(frame)
    assert frames == [frame, frame, frame]
    assert event == "start"

    frames, event = detector.push(frame)
    assert frames == [frame]
    assert event is None

    frames, event = detector.push(frame)
    assert frames == [frame]
    assert event == "stop"
    assert detector.vad.reset_calls == 1


def test_local_turn_detector_requires_more_frames_during_agent_playback() -> None:
    agent_speaking = True
    detector = LocalTurnDetector(
        vad=ScriptedVad([True, True, True, False, False]),
        tail_silence_ms=40,
        min_speech_frames=2,
        interrupt_speech_frames=3,
        preroll_frames=3,
        is_agent_speaking=lambda: agent_speaking,
    )
    frame = b"\x01" * 320

    frames, event = detector.push(frame)
    assert frames == []
    assert event is None

    frames, event = detector.push(frame)
    assert frames == []
    assert event is None

    frames, event = detector.push(frame)
    assert frames == [frame, frame, frame]
    assert event == "start"


def test_parse_device_supports_int_and_string() -> None:
    assert parse_device("1") == 1
    assert parse_device("RDPSource") == "RDPSource"
    assert parse_device(None) is None


def test_pulseaudio_bridge_start_fails_fast_when_backend_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        def __init__(self, *, stderr: bytes, returncode: int = 1) -> None:
            self.stdout = None
            self.stdin = None
            self.stderr = _FakeReader(stderr)
            self._returncode = returncode

        def poll(self) -> int:
            return self._returncode

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return self._returncode

        def kill(self) -> None:
            return None

    class _FakeReader:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

    processes = [
        FakeProcess(stderr=b"Connection failure: Connection refused\n"),
        FakeProcess(stderr=b""),
    ]

    def fake_popen(*_args, **_kwargs) -> FakeProcess:  # type: ignore[no-untyped-def]
        return processes.pop(0)

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/fake")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    bridge = PulseAudioBridge()

    with pytest.raises(RuntimeError, match="PulseAudio command `parec` failed to start"):
        bridge.start()
