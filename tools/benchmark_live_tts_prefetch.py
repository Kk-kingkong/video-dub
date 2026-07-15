#!/usr/bin/env python3
"""Measure the bounded live-TTS prefetch path against a running local Engine."""

import argparse
import base64
import io
import json
import time
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed


SAMPLES = [
    ("欢迎回来，我们继续观看。", 2.0),
    ("这段配音会提前生成。", 2.0),
    ("播放进度改变后也会重新对齐。", 2.4),
    ("短句结束后会等待下一段。", 2.2),
    ("较长的句子会自动调整语速。", 2.5),
    ("这样可以减少实时播放时的等待。", 2.6),
]


def wav_duration(data_url):
    encoded = data_url.split(",", 1)[1]
    with wave.open(io.BytesIO(base64.b64decode(encoded)), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def synthesize(base_url, index, sample):
    text, target_duration = sample
    body = json.dumps(
        {
            "text": text,
            "language": "zh-CN",
            "voice": "auto",
            "rate": 1,
            "targetDuration": target_duration,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tts",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = json.load(response)
    if not payload.get("ok") or not payload.get("dataUrl"):
        raise RuntimeError(payload.get("error") or "Engine did not return TTS audio")
    return {
        "sample": index + 1,
        "requestSeconds": round(time.monotonic() - started, 3),
        "audioSeconds": round(wav_duration(payload["dataUrl"]), 3),
        "fitRate": payload.get("fitRate"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--max-seconds", type=float, default=10.0)
    args = parser.parse_args()

    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(synthesize, args.url, index, sample) for index, sample in enumerate(SAMPLES)]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.monotonic() - started
    report = {
        "workers": 3,
        "segments": len(SAMPLES),
        "elapsedSeconds": round(elapsed, 3),
        "withinBudget": elapsed <= args.max_seconds,
        "results": sorted(results, key=lambda item: item["sample"]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["withinBudget"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
