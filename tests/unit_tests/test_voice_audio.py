import sys
import types

import pytest

from voice.audio import EnergyVad, SileroVad, UtteranceBuffer, build_vad


def _pcm_frame(sample: int, frame_samples: int = 160) -> bytes:
    return int(sample).to_bytes(2, "little", signed=True) * frame_samples


def test_build_vad_falls_back_to_energy_vad_when_silero_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = __import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "silero_vad":
            raise ImportError("silero_vad not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    vad = build_vad(provider="silero")

    assert isinstance(vad, EnergyVad)


def test_silero_vad_tracks_stream_start_and_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [{"start": 0}, None, {"end": 512}]

    class FakeIterator:
        def __init__(self, *_args, **_kwargs) -> None:
            self.reset_called = False

        def __call__(self, _samples, return_seconds: bool = False):  # type: ignore[no-untyped-def]
            assert return_seconds is False
            return events.pop(0) if events else None

        def reset_states(self) -> None:
            self.reset_called = True

    fake_silero = types.SimpleNamespace(
        VADIterator=FakeIterator,
        load_silero_vad=lambda: object(),
    )
    fake_torch = types.SimpleNamespace(
        set_num_threads=lambda _count: None,
        from_numpy=lambda array: array,
    )
    monkeypatch.setitem(sys.modules, "silero_vad", fake_silero)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    vad = SileroVad()

    assert vad.is_speech(_pcm_frame(1200)) is False
    assert vad.is_speech(_pcm_frame(1200)) is True
    assert vad.is_speech(_pcm_frame(1200)) is True
    assert vad.is_speech(_pcm_frame(0)) is True
    assert vad.is_speech(_pcm_frame(0)) is False

    vad.reset()

    assert vad._iterator.reset_called is True  # type: ignore[attr-defined]


class ScriptedVad:
    def __init__(self, states: list[bool]) -> None:
        self.states = iter(states)
        self.reset_calls = 0

    def is_speech(self, _pcm16: bytes) -> bool:
        return next(self.states)

    def reset(self) -> None:
        self.reset_calls += 1


def test_utterance_buffer_includes_preroll_and_closes_after_silence() -> None:
    vad = ScriptedVad([False, False, True, True, False, False])
    buffer = UtteranceBuffer(
        vad=vad,
        silence_frames_to_close=2,
        min_speech_frames=2,
        preroll_frames=2,
    )

    pre1 = _pcm_frame(0)
    pre2 = _pcm_frame(0)
    speech1 = _pcm_frame(1000)
    speech2 = _pcm_frame(1000)
    tail1 = _pcm_frame(0)
    tail2 = _pcm_frame(0)

    assert buffer.push(pre1) is None
    assert buffer.push(pre2) is None
    assert buffer.push(speech1) is None
    assert buffer.push(speech2) is None
    assert buffer.push(tail1) is None
    utterance = buffer.push(tail2)

    assert utterance == pre1 + pre2 + speech1 + speech2 + tail1 + tail2
    assert vad.reset_calls == 1


def test_utterance_buffer_discards_short_noise_bursts() -> None:
    vad = ScriptedVad([True, False, False])
    buffer = UtteranceBuffer(
        vad=vad,
        silence_frames_to_close=2,
        min_speech_frames=2,
    )

    assert buffer.push(_pcm_frame(900)) is None
    assert buffer.push(_pcm_frame(0)) is None
    assert buffer.push(_pcm_frame(0)) is None
    assert buffer.frames == []
    assert vad.reset_calls == 1


def test_utterance_buffer_reports_speech_start_once() -> None:
    buffer = UtteranceBuffer(
        vad=ScriptedVad([True, True, False, False]),
        silence_frames_to_close=2,
        min_speech_frames=2,
    )

    assert buffer.push(_pcm_frame(900)) is None
    assert buffer.consume_speech_started() is False
    assert buffer.push(_pcm_frame(900)) is None
    assert buffer.consume_speech_started() is True
    assert buffer.consume_speech_started() is False
    assert buffer.push(_pcm_frame(0)) is None
    assert buffer.push(_pcm_frame(0)) is not None
