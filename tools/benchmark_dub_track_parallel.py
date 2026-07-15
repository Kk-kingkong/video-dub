#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "server" / "local_dub_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("local_dub_server_benchmark", SERVER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("无法加载本地 Engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_render(server, workers: int, output_dir: Path, cues: list[dict[str, object]]) -> dict[str, object]:
    job_id = f"benchmark-{workers}"
    output_path = output_dir / f"workers-{workers}.wav"
    server.DUB_TRACK_JOBS[job_id] = {
        "id": job_id,
        "key": f"benchmark-{workers}",
        "videoId": "benchmark",
        "durationSeconds": 12,
        "language": "zh-CN",
        "voice": "Tingting",
        "rate": 1,
        "mixOriginal": False,
        "originalVolume": 0,
        "outputFormat": "wav",
        "status": "queued",
        "stage": "queued",
        "progress": 1,
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "cueCount": len(cues),
        "cues": cues,
        "filename": f"benchmark-{workers}.wav",
        "filePath": str(output_path),
        "error": "",
    }
    server.DUB_TRACK_TTS_WORKERS = workers
    started_at = time.monotonic()
    server.run_dub_track_job(job_id, server.threading.Event())
    elapsed = time.monotonic() - started_at
    result = server.get_dub_track_job(job_id)["job"]
    if result["status"] != "completed" or not output_path.is_file():
        raise RuntimeError(result.get("error") or f"{workers} 路渲染失败")
    return {
        "workers": workers,
        "seconds": round(elapsed, 3),
        "duration": round(server.validate_wav_duration(output_path), 3),
        "bytes": output_path.stat().st_size,
    }


def main() -> None:
    server = load_server_module()
    cues = [
        {
            "start": 0.2 + index * 1.25,
            "end": 1.25 + index * 1.25,
            "text": f"这是第{index + 1}个并行配音速度测试片段。",
        }
        for index in range(9)
    ]
    with tempfile.TemporaryDirectory(prefix="localtube-dub-benchmark-") as temp_dir_name:
        output_dir = Path(temp_dir_name)
        sequential = run_render(server, 1, output_dir, cues)
        parallel = run_render(server, 3, output_dir, cues)
    speedup = sequential["seconds"] / max(0.001, parallel["seconds"])
    print(json.dumps({"sequential": sequential, "parallel": parallel, "speedup": round(speedup, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
