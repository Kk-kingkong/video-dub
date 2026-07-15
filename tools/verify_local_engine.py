#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "server" / "local_dub_server.py"
NATIVE_HOST_PATH = ROOT / "companion" / "native_host.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("local_dub_server", SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_native_host_module():
    spec = importlib.util.spec_from_file_location("localtube_native_host_test", NATIVE_HOST_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_data_url_decode(server):
    data_url = "data:audio/webm;base64," + base64.b64encode(b"audio-bytes").decode("ascii")
    audio_bytes, mime_type = server.decode_data_url(data_url, "audio/webm")
    assert audio_bytes == b"audio-bytes"
    assert mime_type == "audio/webm"


def test_health_version_metadata(server):
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    payload = server.build_health_payload("test")
    assert payload["ok"] is True
    assert payload["service"] == "localtube-dub"
    assert payload["engineVersion"] == manifest["version"]
    assert payload["protocolVersion"] == 2


def test_http_byte_ranges(server):
    assert server.parse_http_byte_range("", 1000) is None
    assert server.parse_http_byte_range("bytes=0-99", 1000) == (0, 99)
    assert server.parse_http_byte_range("bytes=900-", 1000) == (900, 999)
    assert server.parse_http_byte_range("bytes=-100", 1000) == (900, 999)
    assert server.parse_http_byte_range("bytes=950-1200", 1000) == (950, 999)
    for invalid in ("items=0-1", "bytes=", "bytes=1000-", "bytes=20-10", "bytes=0-1,3-4", "bytes=-0"):
        try:
            server.parse_http_byte_range(invalid, 1000)
        except ValueError:
            continue
        raise AssertionError(f"range should be rejected: {invalid}")


def test_whisper_segments_to_cues(server):
    cues = server.whisper_payload_to_cues(
        {
            "language": "en",
            "segments": [
                {"start": 0.2, "end": 1.4, "text": " hello "},
                {"start": 1.5, "end": 2.0, "text": "world"},
            ],
        },
        start_time=10,
        duration_seconds=12,
    )
    assert cues == [
        {"id": "asr-0", "start": 10.2, "end": 11.4, "text": "hello"},
        {"id": "asr-1", "start": 11.5, "end": 12.3, "text": "world"},
    ]


def test_whisper_text_fallback(server):
    cues = server.whisper_payload_to_cues({"text": "Hello. World."}, start_time=5, duration_seconds=8)
    assert len(cues) == 2
    assert cues[0]["start"] == 5
    assert cues[0]["text"] == "Hello."
    assert cues[1]["text"] == "World."


def test_build_transcribe_payload(server):
    original = server.transcribe_audio_with_whisper

    def fake_transcribe(audio_bytes, mime_type, model, language):
        assert audio_bytes == b"audio"
        assert mime_type == "audio/webm"
        assert model == "tiny"
        assert language == "en"
        return {
            "language": "en",
            "segments": [{"start": 0, "end": 1.2, "text": "hello there"}],
        }

    server.transcribe_audio_with_whisper = fake_transcribe
    try:
        data_url = "data:audio/webm;base64," + base64.b64encode(b"audio").decode("ascii")
        payload = server.build_transcribe_payload(
            {
                "dataUrl": data_url,
                "mimeType": "audio/webm",
                "startTime": 42,
                "durationSeconds": 6,
                "language": "en",
                "model": "tiny",
            },
            transport="test",
        )
    finally:
        server.transcribe_audio_with_whisper = original

    assert payload["ok"] is True
    assert payload["engine"] == "whisper:tiny"
    assert payload["transport"] == "test"
    assert payload["sourceLanguage"] == "en"
    assert payload["cues"] == [{"id": "asr-0", "start": 42.0, "end": 43.2, "text": "hello there"}]


def test_ollama_failure_is_not_passthrough(server):
    original_translate = server.translate_cues_with_ollama

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    server.translate_cues_with_ollama = unavailable
    try:
        payload = server.build_dub_payload(
            {
                "targetLanguage": "zh-CN",
                "sourceLanguage": "en",
                "cues": [{"id": "1", "start": 0, "end": 2, "text": "Hello"}],
            },
            transport="test",
        )
    finally:
        server.translate_cues_with_ollama = original_translate

    assert payload["ok"] is False
    assert payload["code"] == "OLLAMA_UNAVAILABLE"
    assert "Hello" not in payload.get("error", "")


def test_build_video_transcribe_payload(server):
    original_download = server.download_youtube_audio_window
    original_transcribe = server.transcribe_audio_with_whisper

    def fake_download(video_url, start_time, duration_seconds):
        assert video_url == "https://www.youtube.com/watch?v=abc"
        assert start_time == 12
        assert duration_seconds == 30
        return b"window-audio", "audio/webm"

    def fake_transcribe(audio_bytes, mime_type, model, language):
        assert audio_bytes == b"window-audio"
        assert mime_type == "audio/webm"
        assert model == "base"
        assert language == "en"
        return {"language": "en", "segments": [{"start": 0.5, "end": 2, "text": "window text"}]}

    server.download_youtube_audio_window = fake_download
    server.transcribe_audio_with_whisper = fake_transcribe
    try:
        payload = server.build_video_transcribe_payload(
            {
                "videoUrl": "https://www.youtube.com/watch?v=abc",
                "startTime": 12,
                "durationSeconds": 30,
                "language": "en",
                "model": "base",
            },
            transport="test",
        )
        server.transcribe_audio_with_whisper = lambda *_args: {"language": "en", "segments": [], "text": ""}
        silence_payload = server.build_video_transcribe_payload(
            {
                "videoUrl": "https://www.youtube.com/watch?v=abc",
                "startTime": 12,
                "durationSeconds": 30,
            },
            transport="test",
        )
    finally:
        server.download_youtube_audio_window = original_download
        server.transcribe_audio_with_whisper = original_transcribe

    assert payload["ok"] is True
    assert payload["engine"] == "yt-dlp+whisper:base"
    assert payload["windowStart"] == 12
    assert payload["windowEnd"] == 42
    assert payload["silence"] is False
    assert payload["cues"] == [{"id": "asr-0", "start": 12.5, "end": 14.0, "text": "window text"}]
    assert silence_payload["ok"] is True
    assert silence_payload["silence"] is True
    assert silence_payload["cues"] == []
    assert server.build_video_transcribe_payload({"videoUrl": "https://example.com/video"}, "test")["ok"] is False


def test_ytdlp_audio_window_command(server):
    command = server.build_ytdlp_audio_window_command(
        ["yt-dlp"],
        "https://www.youtube.com/watch?v=abc",
        12.5,
        30,
        Path("/tmp/window"),
        "chrome",
    )
    assert command[0] == "yt-dlp"
    assert command[command.index("--download-sections") + 1] == "*12.500-42.500"
    assert command[command.index("-f") + 1] == "bestaudio/best"
    assert command[command.index("--cookies-from-browser") + 1] == "chrome"
    assert command[-1] == "https://www.youtube.com/watch?v=abc"


def test_ytdlp_full_audio_command(server):
    command = server.build_ytdlp_full_audio_command(
        ["yt-dlp"],
        "https://www.youtube.com/watch?v=abc",
        Path("/tmp/full"),
        "chrome",
    )
    assert command[0] == "yt-dlp"
    assert command[command.index("-f") + 1] == "bestaudio[abr<=96]/bestaudio/best"
    assert command[command.index("-o") + 1] == "/tmp/full/full-audio.%(ext)s"
    assert "--download-sections" not in command
    assert command[command.index("--cookies-from-browser") + 1] == "chrome"
    assert command[-1] == "https://www.youtube.com/watch?v=abc"


def test_full_transcript_job_worker(server):
    original_download = server.download_youtube_full_audio
    original_transcribe = server.transcribe_audio_path_with_whisper
    server.FULL_TRANSCRIPT_JOBS.clear()
    server.FULL_TRANSCRIPT_CANCEL_EVENTS.clear()
    job_id = "full-test"
    now = 1000.0
    server.FULL_TRANSCRIPT_JOBS[job_id] = {
        "id": job_id,
        "key": "video|en|base",
        "videoId": "video",
        "videoUrl": "https://www.youtube.com/watch?v=video",
        "durationSeconds": 60,
        "language": "en",
        "model": "base",
        "status": "queued",
        "stage": "queued",
        "progress": 1,
        "createdAt": now,
        "updatedAt": now,
        "sourceLanguage": "auto",
        "cues": [],
        "error": "",
    }

    def fake_download(video_url, output_dir, cancel_event):
        assert video_url.endswith("v=video")
        path = output_dir / "full-audio.webm"
        path.write_bytes(b"audio")
        return path

    def fake_transcribe(audio_path, output_dir, model, language, timeout, cancel_event):
        assert audio_path.read_bytes() == b"audio"
        assert model == "base"
        assert language == "en"
        return {"language": "en", "segments": [{"start": 1, "end": 2.5, "text": "hello"}]}

    server.download_youtube_full_audio = fake_download
    server.transcribe_audio_path_with_whisper = fake_transcribe
    try:
        server.run_full_transcript_job(job_id, server.threading.Event())
    finally:
        server.download_youtube_full_audio = original_download
        server.transcribe_audio_path_with_whisper = original_transcribe

    result = server.get_full_transcript_job(job_id)
    assert result["ok"] is True
    assert result["job"]["status"] == "completed"
    assert result["job"]["progress"] == 100
    assert result["job"]["sourceLanguage"] == "en"
    assert result["job"]["cues"] == [{"id": "asr-0", "start": 1.0, "end": 2.5, "text": "hello"}]
    assert "videoUrl" not in result["job"]
    assert "key" not in result["job"]

    server.FULL_TRANSCRIPT_CANCEL_EVENTS[job_id] = server.threading.Event()
    cancelled = server.cancel_full_transcript_job(job_id)
    assert cancelled["ok"] is True
    assert cancelled["job"]["status"] == "completed"
    server.FULL_TRANSCRIPT_JOBS.clear()
    server.FULL_TRANSCRIPT_CANCEL_EVENTS.clear()


def test_full_transcript_job_validation(server):
    invalid_url = server.start_full_transcript_job(
        {"videoUrl": "https://example.com/video", "durationSeconds": 30}
    )
    assert invalid_url["code"] == "INVALID_VIDEO_URL"
    invalid_duration = server.start_full_transcript_job(
        {"videoUrl": "https://www.youtube.com/watch?v=test", "durationSeconds": server.FULL_TRANSCRIPT_MAX_SECONDS + 1}
    )
    assert invalid_duration["code"] == "INVALID_VIDEO_DURATION"

    server.FULL_TRANSCRIPT_JOBS.clear()
    server.FULL_TRANSCRIPT_JOBS["busy"] = {
        "id": "busy",
        "key": "different|en|base",
        "status": "transcribing",
        "updatedAt": server.time.time(),
    }
    busy = server.start_full_transcript_job(
        {"videoUrl": "https://www.youtube.com/watch?v=test", "durationSeconds": 30, "language": "en"}
    )
    assert busy["code"] == "FULL_TRANSCRIPT_BUSY"
    server.FULL_TRANSCRIPT_JOBS.clear()


def test_build_tts_payload(server):
    original_tts = server.synthesize_speech_with_system

    def fake_tts(text, language, rate, voice, target_duration, max_fit_rate, tts_engine="system"):
        assert text == "你好"
        assert language == "zh-CN"
        assert rate == 1
        assert voice == "Meijia"
        assert target_duration == 2.4
        assert max_fit_rate == 1.2
        assert tts_engine == "edge"
        return {
            "engine": "edge:zh-CN-XiaoxiaoNeural",
            "ttsEngine": "edge",
            "mimeType": "audio/wav",
            "dataUrl": "data:audio/wav;base64,AAAA",
            "duration": 2.35,
            "fitRate": 1.2,
            "leadingTrimSeconds": 0.135,
        }

    server.synthesize_speech_with_system = fake_tts
    try:
        payload = server.build_tts_payload(
            {
                "text": "你好",
                "language": "zh-CN",
                "rate": 1,
                "voice": "Meijia",
                "targetDuration": 2.4,
                "maxFitRate": 1.2,
                "ttsEngine": "edge",
            },
            transport="test",
        )
    finally:
        server.synthesize_speech_with_system = original_tts

    assert payload["ok"] is True
    assert payload["engine"] == "edge:zh-CN-XiaoxiaoNeural"
    assert payload["ttsEngine"] == "edge"
    assert payload["transport"] == "test"
    assert payload["mimeType"] == "audio/wav"
    assert payload["dataUrl"].startswith("data:audio/wav;base64,")
    assert payload["duration"] == 2.35
    assert payload["fitRate"] == 1.2
    assert payload["leadingTrimSeconds"] == 0.135

    invalid = server.build_tts_payload(
        {"text": "你好", "rate": "fast", "targetDuration": "soon"},
        transport="test",
    )
    assert invalid == {"ok": False, "error": "Invalid TTS rate or target duration"}


def test_tts_duration_helpers(server):
    with tempfile.TemporaryDirectory() as temp_dir_name:
        path = Path(temp_dir_name) / "test.wav"
        import wave

        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(16000)
            audio_file.writeframes(b"\0\0" * 24000)
        assert abs(server.validate_wav_duration(path) - 1.5) < 0.001

    assert server.build_atempo_filter(1.5) == "atempo=1.500000"
    assert server.build_atempo_filter(3) == "atempo=2.000000,atempo=1.500000"
    assert 1 < server.estimate_tts_request_rate("这是一条需要匹配时间的字幕。", "zh-CN", 1, 1.2) <= 1.8


def test_trim_wav_leading_silence(server):
    import array
    import wave

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        source_path = temp_dir / "edge.wav"
        samples = array.array("h", ([0] * 160) + ([4000] * 300))
        with wave.open(str(source_path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(1000)
            audio_file.writeframes(samples.tobytes())

        trimmed_path, trimmed_seconds = server.trim_wav_leading_silence(source_path, temp_dir)
        assert trimmed_path != source_path
        assert 0.12 <= trimmed_seconds <= 0.13
        assert abs(server.validate_wav_duration(trimmed_path) - (0.46 - trimmed_seconds)) < 0.002
        with wave.open(str(trimmed_path), "rb") as audio_file:
            output_samples = array.array("h", audio_file.readframes(audio_file.getnframes()))
        assert output_samples.index(4000) in range(30, 41)

        short_source_path = temp_dir / "short-edge.wav"
        short_samples = array.array("h", ([0] * 30) + ([4000] * 100))
        with wave.open(str(short_source_path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(1000)
            audio_file.writeframes(short_samples.tobytes())
        unchanged_path, unchanged_seconds = server.trim_wav_leading_silence(short_source_path, temp_dir)
        assert unchanged_path == short_source_path
        assert unchanged_seconds == 0


def test_system_voice_discovery(server):
    parsed = server.parse_system_voice_output(
        "\n".join(
            [
                "Samantha           en_US    # Hello! My name is Samantha.",
                "Bad News           en_US    # Hello! My name is Bad News.",
                "Eddy (中文（中国大陆）)     zh_CN    # 你好！我叫Eddy。",
                "Meijia             zh_TW    # 你好，我叫美佳。",
                "invalid row",
            ]
        )
    )
    assert [voice["id"] for voice in parsed] == ["Samantha", "Bad News", "Eddy (中文（中国大陆）)", "Meijia"]
    assert parsed[1]["language"] == "en-US"
    assert parsed[2]["language"] == "zh-CN"

    original_voices = server.available_system_voices
    original_edge_available = server.edge_tts_available
    server.available_system_voices = lambda: parsed
    server.edge_tts_available = lambda: True
    try:
        assert server.pick_system_voice("en-US", "Bad News") == "Bad News"
        assert server.pick_system_voice("zh-TW", "auto") == "Meijia"
        assert server.pick_system_voice("zh-CN", "missing") == "Eddy (中文（中国大陆）)"
        payload = server.build_voices_payload("test")
    finally:
        server.available_system_voices = original_voices
        server.edge_tts_available = original_edge_available
    assert payload["ok"] is True
    assert payload["transport"] == "test"
    assert len([voice for voice in payload["voices"] if voice["provider"] == "system"]) == 4
    assert any(voice["id"] == "zh-CN-XiaoxiaoNeural" and voice["provider"] == "edge" for voice in payload["voices"])
    assert payload["edgeTts"] is True
    assert server.pick_edge_voice("zh-CN", "auto") == "zh-CN-XiaoxiaoNeural"
    assert server.pick_edge_voice("zh-TW", "auto") == "zh-TW-HsiaoChenNeural"
    assert server.edge_tts_rate_argument(1.08) == "+8%"


def write_test_wav(path, frame_count, sample_value=1000, sample_rate=1000):
    import struct
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio_file:
        audio_file.setnchannels(1)
        audio_file.setsampwidth(2)
        audio_file.setframerate(sample_rate)
        audio_file.writeframes(struct.pack("<h", sample_value) * frame_count)


def test_dub_track_wav_layout(server):
    import struct
    import wave

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        first = temp_dir / "first.wav"
        second = temp_dir / "second.wav"
        output = temp_dir / "track.wav"
        write_test_wav(first, 300, 1000)
        write_test_wav(second, 300, 2000)
        result = server.write_dub_track_wav(
            [
                {"start": 0.5, "end": 0.6, "path": first},
                {"start": 1.0, "end": 1.2, "path": second},
            ],
            output,
            1.5,
        )
        assert result["duration"] == 1.5
        with wave.open(str(output), "rb") as audio_file:
            assert audio_file.getnframes() == 1500
            samples = struct.unpack("<" + "h" * 1500, audio_file.readframes(1500))
        assert set(samples[:500]) == {0}
        assert set(samples[500:600]) == {1000}
        assert set(samples[600:1000]) == {0}
        assert set(samples[1000:1200]) == {2000}
        assert set(samples[1200:]) == {0}


def test_dub_track_audio_mix(server):
    import struct
    import wave

    ffmpeg = server.find_ffmpeg_command()
    if not ffmpeg:
        return
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        original = temp_dir / "original.wav"
        voice_clip = temp_dir / "voice.wav"
        voice_track = temp_dir / "voice-track.wav"
        mixed = temp_dir / "mixed.wav"
        sample_rate = 22050
        write_test_wav(original, sample_rate * 2, 1000, sample_rate)
        write_test_wav(voice_clip, round(sample_rate * 0.4), 4000, sample_rate)
        server.write_dub_track_wav(
            [{"start": 0.5, "end": 0.9, "path": voice_clip}],
            voice_track,
            2,
        )
        command = server.build_ffmpeg_dub_mix_command(ffmpeg, original, voice_track, mixed, 0.25, 2)
        assert "amix=inputs=2" in command[command.index("-filter_complex") + 1]
        assert command[command.index("-t") + 1] == "2.000"
        result = server.mix_dub_track_with_original(original, voice_track, mixed, 0.25, 2)
        assert abs(result["duration"] - 2) < 0.01
        with wave.open(str(mixed), "rb") as audio_file:
            assert audio_file.getframerate() == sample_rate
            assert audio_file.getnchannels() == 1
            samples = struct.unpack("<" + "h" * audio_file.getnframes(), audio_file.readframes(audio_file.getnframes()))
        background_level = sum(abs(value) for value in samples[: round(sample_rate * 0.3)]) / round(sample_rate * 0.3)
        voice_level = sum(abs(value) for value in samples[round(sample_rate * 0.6) : round(sample_rate * 0.8)]) / round(
            sample_rate * 0.2
        )
        assert 150 <= background_level <= 350
        assert voice_level > background_level + 2500


def test_dub_track_m4a_encoding(server):
    ffmpeg = server.find_ffmpeg_command()
    if not ffmpeg:
        return
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        source = temp_dir / "source.wav"
        output = temp_dir / "track.m4a"
        sample_rate = 22050
        write_test_wav(source, sample_rate * 3, 1200, sample_rate)
        command = server.build_ffmpeg_m4a_command(ffmpeg, source, output, 3)
        assert command[command.index("-c:a") + 1] == "aac"
        assert command[command.index("-b:a") + 1] == "96k"
        assert command[command.index("-f") + 1] == "ipod"
        result = server.encode_dub_track_m4a(source, output, 3)
        assert result["format"] == "m4a"
        assert abs(result["duration"] - 3) < 0.01
        assert output.is_file()
        assert output.stat().st_size < source.stat().st_size
        assert server.mime_type_for_audio_path(output) == "audio/mp4"


def test_dub_track_job_worker(server):
    original_synthesize = server.synthesize_speech_to_wav_file
    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        output_path = temp_dir / "rendered.wav"
        job_id = "dub-test"
        server.DUB_TRACK_JOBS[job_id] = {
            "id": job_id,
            "key": "private-hash",
            "videoId": "video",
            "durationSeconds": 2,
            "language": "zh-CN",
            "voice": "Tingting",
            "rate": 1,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": 1000,
            "updatedAt": 1000,
            "cueCount": 2,
            "cues": [
                {"start": 0.2, "end": 0.8, "text": "第一条"},
                {"start": 1.0, "end": 1.6, "text": "第二条"},
            ],
            "filename": "LocalTube-Dub-video-zh-CN-dub.wav",
            "filePath": str(output_path),
            "error": "",
        }

        def fake_synthesize(text, language, rate, voice, target_duration, output_dir, max_fit_rate=3, cancel_event=None, tts_engine="system"):
            path = output_dir / "voice.wav"
            write_test_wav(path, 500, 1000)
            return {"path": path, "duration": 0.5, "fitRate": 1, "engine": "test"}

        server.synthesize_speech_to_wav_file = fake_synthesize
        try:
            server.run_dub_track_job(job_id, server.threading.Event())
        finally:
            server.synthesize_speech_to_wav_file = original_synthesize

        result = server.get_dub_track_job(job_id)
        assert result["ok"] is True
        assert result["job"]["status"] == "completed", result
        assert result["job"]["progress"] == 100
        assert result["job"]["downloadUrl"].endswith(f"id={job_id}")
        assert "filePath" not in result["job"]
        assert "cues" not in result["job"]
        assert "key" not in result["job"]
        assert output_path.is_file()
        assert abs(server.validate_wav_duration(output_path) - 2) < 0.001

    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()


def test_dub_track_parallel_synthesis(server):
    original_synthesize = server.synthesize_speech_to_wav_file
    original_workers = server.DUB_TRACK_TTS_WORKERS
    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        output_path = temp_dir / "parallel.wav"
        job_id = "parallel-dub-test"
        cues = [
            {"start": index * 0.6, "end": index * 0.6 + 0.5, "text": f"第 {index + 1} 条"}
            for index in range(6)
        ]
        server.DUB_TRACK_JOBS[job_id] = {
            "id": job_id,
            "key": "parallel-hash",
            "videoId": "video",
            "durationSeconds": 4,
            "language": "zh-CN",
            "voice": "Tingting",
            "rate": 1,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": 1000,
            "updatedAt": 1000,
            "cueCount": len(cues),
            "cues": cues,
            "filename": "LocalTube-Dub-parallel.wav",
            "filePath": str(output_path),
            "error": "",
        }
        lock = server.threading.Lock()
        active = 0
        peak_active = 0

        def fake_synthesize(text, language, rate, voice, target_duration, output_dir, max_fit_rate=3, cancel_event=None, tts_engine="system"):
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                server.time.sleep(0.05)
                path = output_dir / "voice.wav"
                write_test_wav(path, 400, 1000)
                return {"path": path, "duration": 0.4, "fitRate": 1, "engine": "test"}
            finally:
                with lock:
                    active -= 1

        server.DUB_TRACK_TTS_WORKERS = 3
        server.synthesize_speech_to_wav_file = fake_synthesize
        try:
            server.run_dub_track_job(job_id, server.threading.Event())
        finally:
            server.synthesize_speech_to_wav_file = original_synthesize
            server.DUB_TRACK_TTS_WORKERS = original_workers

        result = server.get_dub_track_job(job_id)
        assert result["job"]["status"] == "completed", result
        assert result["job"]["synthesisWorkers"] == 3
        assert result["job"]["renderedCues"] == len(cues)
        assert peak_active >= 2
        assert output_path.is_file()
        assert abs(server.validate_wav_duration(output_path) - 4) < 0.001

    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()


def test_dub_track_parallel_cancellation(server):
    original_synthesize = server.synthesize_speech_to_wav_file
    original_workers = server.DUB_TRACK_TTS_WORKERS
    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        output_path = Path(temp_dir_name) / "cancelled.wav"
        job_id = "parallel-cancel-test"
        cues = [
            {"start": index * 0.6, "end": index * 0.6 + 0.5, "text": f"第 {index + 1} 条"}
            for index in range(6)
        ]
        server.DUB_TRACK_JOBS[job_id] = {
            "id": job_id,
            "key": "cancel-hash",
            "videoId": "video",
            "durationSeconds": 4,
            "language": "zh-CN",
            "voice": "Tingting",
            "rate": 1,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": 1000,
            "updatedAt": 1000,
            "cueCount": len(cues),
            "cues": cues,
            "filename": "cancelled.wav",
            "filePath": str(output_path),
            "error": "",
        }
        cancel_event = server.threading.Event()

        def cancellable_synthesize(text, language, rate, voice, target_duration, output_dir, max_fit_rate=3, cancel_event=None, tts_engine="system"):
            for _ in range(100):
                if cancel_event and cancel_event.is_set():
                    raise server.FullTranscriptCancelled("任务已取消")
                server.time.sleep(0.005)
            path = output_dir / "voice.wav"
            write_test_wav(path, 400, 1000)
            return {"path": path, "duration": 0.4, "fitRate": 1, "engine": "test"}

        server.DUB_TRACK_TTS_WORKERS = 3
        server.synthesize_speech_to_wav_file = cancellable_synthesize
        worker = server.threading.Thread(target=server.run_dub_track_job, args=(job_id, cancel_event))
        try:
            worker.start()
            server.time.sleep(0.04)
            cancel_event.set()
            worker.join(timeout=2)
        finally:
            server.synthesize_speech_to_wav_file = original_synthesize
            server.DUB_TRACK_TTS_WORKERS = original_workers

        assert not worker.is_alive()
        result = server.get_dub_track_job(job_id)
        assert result["job"]["status"] == "cancelled", result
        assert not output_path.exists()

    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()


def test_m4a_dub_track_job_worker(server):
    if not server.find_ffmpeg_command():
        return
    original_synthesize = server.synthesize_speech_to_wav_file
    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        output_path = temp_dir / "rendered.m4a"
        job_id = "m4a-dub-test"
        server.DUB_TRACK_JOBS[job_id] = {
            "id": job_id,
            "key": "private-m4a-hash",
            "videoId": "video",
            "durationSeconds": 2,
            "language": "zh-CN",
            "voice": "Tingting",
            "rate": 1,
            "mixOriginal": False,
            "originalVolume": 0,
            "outputFormat": "m4a",
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": 1000,
            "updatedAt": 1000,
            "cueCount": 1,
            "cues": [{"start": 0.2, "end": 1.2, "text": "压缩音轨"}],
            "filename": "LocalTube-Dub-video-zh-CN-dub.m4a",
            "filePath": str(output_path),
            "error": "",
        }

        def fake_synthesize(text, language, rate, voice, target_duration, output_dir, max_fit_rate=3, cancel_event=None, tts_engine="system"):
            path = output_dir / "voice.wav"
            write_test_wav(path, 11025, 1200, 22050)
            return {"path": path, "duration": 0.5, "fitRate": 1, "engine": "test"}

        server.synthesize_speech_to_wav_file = fake_synthesize
        try:
            server.run_dub_track_job(job_id, server.threading.Event())
        finally:
            server.synthesize_speech_to_wav_file = original_synthesize

        result = server.get_dub_track_job(job_id)
        assert result["job"]["status"] == "completed", result
        assert result["job"]["outputFormat"] == "m4a"
        assert result["job"]["filename"].endswith(".m4a")
        assert output_path.is_file()
        assert abs(server.probe_audio_duration(output_path) - 2) < 0.01

    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()


def test_mixed_dub_track_job_worker(server):
    original_synthesize = server.synthesize_speech_to_wav_file
    original_download = server.download_youtube_full_audio
    original_mix = server.mix_dub_track_with_original
    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        output_path = temp_dir / "mixed.wav"
        job_id = "mixed-dub-test"
        server.DUB_TRACK_JOBS[job_id] = {
            "id": job_id,
            "key": "private-mixed-hash",
            "videoId": "video",
            "videoUrl": "https://www.youtube.com/watch?v=video",
            "durationSeconds": 2,
            "language": "zh-CN",
            "voice": "Tingting",
            "rate": 1,
            "mixOriginal": True,
            "originalVolume": 0.2,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": 1000,
            "updatedAt": 1000,
            "cueCount": 1,
            "cues": [{"start": 0.2, "end": 0.8, "text": "第一条"}],
            "filename": "LocalTube-Dub-video-zh-CN-mixed.wav",
            "filePath": str(output_path),
            "error": "",
        }

        def fake_synthesize(text, language, rate, voice, target_duration, output_dir, max_fit_rate=3, cancel_event=None, tts_engine="system"):
            path = output_dir / "voice.wav"
            write_test_wav(path, 500, 1000)
            return {"path": path, "duration": 0.5, "fitRate": 1, "engine": "test"}

        def fake_download(video_url, output_dir, cancel_event):
            assert video_url.endswith("v=video")
            path = output_dir / "full-audio.wav"
            write_test_wav(path, 2000, 400)
            return path

        def fake_mix(original_path, voice_path, mixed_path, original_volume, duration_seconds, cancel_event):
            assert original_path.is_file()
            assert voice_path.is_file()
            assert original_volume == 0.2
            assert duration_seconds == 2
            mixed_path.write_bytes(voice_path.read_bytes())
            return {"path": mixed_path, "duration": 2, "originalVolume": original_volume}

        server.synthesize_speech_to_wav_file = fake_synthesize
        server.download_youtube_full_audio = fake_download
        server.mix_dub_track_with_original = fake_mix
        try:
            server.run_dub_track_job(job_id, server.threading.Event())
        finally:
            server.synthesize_speech_to_wav_file = original_synthesize
            server.download_youtube_full_audio = original_download
            server.mix_dub_track_with_original = original_mix

        result = server.get_dub_track_job(job_id)
        assert result["job"]["status"] == "completed", result
        assert result["job"]["mixOriginal"] is True
        assert result["job"]["originalVolume"] == 0.2
        assert "videoUrl" not in result["job"]
        assert output_path.is_file()

    server.DUB_TRACK_JOBS.clear()
    server.DUB_TRACK_CANCEL_EVENTS.clear()


def test_dub_track_validation(server):
    missing = server.start_dub_track_job({"cues": []})
    assert missing["code"] == "INVALID_DUB_TRACK_CUES"
    normalized = server.normalize_dub_track_cues(
        [{"start": 2, "end": 3, "text": "source", "translatedText": "translated"}, {"start": "bad", "text": "skip"}]
    )
    assert normalized == [{"start": 2.0, "end": 3.0, "text": "translated"}]
    invalid_mix = server.start_dub_track_job(
        {"cues": [{"start": 0, "end": 1, "text": "test"}], "durationSeconds": 1, "mixOriginal": True}
    )
    assert invalid_mix["code"] == "INVALID_DUB_TRACK_VIDEO_URL"
    voice_key = server.dub_track_job_key(normalized, "zh-CN", "auto", 1)
    mixed_key = server.dub_track_job_key(
        normalized,
        "zh-CN",
        "auto",
        1,
        mix_original=True,
        original_volume=0.25,
        video_url="https://www.youtube.com/watch?v=abc",
    )
    assert voice_key != mixed_key
    m4a_key = server.dub_track_job_key(normalized, "zh-CN", "auto", 1, output_format="m4a")
    assert voice_key != m4a_key
    invalid_format = server.start_dub_track_job(
        {
            "cues": [{"start": 0, "end": 1, "text": "test"}],
            "durationSeconds": 1,
            "outputFormat": "mp3",
        }
    )
    assert invalid_format["code"] == "INVALID_DUB_TRACK_FORMAT"


def test_caption_parsers(server):
    xml_cues = server.parse_caption_text(
        '<transcript><text start="1.2" dur="2">Hello &amp;#39;caption&amp;#39;</text></transcript>'
    )
    assert xml_cues == [{"id": "0", "start": 1.2, "end": 3.2, "text": "Hello 'caption'"}]

    vtt_cues = server.parse_caption_text("WEBVTT\n\n00:00:04.000 --> 00:00:06.000\n<v Roger>Hello VTT</v>")
    assert vtt_cues == [{"id": "1", "start": 4.0, "end": 6.0, "text": "Hello VTT"}]

    json_cues = server.parse_caption_text(
        '{"events":[{"tStartMs":7000,"dDurationMs":1500,"segs":[{"utf8":"Hello"},{"utf8":" json3"}]}]}'
    )
    assert json_cues == [{"id": "0", "start": 7.0, "end": 8.5, "text": "Hello json3"}]

    ttml_cues = server.parse_caption_text(
        '<tt><body><div><p begin="00:00:07.500" end="00:00:09.000"><span>TTML</span> caption</p></div></body></tt>'
    )
    assert ttml_cues == [{"id": "0", "start": 7.5, "end": 9.0, "text": "TTML caption"}]


def test_build_captions_payload(server):
    original_extract = server.extract_youtube_captions

    def fake_extract(video_url, source_language, target_language=""):
        assert video_url == "https://www.youtube.com/watch?v=abc123"
        assert source_language == "auto"
        assert target_language == "zh-CN"
        return {
            "engine": "yt-dlp",
            "source": "automatic_captions",
            "sourceLanguage": "en",
            "cues": [{"id": "0", "start": 0, "end": 1.5, "text": "hello"}],
        }

    server.extract_youtube_captions = fake_extract
    try:
        payload = server.build_captions_payload(
            {"videoId": "abc123", "sourceLanguage": "auto", "targetLanguage": "zh-CN"},
            transport="test"
        )
    finally:
        server.extract_youtube_captions = original_extract

    assert payload["ok"] is True
    assert payload["engine"] == "yt-dlp"
    assert payload["transport"] == "test"
    assert payload["sourceLanguage"] == "en"
    assert payload["cues"] == [{"id": "0", "start": 0, "end": 1.5, "text": "hello"}]


def test_caption_cache_and_ytdlp_command(server):
    server.CAPTION_CACHE.clear()
    original_extract = server.extract_youtube_captions

    calls = []

    def fake_extract(video_url, source_language, target_language=""):
        calls.append((video_url, source_language, target_language))
        return {
            "engine": "yt-dlp",
            "source": "automatic_captions",
            "sourceLanguage": "en",
            "cues": [{"id": "0", "start": 0, "end": 1.5, "text": "cached"}],
        }

    server.extract_youtube_captions = fake_extract
    try:
        request = {"videoId": "cached123", "sourceLanguage": "auto", "targetLanguage": "zh-CN"}
        first = server.build_captions_payload(request, transport="test")
        second = server.build_captions_payload(request, transport="test")
    finally:
        server.extract_youtube_captions = original_extract
        server.CAPTION_CACHE.clear()

    assert len(calls) == 1
    assert calls[0][2] == "zh-CN"
    assert "cache" not in first
    assert second["cache"] is True
    assert second["cues"][0]["text"] == "cached"

    command = server.build_ytdlp_metadata_command(["/usr/bin/yt-dlp"], "https://www.youtube.com/watch?v=abc")
    assert "--cookies-from-browser" in command
    assert "chrome" in command
    fast_command = server.build_ytdlp_metadata_command_with_cookies(["/usr/bin/yt-dlp"], "https://www.youtube.com/watch?v=abc", "")
    assert "--no-playlist" in fast_command
    assert "--ignore-no-formats-error" in fast_command
    assert "--simulate" in fast_command
    assert "--write-auto-subs" in fast_command
    assert "--cookies-from-browser" not in fast_command
    targeted_command = server.build_ytdlp_metadata_command_with_cookies(
        ["/usr/bin/yt-dlp"],
        "https://www.youtube.com/watch?v=abc",
        "",
        "auto",
        "zh-CN",
    )
    assert "--sub-langs" in targeted_command
    assert any("zh-Hans.*" in argument for argument in targeted_command)
    assert not any("zh.*" in argument for argument in targeted_command)
    assert server.CAPTION_CACHE_SECONDS >= 3600
    assert server.CAPTION_CACHE_MAX_ENTRIES <= 24

    discovered = server.find_ytdlp_command()
    assert discovered


def test_caption_singleflight(server):
    with server.CAPTION_CACHE_LOCK:
        server.CAPTION_CACHE.clear()
        server.CAPTION_FAILURE_CACHE.clear()
    with server.CAPTION_INFLIGHT_LOCK:
        server.CAPTION_INFLIGHT.clear()

    original_extract = server.extract_youtube_captions
    calls = []
    calls_lock = server.threading.Lock()
    start_barrier = server.threading.Barrier(4)
    results = []

    def fake_extract(video_url, source_language, target_language=""):
        with calls_lock:
            calls.append((video_url, source_language, target_language))
        server.time.sleep(0.08)
        return {
            "engine": "yt-dlp",
            "source": "automatic_captions",
            "sourceLanguage": "en",
            "cues": [{"id": "0", "start": 0, "end": 1.5, "text": "coalesced"}],
        }

    def worker():
        start_barrier.wait()
        results.append(
            server.build_captions_payload(
                {"videoId": "singleflight123", "sourceLanguage": "auto", "targetLanguage": "zh-CN"},
                transport="test",
            )
        )

    server.extract_youtube_captions = fake_extract
    threads = [server.threading.Thread(target=worker) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
    finally:
        server.extract_youtube_captions = original_extract
        with server.CAPTION_CACHE_LOCK:
            server.CAPTION_CACHE.clear()
            server.CAPTION_FAILURE_CACHE.clear()
        with server.CAPTION_INFLIGHT_LOCK:
            server.CAPTION_INFLIGHT.clear()

    assert all(not thread.is_alive() for thread in threads)
    assert len(calls) == 1
    assert len(results) == 4
    assert all(result["ok"] is True for result in results)
    assert sum(bool(result.get("coalesced")) for result in results) == 3


def test_ytdlp_429_error(server):
    message = server.read_ytdlp_error("ERROR: HTTP Error 429: Too Many Requests")
    assert "429" in message
    assert "限流" in message


def test_video_availability_metadata(server):
    assert server.metadata_video_unavailable(
        {"id": "gone", "title": "youtube video #gone", "availability": None, "formats": []}
    )
    assert server.metadata_video_unavailable(
        {"id": "private", "title": "Private video", "availability": "private", "formats": []}
    )
    assert not server.metadata_video_unavailable(
        {"id": "silent", "title": "10 seconds silence", "availability": "public", "formats": [{"url": "x"}]}
    )


def test_caption_download_timeout_returns_none(server):
    original_run = server.subprocess.run

    def timeout(*_args, **kwargs):
        raise server.subprocess.TimeoutExpired(cmd="yt-dlp", timeout=kwargs.get("timeout", 1))

    server.subprocess.run = timeout
    try:
        result = server.download_youtube_captions(
            ["yt-dlp"],
            "https://www.youtube.com/watch?v=abc",
            "auto",
            "zh-CN",
            "",
            metadata={"subtitles": {"en": []}},
            deadline=server.time.monotonic() + 2,
        )
    finally:
        server.subprocess.run = original_run

    assert result is None


def test_caption_error_classification(server):
    assert server.classify_caption_error("HTTP Error 429: Too Many Requests") == "YOUTUBE_RATE_LIMITED"
    assert server.caption_error_http_status("YOUTUBE_RATE_LIMITED") == 429
    assert server.classify_caption_error("yt-dlp 没有读取到可用字幕。") == "NO_PUBLIC_CAPTIONS"
    assert server.caption_error_http_status("NO_PUBLIC_CAPTIONS") == 404
    assert server.classify_caption_error("字幕轨道返回空内容 empty") == "CAPTION_EMPTY"
    assert server.classify_caption_error("VIDEO_UNAVAILABLE: Video unavailable") == "VIDEO_UNAVAILABLE"
    assert server.caption_error_http_status("VIDEO_UNAVAILABLE") == 422


def test_caption_failure_backoff_cache(server):
    server.CAPTION_CACHE.clear()
    server.CAPTION_FAILURE_CACHE.clear()
    original_extract = server.extract_youtube_captions
    calls = []

    def fake_extract(video_url, source_language, target_language=""):
        calls.append((video_url, source_language, target_language))
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    server.extract_youtube_captions = fake_extract
    try:
        request = {"videoId": "limited123", "sourceLanguage": "auto", "targetLanguage": "zh-CN"}
        first = server.build_captions_payload(request, transport="test")
        second = server.build_captions_payload(request, transport="test")
    finally:
        server.extract_youtube_captions = original_extract
        server.CAPTION_FAILURE_CACHE.clear()

    assert len(calls) == 1
    assert first["ok"] is False
    assert first["code"] == "YOUTUBE_RATE_LIMITED"
    assert second["cache"] is True
    assert second["retryAfterSeconds"] > 0


def test_caption_empty_failure_is_not_cached(server):
    server.CAPTION_CACHE.clear()
    server.CAPTION_FAILURE_CACHE.clear()
    original_extract = server.extract_youtube_captions
    calls = []

    def fake_extract(video_url, source_language, target_language=""):
        calls.append((video_url, source_language, target_language))
        raise RuntimeError("字幕 URL 返回空内容：youtube-translate/zh-CN/json3")

    server.extract_youtube_captions = fake_extract
    try:
        request = {"videoId": "empty123", "sourceLanguage": "auto", "targetLanguage": "zh-CN"}
        first = server.build_captions_payload(request, transport="test")
        second = server.build_captions_payload(request, transport="test")
    finally:
        server.extract_youtube_captions = original_extract
        server.CAPTION_FAILURE_CACHE.clear()

    assert len(calls) == 2
    assert first["code"] == "CAPTION_EMPTY"
    assert "cache" not in second


def test_ytdlp_retries_with_cookies_when_captions_are_hidden(server):
    original_find = server.find_ytdlp_command
    original_run = server.run_ytdlp_metadata
    original_fetch = server.fetch_caption_text
    original_download = server.download_youtube_captions
    original_cookie_mode = server.YTDLP_COOKIES_FROM_BROWSER
    calls = []
    download_calls = []

    def fake_run(command_prefix, video_url, cookies_browser, source_language="", target_language="", timeout=None):
        calls.append(cookies_browser)
        metadata = {"automatic_captions": {}, "subtitles": {}}
        if cookies_browser == "chrome":
            metadata = {
                "automatic_captions": {
                    "en": [{"url": "https://example.test/caption.json3", "ext": "json3"}]
                },
                "subtitles": {},
            }
        return server.subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=server.json.dumps(metadata),
            stderr="",
        )

    server.find_ytdlp_command = lambda: ["yt-dlp"]
    server.run_ytdlp_metadata = fake_run
    server.fetch_caption_text = lambda url, timeout=None: '{"events":[{"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"cookie caption"}]}]}'
    server.download_youtube_captions = lambda *args, **kwargs: download_calls.append((args, kwargs)) or None
    server.YTDLP_COOKIES_FROM_BROWSER = "auto"
    try:
        payload = server.extract_youtube_captions("https://www.youtube.com/watch?v=abc", "auto", "zh-CN")
    finally:
        server.find_ytdlp_command = original_find
        server.run_ytdlp_metadata = original_run
        server.fetch_caption_text = original_fetch
        server.download_youtube_captions = original_download
        server.YTDLP_COOKIES_FROM_BROWSER = original_cookie_mode

    assert calls == ["", "chrome"]
    assert download_calls == []
    assert payload["cues"][0]["text"] == "cookie caption"


def test_ytdlp_prefers_target_language(server):
    metadata = {
        "subtitles": {
            "en": [{"url": "https://example.test/en.vtt", "ext": "vtt"}]
        },
        "automatic_captions": {
            "zh-Hans": [{"url": "https://example.test/zh.vtt", "ext": "vtt"}]
        },
    }
    caption = server.select_caption_entry(metadata, "auto", "zh-CN")
    assert caption["sourceLanguage"] == "zh-Hans"
    assert not any(
        item.get("source") == "youtube-translate"
        for item in server.select_caption_candidates(metadata, "auto", "zh-CN")
    )
    selector = server.subtitle_language_selector("auto", "zh-CN")
    assert "zh-Hans.*" in selector
    assert "zh.*" not in selector
    assert "en" in selector
    assert "all" not in selector

    variant_metadata = {
        "subtitles": {
            "zh-Hant": [{"url": "https://example.test/zh-hant.vtt", "ext": "vtt"}],
            "zh-Hans": [{"url": "https://example.test/zh-hans.vtt", "ext": "vtt"}],
        },
        "automatic_captions": {},
    }
    simplified = server.select_caption_entry(variant_metadata, "auto", "zh-CN")
    traditional = server.select_caption_entry(variant_metadata, "auto", "zh-TW")
    assert simplified["sourceLanguage"] == "zh-Hans"
    assert traditional["sourceLanguage"] == "zh-Hant"


def test_ytdlp_recognizes_composite_translated_languages(server):
    assert server.normalize_caption_language_identity("zh-Hans-en") == "zh-hans"
    assert server.normalize_caption_language_identity("zh-Hant-en") == "zh-hant"
    assert server.normalize_caption_language_identity("pt-BR-en") == "pt-br"
    assert server.youtube_translated_caption_source_language("zh-Hans-en", "zh-CN") == "en"
    assert server.youtube_translated_caption_source_language("zh-Hans", "zh-CN") == ""
    assert server.is_youtube_translated_caption_language("zh-Hans-en", "zh-CN")

    metadata = {
        "subtitles": {
            "en": [{"url": "https://example.test/en.vtt", "ext": "vtt"}],
        },
        "automatic_captions": {
            "zh-Hans-en": [{"url": "https://example.test/zh-Hans-en.vtt", "ext": "vtt"}],
        },
    }
    caption = server.select_caption_entry(metadata, "auto", "zh-CN")
    assert caption["sourceLanguage"] == "zh-Hans-en"
    assert caption["translatedByYouTube"] == "true"
    assert caption["originalLanguage"] == "en"


def test_ytdlp_download_marks_composite_target_caption(server):
    original_run = server.subprocess.run

    def fake_run(command, **_kwargs):
        output_template = Path(command[command.index("-o") + 1])
        caption_path = output_template.parent / "abc.zh-Hans-en.json3"
        caption_path.write_text(
            '{"events":[{"tStartMs":0,"dDurationMs":1200,"segs":[{"utf8":"已经翻译的中文"}]}]}',
            encoding="utf-8",
        )
        return server.subprocess.CompletedProcess(command, 0, "", "")

    server.subprocess.run = fake_run
    try:
        payload = server.download_youtube_captions(
            ["yt-dlp"],
            "https://www.youtube.com/watch?v=abc",
            "auto",
            "zh-CN",
            "",
            metadata={"automatic_captions": {"zh-Hans-en": []}},
            deadline=server.time.monotonic() + 2,
        )
    finally:
        server.subprocess.run = original_run

    assert payload["sourceLanguage"] == "zh-Hans-en"
    assert payload["translatedByYouTube"] is True
    assert payload["cues"][0]["text"] == "已经翻译的中文"


def test_ytdlp_downloads_target_before_accepting_source(server):
    original_find = server.find_ytdlp_command
    original_run = server.run_ytdlp_metadata
    original_fetch = server.fetch_caption_text
    original_download = server.download_youtube_captions
    original_cookie_mode = server.YTDLP_COOKIES_FROM_BROWSER

    metadata = {
        "subtitles": {},
        "automatic_captions": {
            "zh-Hans": [{"url": "https://example.test/zh-Hans.vtt", "ext": "vtt"}],
            "en-orig": [{"url": "https://example.test/en-orig.vtt", "ext": "vtt"}],
        },
    }

    class Completed:
        returncode = 0
        stdout = json.dumps(metadata)
        stderr = ""

    requested_urls = []
    server.find_ytdlp_command = lambda: ["yt-dlp"]
    server.run_ytdlp_metadata = lambda *args, **kwargs: Completed()
    server.fetch_caption_text = lambda url, timeout=None: requested_urls.append(url) or ""
    server.download_youtube_captions = lambda *args, **kwargs: {
        "engine": "yt-dlp-download",
        "source": "yt-dlp-download",
        "sourceLanguage": "zh-Hans",
        "translatedByYouTube": True,
        "cues": [{"id": "0", "start": 0, "end": 1.2, "text": "下载到的中文"}],
    }
    server.YTDLP_COOKIES_FROM_BROWSER = "none"

    try:
        payload = server.extract_youtube_captions("https://www.youtube.com/watch?v=abc", "auto", "zh-CN")
    finally:
        server.find_ytdlp_command = original_find
        server.run_ytdlp_metadata = original_run
        server.fetch_caption_text = original_fetch
        server.download_youtube_captions = original_download
        server.YTDLP_COOKIES_FROM_BROWSER = original_cookie_mode

    assert requested_urls
    assert all("zh-Hans" in url for url in requested_urls)
    assert payload["sourceLanguage"] == "zh-Hans"
    assert payload["cues"][0]["text"] == "下载到的中文"


def test_ytdlp_builds_youtube_translated_caption(server):
    metadata = {
        "subtitles": {
            "en": [{"url": "https://example.test/api/timedtext?v=abc&lang=en&fmt=json3", "ext": "json3"}]
        },
        "automatic_captions": {},
    }
    caption = server.select_caption_entry(metadata, "auto", "zh-CN")
    assert caption["source"] == "youtube-translate"
    assert caption["sourceLanguage"] == "zh-CN"
    assert caption["translatedByYouTube"] == "true"
    assert "tlang=zh" in caption["url"]
    assert server.youtube_translation_languages("zh-CN") == ["zh", "zh-Hans", "zh-CN"]

    many_formats = {
        "subtitles": {
            "en": [
                {"url": f"https://example.test/api/timedtext?v=abc&lang=en&fmt={ext}", "ext": ext}
                for ext in ("json3", "srv1", "srv3", "vtt", "ttml")
            ]
        },
        "automatic_captions": {},
    }
    candidates = server.select_caption_candidates(many_formats, "auto", "zh-CN")
    translated = [item for item in candidates if item.get("translatedByYouTube") == "true"]
    assert [item["translationLanguage"] for item in translated] == ["zh", "zh-Hans", "zh-CN"]


def test_ytdlp_impersonation_args(server):
    original_impersonate = server.YTDLP_IMPERSONATE
    try:
        server.YTDLP_IMPERSONATE = "chrome"
        command = server.build_ytdlp_metadata_command_with_cookies(["yt-dlp"], "https://example.test/video", "")
        assert "--impersonate" in command
        assert "chrome" in command

        server.YTDLP_IMPERSONATE = "none"
        command = server.build_ytdlp_metadata_command_with_cookies(["yt-dlp"], "https://example.test/video", "")
        assert "--impersonate" not in command
    finally:
        server.YTDLP_IMPERSONATE = original_impersonate


def test_ytdlp_uses_translated_caption_without_ai(server):
    original_find = server.find_ytdlp_command
    original_run = server.run_ytdlp_metadata
    original_fetch = server.fetch_caption_text
    original_download = server.download_youtube_captions
    original_cookie_mode = server.YTDLP_COOKIES_FROM_BROWSER

    metadata = {
        "subtitles": {
            "en": [{"url": "https://example.test/api/timedtext?v=abc&lang=en&fmt=json3", "ext": "json3"}]
        },
        "automatic_captions": {},
    }

    class Completed:
        returncode = 0
        stdout = json.dumps(metadata)
        stderr = ""

    requested_urls = []
    server.find_ytdlp_command = lambda: ["yt-dlp"]
    server.run_ytdlp_metadata = lambda *args, **kwargs: Completed()
    server.fetch_caption_text = lambda url, timeout=None: requested_urls.append(url) or '{"events":[{"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"你好"}]}]}'
    server.download_youtube_captions = lambda *args, **kwargs: None
    server.YTDLP_COOKIES_FROM_BROWSER = "none"

    try:
        payload = server.extract_youtube_captions("https://www.youtube.com/watch?v=abc", "auto", "zh-CN")
    finally:
        server.find_ytdlp_command = original_find
        server.run_ytdlp_metadata = original_run
        server.fetch_caption_text = original_fetch
        server.download_youtube_captions = original_download
        server.YTDLP_COOKIES_FROM_BROWSER = original_cookie_mode

    assert payload["sourceLanguage"] == "zh-CN"
    assert payload["translatedByYouTube"] is True
    assert payload["cues"][0]["text"] == "你好"
    assert requested_urls and "tlang=zh" in requested_urls[0]


def test_ytdlp_falls_back_when_translated_caption_is_empty(server):
    original_find = server.find_ytdlp_command
    original_run = server.run_ytdlp_metadata
    original_fetch = server.fetch_caption_text
    original_download = server.download_youtube_captions
    original_cookie_mode = server.YTDLP_COOKIES_FROM_BROWSER

    metadata = {
        "subtitles": {
            "en": [{"url": "https://example.test/api/timedtext?v=abc&lang=en&fmt=json3", "ext": "json3"}]
        },
        "automatic_captions": {},
    }

    class Completed:
        returncode = 0
        stdout = json.dumps(metadata)
        stderr = ""

    requested_urls = []

    def fake_fetch(url, timeout=None):
        requested_urls.append(url)
        if "tlang=" in url:
            return ""
        return '{"events":[{"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"fallback source"}]}]}'

    server.find_ytdlp_command = lambda: ["yt-dlp"]
    server.run_ytdlp_metadata = lambda *args, **kwargs: Completed()
    server.fetch_caption_text = fake_fetch
    server.download_youtube_captions = lambda *args, **kwargs: None
    server.YTDLP_COOKIES_FROM_BROWSER = "none"

    try:
        payload = server.extract_youtube_captions("https://www.youtube.com/watch?v=abc", "auto", "zh-CN")
    finally:
        server.find_ytdlp_command = original_find
        server.run_ytdlp_metadata = original_run
        server.fetch_caption_text = original_fetch
        server.download_youtube_captions = original_download
        server.YTDLP_COOKIES_FROM_BROWSER = original_cookie_mode

    translated_languages = [
        server.urllib.parse.parse_qs(server.urllib.parse.urlsplit(url).query).get("tlang", [""])[0]
        for url in requested_urls[:3]
    ]
    assert translated_languages == ["zh", "zh-Hans", "zh-CN"]
    assert len(requested_urls) <= server.CAPTION_TARGET_URL_ATTEMPT_LIMIT + 1
    assert all("tlang=" in url for url in requested_urls[:-1])
    assert "tlang=" not in requested_urls[-1]
    assert payload["sourceLanguage"] == "en"
    assert payload["translatedByYouTube"] is False
    assert payload["cues"][0]["text"] == "fallback source"


def test_invalid_audio_payload(server):
    payload = server.build_transcribe_payload({"dataUrl": "not-a-data-url"}, transport="test")
    assert payload["ok"] is False
    assert "audio" in payload["error"].lower()


def test_whisper_cpp_json_normalization(server):
    payload = server.normalize_whisper_json(
        {
            "result": {"language": "en"},
            "transcription": [
                {
                    "timestamps": {"from": "00:00:00.200", "to": "00:00:01.400"},
                    "offsets": {"from": 200, "to": 1400},
                    "text": " hello ",
                },
                {
                    "timestamps": {"from": "00:00:01.500", "to": "00:00:02.300"},
                    "offsets": {"from": 1500, "to": 2300},
                    "text": "world",
                },
            ],
        }
    )
    assert payload["language"] == "en"
    assert payload["text"] == "hello world"
    assert payload["segments"] == [
        {"start": 0.2, "end": 1.4, "text": "hello"},
        {"start": 1.5, "end": 2.3, "text": "world"},
    ]


def test_whisper_cpp_command(server):
    original_command = server.WHISPER_CPP_COMMAND
    original_model = server.WHISPER_CPP_MODEL
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        model_path = temp_dir / "ggml-base.bin"
        model_path.write_bytes(b"model")
        server.WHISPER_CPP_COMMAND = "/usr/local/bin/whisper-cli"
        server.WHISPER_CPP_MODEL = model_path
        try:
            command = server.build_whisper_cpp_command(temp_dir / "input.wav", temp_dir, "en-US")
        finally:
            server.WHISPER_CPP_COMMAND = original_command
            server.WHISPER_CPP_MODEL = original_model

    assert command[0] == "/usr/local/bin/whisper-cli"
    assert "-oj" in command
    assert "-of" in command
    assert command[command.index("-l") + 1] == "en"


def test_ollama_translation_count_recovery(server):
    original_call = server.call_ollama
    responses = iter(
        [
            json.dumps(["一", "二", "三"], ensure_ascii=False),
            json.dumps(["一", "二"], ensure_ascii=False),
            json.dumps(["三", "四"], ensure_ascii=False),
        ]
    )
    server.call_ollama = lambda _prompt: next(responses)
    cues = [
        {"id": str(index), "start": index, "end": index + 1, "text": f"cue {index}"}
        for index in range(4)
    ]
    try:
        translated = server.translate_ollama_batch_with_recovery(cues, "Simplified Chinese", "en")
    finally:
        server.call_ollama = original_call

    assert translated == ["一", "二", "三", "四"]


def test_native_autostart_dispatch(native_host):
    original = native_host.install_engine_autostart
    native_host.install_engine_autostart = lambda: {"ok": True, "installed": True}
    try:
        assert native_host.handle_message({"type": "install-autostart"}) == {"ok": True, "installed": True}
        assert native_host.handle_message({"type": "repair-autostart"}) == {"ok": True, "installed": True}
    finally:
        native_host.install_engine_autostart = original


def test_native_restart_reuses_launchagent_engine(native_host):
    original_stop = native_host.stop_http_engine
    original_wait = native_host.wait_for_port_release
    original_health = native_host.http_engine_running
    original_launch = native_host.launch_http_engine
    launch_called = False

    def fail_launch():
        nonlocal launch_called
        launch_called = True
        raise AssertionError("Native Host must not launch a second Engine after launchd recovered it")

    native_host.stop_http_engine = lambda force=False: {"ok": True, "stopped": True}
    native_host.wait_for_port_release = lambda: None
    native_host.http_engine_running = lambda: True
    native_host.launch_http_engine = fail_launch
    try:
        result = native_host.restart_http_engine()
    finally:
        native_host.stop_http_engine = original_stop
        native_host.wait_for_port_release = original_wait
        native_host.http_engine_running = original_health
        native_host.launch_http_engine = original_launch

    assert result["ok"] is True
    assert result["managedByLaunchAgent"] is True
    assert launch_called is False


def test_native_autostart_installer(native_host):
    original_run = native_host.subprocess.run
    original_health = native_host.http_engine_running
    original_log_path = native_host.AUTOSTART_INSTALL_LOG_PATH
    with tempfile.TemporaryDirectory() as temp_dir_name:
        log_path = Path(temp_dir_name) / "autostart.log"

        def fake_run(command, **kwargs):
            assert command == [str(ROOT / "scripts" / "install_engine_autostart_macos.sh")]
            assert kwargs["cwd"] == str(ROOT)
            return native_host.subprocess.CompletedProcess(command, 0, "service ready\n", "")

        native_host.subprocess.run = fake_run
        native_host.http_engine_running = lambda: True
        native_host.AUTOSTART_INSTALL_LOG_PATH = log_path
        try:
            result = native_host.install_engine_autostart()
        finally:
            native_host.subprocess.run = original_run
            native_host.http_engine_running = original_health
            native_host.AUTOSTART_INSTALL_LOG_PATH = original_log_path

        assert result["ok"] is True
        assert result["installed"] is True
        assert result["healthy"] is True
        assert log_path.read_text(encoding="utf-8") == "service ready\n"


def main() -> None:
    server = load_server_module()
    native_host = load_native_host_module()
    test_data_url_decode(server)
    test_health_version_metadata(server)
    test_http_byte_ranges(server)
    test_whisper_segments_to_cues(server)
    test_whisper_text_fallback(server)
    test_build_transcribe_payload(server)
    test_ollama_failure_is_not_passthrough(server)
    test_build_video_transcribe_payload(server)
    test_ytdlp_audio_window_command(server)
    test_ytdlp_full_audio_command(server)
    test_full_transcript_job_worker(server)
    test_full_transcript_job_validation(server)
    test_build_tts_payload(server)
    test_tts_duration_helpers(server)
    test_trim_wav_leading_silence(server)
    test_system_voice_discovery(server)
    test_dub_track_wav_layout(server)
    test_dub_track_audio_mix(server)
    test_dub_track_m4a_encoding(server)
    test_dub_track_job_worker(server)
    test_dub_track_parallel_synthesis(server)
    test_dub_track_parallel_cancellation(server)
    test_m4a_dub_track_job_worker(server)
    test_mixed_dub_track_job_worker(server)
    test_dub_track_validation(server)
    test_caption_parsers(server)
    test_build_captions_payload(server)
    test_caption_cache_and_ytdlp_command(server)
    test_caption_singleflight(server)
    test_ytdlp_429_error(server)
    test_video_availability_metadata(server)
    test_caption_download_timeout_returns_none(server)
    test_caption_error_classification(server)
    test_caption_failure_backoff_cache(server)
    test_caption_empty_failure_is_not_cached(server)
    test_ytdlp_retries_with_cookies_when_captions_are_hidden(server)
    test_ytdlp_prefers_target_language(server)
    test_ytdlp_recognizes_composite_translated_languages(server)
    test_ytdlp_download_marks_composite_target_caption(server)
    test_ytdlp_downloads_target_before_accepting_source(server)
    test_ytdlp_builds_youtube_translated_caption(server)
    test_ytdlp_impersonation_args(server)
    test_ytdlp_uses_translated_caption_without_ai(server)
    test_ytdlp_falls_back_when_translated_caption_is_empty(server)
    test_invalid_audio_payload(server)
    test_whisper_cpp_json_normalization(server)
    test_whisper_cpp_command(server)
    test_ollama_translation_count_recovery(server)
    test_native_autostart_dispatch(native_host)
    test_native_restart_reuses_launchagent_engine(native_host)
    test_native_autostart_installer(native_host)
    print("local engine checks ok")


if __name__ == "__main__":
    main()
