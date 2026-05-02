import asyncio
import subprocess

import pytest
import voice.live_ws_client as live_ws_client

from voice.live_ws_client import (
    LocalTurnDetector,
    PulseAudioBridge,
    choose_audio_bridge,
    detect_pulse_server,
    is_wsl_pulse_available,
    list_pulse_devices,
    main,
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


def test_detect_pulse_server_prefers_existing_env_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse")
    monkeypatch.setattr(
        "os.path.exists",
        lambda path: path in {"/tmp/pulse"}
        and path != "/mnt/wslg/runtime-dir/pulse/native",
    )

    assert detect_pulse_server() == "unix:/tmp/pulse"


def test_detect_pulse_server_falls_back_to_wslg_runtime_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PULSE_SERVER", raising=False)
    monkeypatch.setattr(
        "os.path.exists",
        lambda path: path == "/mnt/wslg/runtime-dir/pulse/native",
    )

    assert detect_pulse_server() == "unix:/mnt/wslg/runtime-dir/pulse/native"


def test_detect_pulse_server_prefers_wslg_runtime_socket_over_stale_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")
    monkeypatch.setattr(
        "os.path.exists",
        lambda path: path == "/mnt/wslg/runtime-dir/pulse/native",
    )

    assert detect_pulse_server() == "unix:/mnt/wslg/runtime-dir/pulse/native"


def test_is_wsl_pulse_available_uses_detected_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse")
    monkeypatch.setattr("os.path.exists", lambda path: path == "/tmp/pulse")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/parec" if name == "parec" else None)

    assert is_wsl_pulse_available() is True


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

    bridge = PulseAudioBridge(startup_retries=1)

    with pytest.raises(
        RuntimeError, match="PulseAudio command `parec` failed to start"
    ):
        bridge.start()


def test_list_pulse_devices_requires_server_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/pactl")
    monkeypatch.setattr("os.path.exists", lambda _path: False)
    monkeypatch.delenv("PULSE_SERVER", raising=False)

    with pytest.raises(RuntimeError, match="No PulseAudio server is configured"):
        list_pulse_devices()


def test_list_pulse_devices_wraps_pactl_failure_with_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/pactl")
    monkeypatch.setattr("os.path.exists", lambda path: path == "/tmp/pulse")
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse")

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(
            1,
            ["pactl", "list", "short", "sources"],
            stderr="Connection failure: Connection refused",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(
        RuntimeError,
        match="using unix:/tmp/pulse: Connection failure: Connection refused",
    ):
        list_pulse_devices()


def test_main_returns_1_for_runtime_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "voice.live_ws_client.async_main",
        lambda _argv=None: (_ for _ in ()).throw(RuntimeError("pulse failed")),
    )

    exit_code = main(["--list-pulse-devices"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "error: pulse failed"


def test_choose_audio_bridge_prefers_pulseaudio_on_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pulse_bridge = object()
    local_called = False

    def fake_pulse_bridge(**_kwargs: object) -> object:
        return pulse_bridge

    def fake_local_bridge(**_kwargs: object) -> object:
        nonlocal local_called
        local_called = True
        return object()

    monkeypatch.setattr("voice.live_ws_client.is_wsl_pulse_available", lambda: True)
    monkeypatch.setattr("voice.live_ws_client.PulseAudioBridge", fake_pulse_bridge)
    monkeypatch.setattr("voice.live_ws_client.LocalAudioBridge", fake_local_bridge)

    bridge, backend = choose_audio_bridge(
        input_device="RDPSource",
        output_device="RDPSink",
    )

    assert bridge is pulse_bridge
    assert backend == "pulseaudio"
    assert local_called is False


def test_choose_audio_bridge_falls_back_to_sounddevice_when_pulse_fails_on_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_bridge = object()

    def fake_pulse_bridge(**_kwargs: object) -> object:
        raise RuntimeError("pulse failed")

    def fake_local_bridge(**_kwargs: object) -> object:
        return local_bridge

    monkeypatch.setattr("voice.live_ws_client.is_wsl_pulse_available", lambda: True)
    monkeypatch.setattr("voice.live_ws_client.PulseAudioBridge", fake_pulse_bridge)
    monkeypatch.setattr("voice.live_ws_client.LocalAudioBridge", fake_local_bridge)

    bridge, backend = choose_audio_bridge()

    assert bridge is local_bridge
    assert backend == "sounddevice"


def test_run_live_session_falls_back_when_pulse_start_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakePulseBridge:
        def __init__(self) -> None:
            self.closed = False

        def start(self) -> None:
            raise RuntimeError("pulse start failed")

        async def aclose(self) -> None:
            self.closed = True

    class FakeLocalBridge:
        def __init__(self, **_kwargs: object) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

        def close(self) -> None:
            return None

    class FakeWebSocket:
        async def send(self, _payload: str) -> None:
            return None

    class FakeConnect:
        async def __aenter__(self) -> FakeWebSocket:
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    pulse_bridge = FakePulseBridge()
    local_bridge = FakeLocalBridge()

    monkeypatch.setattr(
        live_ws_client,
        "choose_audio_bridge",
        lambda **_kwargs: (pulse_bridge, "pulseaudio"),
    )
    monkeypatch.setattr(
        live_ws_client,
        "LocalAudioBridge",
        lambda **_kwargs: local_bridge,
    )
    monkeypatch.setattr(live_ws_client, "connect", lambda *args, **kwargs: FakeConnect())
    monkeypatch.setattr(live_ws_client, "receive_agent_audio", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(live_ws_client, "send_microphone_audio", lambda *args, **kwargs: asyncio.sleep(0))

    async def fake_command_loop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(live_ws_client, "command_loop", fake_command_loop)

    asyncio.run(live_ws_client.run_live_session("ws://localhost:8000/twilio/media"))

    captured = capsys.readouterr()
    assert pulse_bridge.closed is True
    assert local_bridge.started is True
    assert "PulseAudio startup failed, falling back to sounddevice: pulse start failed" in captured.out
    assert "audio backend: sounddevice" in captured.out
