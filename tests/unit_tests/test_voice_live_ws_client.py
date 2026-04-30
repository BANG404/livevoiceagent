from voice.live_ws_client import (
    LocalTurnDetector,
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
