"""Update only the pure-Python Edge speech client, outside the bundled runtime."""
from __future__ import annotations

import email.parser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile

INDEX_URL = "https://pypi.org/pypi/edge-tts/json"
CHECK_INTERVAL = 6 * 60 * 60
MAX_WHEEL = 2 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30
SMOKE_TIMEOUT = 30


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", value):
        raise ValueError("Only stable three-part Edge speech versions are supported")
    return tuple(map(int, value.split(".")))


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment or not (url == INDEX_URL or
            parsed.hostname == "files.pythonhosted.org" and parsed.path.startswith("/packages/"))):
        raise ValueError("Untrusted Edge speech update URL")


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def download(url, destination, limit):
    validate_url(url)
    # A child deadline also covers DNS and servers that trickle headers or bytes.
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--download", url, str(destination), str(limit)],
                   check=True, timeout=DOWNLOAD_TIMEOUT, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fetch(url, destination, limit):
    validate_url(url)
    opener = urllib.request.build_opener(TrustedRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "LocalTube-Dub-Speech-Updater", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=10) as response, Path(destination).open("wb") as output:
        validate_url(response.geturl())
        count = 0
        while chunk := response.read(65536):
            count += len(chunk)
            if count > limit:
                raise ValueError("Edge speech download exceeds size limit")
            output.write(chunk)


def bundled_version():
    try:
        return importlib.metadata.version("edge-tts")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def validate_wheel(path, record):
    if path.stat().st_size != record["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Edge speech wheel checksum mismatch")
    metadata_dir = f"edge_tts-{record['version']}.dist-info"
    with zipfile.ZipFile(path) as archive:
        names, expanded = set(), 0
        for member in archive.infolist():
            parts = PurePosixPath(member.filename).parts
            expanded += member.file_size
            if (not parts or parts[0] not in {"edge_tts", "edge_playback", metadata_dir} or ".." in parts
                    or "\\" in member.filename or member.filename in names or member.flag_bits & 1
                    or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or expanded > 8 * MAX_WHEEL or len(names) >= 512):
                raise ValueError("Unsupported Edge speech wheel contents")
            names.add(member.filename)
        if not {"edge_tts/__init__.py", "edge_tts/__main__.py", f"{metadata_dir}/METADATA"}.issubset(names):
            raise ValueError("Incomplete Edge speech wheel")
        metadata = email.parser.Parser().parsestr(archive.read(f"{metadata_dir}/METADATA").decode("utf-8"))
        if metadata["Name"] != "edge-tts" or metadata["Version"] != record["version"]:
            raise ValueError("Edge speech wheel identity mismatch")
        # pip is already bundled; fail closed if its requirement parser is unavailable.
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.specifiers import SpecifierSet
        if not SpecifierSet(metadata.get("Requires-Python", "")).contains(".".join(map(str, sys.version_info[:3]))):
            raise ValueError("Edge speech update requires a different Python version")
        for raw in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            if requirement.url or not requirement.specifier.contains(importlib.metadata.version(requirement.name)):
                raise ValueError("Edge speech update requires other dependency changes")


def wheel_command(path):
    return [sys.executable, "-I", "-c",
            "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('edge_tts',run_name='__main__')",
            str(path)]


class EdgeTtsUpdater:
    def __init__(self, root, helpers):
        self.root = Path(root)
        self.helpers = helpers
        self.directory = helpers.state_directory(root) / "edge-tts"
        self.worker = None
        self.thread_lock = threading.Lock()

    def enabled(self):
        return self.helpers.enabled(self.helpers.read_json(self.root / "release.json"))

    def read_state(self):
        state = self.helpers.read_json(self.directory / "state.json")
        checked = state.get("checkedAt", 0)
        if type(checked) not in (int, float) or not 0 <= checked <= time.time():
            state["checkedAt"] = 0
        return state

    def write_state(self, state):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.directory / f"state.{os.getpid()}.{threading.get_ident()}.tmp"
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, self.directory / "state.json")

    def path_for(self, record):
        version(record["version"])
        if not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValueError("Invalid Edge speech checksum")
        return self.directory / f"edge_tts-{record['version']}-{record['sha256']}.whl"

    def usable(self, record):
        try:
            path = self.path_for(record)
            return (version(record["version"])[0] == version(bundled_version())[0]
                    and version(record["version"]) > version(bundled_version())
                    and 0 < record["size"] <= MAX_WHEEL and path.is_file()
                    and path.stat().st_size == record["size"]
                    and hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"])
        except (KeyError, TypeError, ValueError, OSError):
            return False

    def choices(self):
        if not self.enabled():
            return []
        state = self.read_state()
        return [record for key in ("active", "previous") if self.usable(record := state.get(key, {}))]

    def status(self):
        state = self.read_state() if self.enabled() else {}
        choices = self.choices()
        return {"enabled": self.enabled(), "currentVersion": choices[0]["version"] if choices else bundled_version(),
                "status": state.get("status", "idle"), "checkedAt": state.get("checkedAt", 0),
                "error": state.get("error", "")}

    def is_check_running(self):
        return self.worker is not None and self.worker.is_alive()

    def start_check(self):
        if not self.enabled() or time.time() - self.read_state().get("checkedAt", 0) < CHECK_INTERVAL:
            return
        with self.thread_lock:
            if not self.is_check_running():
                self.worker = threading.Thread(target=self.check, name="edge-tts-update", daemon=True)
                self.worker.start()

    def check(self):
        with self.helpers.update_lock(self.root, "edge-tts-check.lock") as held:
            if not held or not self.enabled():
                return
            with self.helpers.update_lock(self.root, "edge-tts-state.lock", blocking=True) as locked:
                if not locked:
                    return
                state = self.read_state()
                if time.time() - state.get("checkedAt", 0) < CHECK_INTERVAL:
                    return
                state.update(checkedAt=time.time(), status="checking", error="")
                self.write_state(state)
            try:
                with tempfile.TemporaryDirectory(prefix="check-", dir=self.directory) as temporary:
                    stage = Path(temporary)
                    download(INDEX_URL, stage / "index.json", MAX_WHEEL)
                    release = json.loads((stage / "index.json").read_text(encoding="utf-8"))
                    candidate = release["info"]["version"]
                    if release["info"]["name"] != "edge-tts" or release.get("vulnerabilities"):
                        raise ValueError("Untrusted or vulnerable Edge speech release")
                    current = self.status()["currentVersion"]
                    if version(candidate) <= version(current):
                        state.update(status="up-to-date")
                    elif version(candidate)[0] != version(bundled_version())[0]:
                        raise ValueError("A new major Edge speech version requires an Engine update")
                    elif candidate == state.get("failedVersion"):
                        raise ValueError("This Edge speech version previously failed; keeping the working version")
                    else:
                        filename = f"edge_tts-{candidate}-py3-none-any.whl"
                        artifacts = [item for item in release["urls"] if item.get("filename") == filename
                                     and item.get("packagetype") == "bdist_wheel" and not item.get("yanked")]
                        if len(artifacts) != 1:
                            raise ValueError("No unique compatible Edge speech wheel")
                        artifact = artifacts[0]
                        record = {"version": candidate, "sha256": artifact["digests"]["sha256"], "size": artifact["size"]}
                        target = self.path_for(record)
                        if type(record["size"]) is not int or not 0 < record["size"] <= MAX_WHEEL:
                            raise ValueError("Invalid Edge speech wheel size")
                        wheel = stage / filename
                        download(artifact["url"], wheel, MAX_WHEEL)
                        validate_wheel(wheel, record)
                        # This check runs only after an authorized Microsoft speech request.
                        audio = stage / "check.mp3"
                        subprocess.run([*wheel_command(wheel), "--voice", "zh-CN-XiaoxiaoNeural", "--text",
                                        "语音连接测试。", "--write-media", str(audio)], check=True,
                                       timeout=SMOKE_TIMEOUT, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        if not audio.is_file() or audio.stat().st_size < 1000:
                            raise ValueError("Edge speech update did not generate audio")
                        ffmpeg = self.root / ".venv" / ("ffmpeg.exe" if os.name == "nt" else "bin/ffmpeg")
                        subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-i", str(audio), "-f", "null", "-"],
                                       check=True, timeout=SMOKE_TIMEOUT, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        os.replace(wheel, target)
                        # shortcut: retain small verified wheels; pruning needs cross-process reader leases.
                        # Merge current state so a concurrent playback rollback is not lost.
                        with self.helpers.update_lock(self.root, "edge-tts-state.lock", blocking=True) as locked:
                            if not locked:
                                raise RuntimeError("Speech update state is busy")
                            latest = self.read_state()
                            previous = next((item for key in ("active", "previous")
                                             if self.usable(item := latest.get(key, {}))), {})
                            latest.update(active=record, previous=previous, status="updated", error="",
                                          checkedAt=state["checkedAt"])
                            self.write_state(latest)
                        return
            except Exception as error:
                state.update(status="failed", error=str(error)[:300])
            with self.helpers.update_lock(self.root, "edge-tts-state.lock", blocking=True) as locked:
                if not locked:
                    return
                latest = self.read_state()
                latest.update({key: state[key] for key in ("checkedAt", "status", "error")})
                self.write_state(latest)

    def rollback(self, failed):
        with self.helpers.update_lock(self.root, "edge-tts-state.lock", blocking=True) as locked:
            if not locked:
                return
            state = self.read_state()
            if state.get("active") == failed:
                state.update(active=state.get("previous", {}), previous={}, failedVersion=failed["version"],
                             status="rolled-back", error="Updated speech client failed; restored the working client")
                self.write_state(state)


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--download":
        raise SystemExit("Unsupported speech updater command")
    fetch(sys.argv[2], sys.argv[3], int(sys.argv[4]))
