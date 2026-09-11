"""Signed, idle-only updates for installed, bundled LocalTube Dub Engines."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile

RELEASE_URL = "https://github.com/Kk-kingkong/video-dub/releases/"
MANIFEST_URL = RELEASE_URL + "latest/download/LocalTube-Dub-update.json"
SIGNATURE_URL = RELEASE_URL + "latest/download/LocalTube-Dub-update.sig"
CERTIFICATE = Path(__file__).with_name("update-signing-cert.cer")
CHECK_INTERVAL = 6 * 60 * 60
MAX_ARCHIVE = 512 * 1024 ** 2
MAX_EXPANDED = 2 * 1024 ** 3
_worker = None
_thread_lock = threading.Lock()


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def state_directory(root):
    return Path(root).parent / "updates"


def write_state(root, state):
    directory = state_directory(root)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = directory / f"state.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(state), encoding="utf-8")
    os.replace(temporary, directory / "state.json")


@contextmanager
def update_lock(root, name="update.lock", blocking=False):
    directory = state_directory(root)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / name).open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){0,3}", value):
        raise ValueError("Invalid update version")
    parts = tuple(int(part) for part in value.split("."))
    if any(part > 65535 for part in parts):
        raise ValueError("Invalid update version")
    return parts + (0,) * (4 - len(parts))


def enabled(release):
    return (os.environ.get("LOCAL_DUB_AUTO_UPDATE") != "0" and release.get("autoUpdate") is True
            and release.get("bundledRuntime") is True
            and (release.get("platform"), release.get("architecture")) in
            {("macos", "arm64"), ("macos", "x64"), ("windows", "x64")})


def get_update_status(runtime_root):
    release = read_json(Path(runtime_root) / "release.json")
    state = read_json(state_directory(runtime_root) / "state.json") if enabled(release) else {}
    return {"enabled": enabled(release), "currentVersion": release.get("version", ""),
            "availableVersion": state.get("availableVersion", ""),
            "status": state.get("status", "idle"), "error": state.get("error", "")}


def has_native_work(root):
    if not enabled(read_json(Path(root) / "release.json")):
        return False
    directory = state_directory(root) / "native-work"
    active = False
    for lease in directory.iterdir() if directory.is_dir() else ():
        if lease.name.isdigit() and process_alive(int(lease.name)):
            active = True
        else:
            lease.unlink(missing_ok=True)
    return active


def register_native_work(root, pid):
    if not enabled(read_json(Path(root) / "release.json")):
        return True
    with update_lock(root, blocking=True) as held:
        if not held or read_json(state_directory(root) / "state.json").get("status") == "installing":
            return False
        directory = state_directory(root) / "native-work"
        directory.mkdir(mode=0o700, exist_ok=True)
        (directory / str(pid)).touch()
        return True


@contextmanager
def native_work_lease(root):
    if not enabled(read_json(Path(root) / "release.json")):
        yield True
        return
    installation_in_progress(root)
    admitted = register_native_work(root, os.getpid())
    try:
        yield admitted
    finally:
        if admitted:
            (state_directory(root) / "native-work" / str(os.getpid())).unlink(missing_ok=True)


def verify_signature(document, signature):
    if document.stat().st_size > 65536 or signature.stat().st_size > 1024:
        raise ValueError("Update signature or manifest is too large")
    if os.name == "nt":
        script = """$ErrorActionPreference='Stop';
        $cert=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new($env:LOCAL_DUB_VERIFY_CERT);
        $rsa=[System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($cert);
        if (-not $rsa.VerifyData([IO.File]::ReadAllBytes($env:LOCAL_DUB_VERIFY_DOC),[IO.File]::ReadAllBytes($env:LOCAL_DUB_VERIFY_SIG),[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1)) {exit 1}"""
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env={**os.environ, "LOCAL_DUB_VERIFY_CERT": str(CERTIFICATE),
                                     "LOCAL_DUB_VERIFY_DOC": str(document), "LOCAL_DUB_VERIFY_SIG": str(signature)},
                                capture_output=True, timeout=20)
    else:
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "public.pem"
            result = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", str(CERTIFICATE), "-pubkey", "-noout"], capture_output=True, timeout=20)
            if result.returncode:
                raise ValueError("Cannot read update signing certificate")
            key.write_bytes(result.stdout)
            result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(key), "-signature", str(signature), str(document)], capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError("Update signature verification failed")


def select_package(manifest, release):
    if (set(manifest) != {"schemaVersion", "channel", "version", "protocolVersion", "packages"}
            or type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1
            or manifest.get("channel") != "stable"
            or type(manifest.get("protocolVersion")) is not int
            or manifest["protocolVersion"] != release.get("protocolVersion")):
        raise ValueError("Update channel, schema, or Engine protocol is incompatible")
    version = version_tuple(manifest.get("version"))
    current = version_tuple(release.get("version"))
    if version == current:
        return None
    if version < current:
        raise ValueError("Engine downgrade refused")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 3:
        raise ValueError("Invalid update packages")
    selected, seen = None, set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"platform", "architecture", "url", "size", "sha256"}:
            raise ValueError("Invalid update package")
        identity = (package["platform"], package["architecture"])
        if identity not in {("macos", "arm64"), ("macos", "x64"), ("windows", "x64")} or identity in seen:
            raise ValueError("Unsupported or duplicate update platform")
        seen.add(identity)
        name = package_name(manifest["version"], package)
        if (package["url"] != RELEASE_URL + f"download/v{manifest['version']}/{name}.zip"
                or type(package["size"]) is not int or not 0 < package["size"] <= MAX_ARCHIVE
                or not isinstance(package["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", package["sha256"])):
            raise ValueError("Untrusted update URL, size, or checksum")
        if identity == (release.get("platform"), release.get("architecture")):
            selected = package
    if selected is None:
        raise ValueError("No compatible Engine update package")
    return selected


def package_name(version, package):
    return f"LocalTube-Dub-Engine-v{version}-{'macOS' if package['platform'] == 'macos' else 'Windows'}-{package['architecture']}"


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def validate_download_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or posixpath.normpath(urllib.parse.unquote(parsed.path)) != parsed.path
            or parsed.fragment or not (
                parsed.hostname == "github.com" and parsed.path.startswith("/Kk-kingkong/video-dub/releases/")
                or parsed.hostname in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
                and parsed.path.startswith("/github-production-release-asset/"))):
        raise ValueError("Untrusted update download redirect")


def download(url, destination, limit, expected_size=None):
    validate_download_url(url)
    deadline, count = time.monotonic() + 300, 0
    opener = urllib.request.build_opener(TrustedRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "LocalTube-Dub-Engine-Updater", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=15) as response, destination.open("wb") as output:
        validate_download_url(response.geturl())
        if int(response.headers.get("Content-Length", 0)) > limit:
            raise ValueError("Update download exceeds size limit")
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > limit or time.monotonic() > deadline:
                raise ValueError("Update download exceeded its size or time limit")
            output.write(chunk)
    if expected_size is not None and count != expected_size:
        raise ValueError("Update download is incomplete")


def extract_package(archive, destination, expected_root):
    """Validate all paths before writing; permit only internal macOS runtime links."""
    with zipfile.ZipFile(archive) as source:
        members, seen, links, total = source.infolist(), set(), {}, 0
        if len(members) > 100000:
            raise ValueError("Too many files in update package")
        for member in members:
            parts = member.filename.rstrip("/").split("/")
            key = unicodedata.normalize("NFD", "/".join(parts)).casefold()
            if (not parts or parts[0] != expected_root or key in seen or member.flag_bits & 1
                    or any(part in ("", ".", "..") or "\\" in part or ":" in part or "\x00" in part
                           or part.rstrip(" .") != part or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                           for part in parts)):
                raise ValueError("Unsafe or duplicate update archive path")
            seen.add(key)
            total += member.file_size
            if total > MAX_EXPANDED:
                raise ValueError("Expanded update is too large")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                if os.name == "nt" or member.file_size > 4096:
                    raise ValueError("Unsupported update symlink")
                target = source.read(member).decode("utf-8")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.filename), target))
                if target.startswith("/") or "\\" in target or not resolved.startswith(expected_root + "/"):
                    raise ValueError("Update symlink escapes package")
                links[member.filename] = target
            elif stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("Unsupported update archive file type")
        for member in members:
            if any(str(parent) in links for parent in PurePosixPath(member.filename).parents):
                raise ValueError("Update member traverses a symlink")
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            path = destination / member.filename
            if member.filename in links:
                continue
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_file, path.open("xb") as output:
                    shutil.copyfileobj(input_file, output, 1024 * 1024)
                path.chmod((member.external_attr >> 16) & 0o777 or 0o600)
        for name, target in links.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        for name in links:
            if not (destination / name).resolve().is_relative_to((destination / expected_root).resolve()):
                raise ValueError("Update symlink chain escapes package")
    return destination / expected_root


def check_archive(path, package):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if path.stat().st_size != package["size"] or digest != package["sha256"]:
        raise ValueError("Engine archive checksum verification failed")


def _check(root):
    if installation_in_progress(root):
        return
    with update_lock(root, "check.lock") as held:
        if not held:
            return
        with update_lock(root, blocking=True) as admitted:
            if not admitted:
                return
            state = read_json(state_directory(root) / "state.json")
            if state.get("status") == "installing" or time.time() - state.get("checkedAt", 0) < CHECK_INTERVAL:
                return
            previous = dict(state)
            state.update(status="checking", checkedAt=time.time(), error="")
            write_state(root, state)
        try:
            release = read_json(root / "release.json")
            with tempfile.TemporaryDirectory(prefix="download-", dir=state_directory(root)) as temporary:
                stage = Path(temporary)
                download(MANIFEST_URL, stage / "update.json", 65536)
                download(SIGNATURE_URL, stage / "update.sig", 1024)
                verify_signature(stage / "update.json", stage / "update.sig")
                manifest = read_json(stage / "update.json")
                package = select_package(manifest, release)
                if package is None:
                    state.update(status="idle", availableVersion="")
                else:
                    download(package["url"], stage / "package.zip", MAX_ARCHIVE, package["size"])
                    check_archive(stage / "package.zip", package)
                    name = package_name(manifest["version"], package)
                    extracted = extract_package(stage / "package.zip", stage / "extracted", name)
                    metadata = read_json(extracted / "release.json")
                    if any(metadata.get(key) != value for key, value in {
                        "version": manifest["version"], "protocolVersion": release["protocolVersion"],
                        "platform": package["platform"], "architecture": package["architecture"],
                        "bundledRuntime": True, "autoUpdate": True}.items()):
                        raise ValueError("Engine archive metadata does not match signed update")
                    target = state_directory(root) / manifest["version"]
                    if target.exists():
                        shutil.rmtree(target)
                    os.replace(stage, target)
                    state.update(status="ready", availableVersion=manifest["version"])
            with update_lock(root, blocking=True) as admitted:
                if admitted:
                    write_state(root, state)
            # Keep only the verified pending version; model/cache directories live elsewhere.
            for previous_download in state_directory(root).iterdir():
                if (previous_download.is_dir() and re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", previous_download.name)
                        and previous_download.name != state.get("availableVersion")):
                    shutil.rmtree(previous_download, ignore_errors=True)
        except Exception as error:
            state.update(status="ready" if previous.get("status") == "ready" else "failed",
                         availableVersion=previous.get("availableVersion", ""), error=str(error)[:500])
            with update_lock(root, blocking=True) as admitted:
                if admitted:
                    write_state(root, state)


def start_background_check(runtime_root):
    global _worker
    root = Path(runtime_root)
    if not enabled(read_json(root / "release.json")):
        return
    with _thread_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_check, args=(root,), name="engine-update", daemon=True)
            _worker.start()


def is_check_running():
    return _worker is not None and _worker.is_alive()


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def installation_in_progress(runtime_root):
    state = read_json(state_directory(runtime_root) / "state.json")
    if state.get("status") != "installing":
        return False
    if time.time() - state.get("installStartedAt", 0) < 900 and (
            process_alive(state.get("helperPid")) or process_alive(state.get("parentPid"))):
        return True
    with update_lock(runtime_root) as held:
        if held:
            state = read_json(state_directory(runtime_root) / "state.json")
            if state.get("status") != "installing":
                return False
            if time.time() - state.get("installStartedAt", 0) < 900 and (
                    process_alive(state.get("helperPid")) or process_alive(state.get("parentPid"))):
                return True
            state.update(status="failed", error="The Engine update process stopped before completion")
            write_state(runtime_root, state)
    return False


def begin_install_if_ready(runtime_root, parent_pid, commit_guard=lambda: nullcontext(True)):
    root = Path(runtime_root)
    if not enabled(read_json(root / "release.json")):
        return False
    with update_lock(root) as held:
        if not held:
            return False
        state = read_json(state_directory(root) / "state.json")
        if state.get("status") != "ready" or has_native_work(root) or is_check_running():
            return False
        try:
            version = state["availableVersion"]
            version_tuple(version)
            stage = state_directory(root) / version
            verify_signature(stage / "update.json", stage / "update.sig")
            manifest = read_json(stage / "update.json")
            package = select_package(manifest, read_json(root / "release.json"))
            if package is None or manifest["version"] != version:
                raise ValueError("Staged Engine update is no longer applicable")
            check_archive(stage / "package.zip", package)
            # Recreate executable files from the authenticated archive before launch.
            shutil.rmtree(stage / "extracted")
            extracted = extract_package(stage / "package.zip", stage / "extracted", package_name(version, package))
            python = extracted / ".venv" / ("python.exe" if os.name == "nt" else "bin/python")
            helper = state_directory(root) / "install_update.py"
            shutil.copyfile(__file__, helper)
            with commit_guard() as idle:
                if not idle or has_native_work(root):
                    return False
                state.update(status="installing", parentPid=parent_pid, helperPid=0, installStartedAt=time.time(), error="")
                write_state(root, state)
                env = {**os.environ, "LOCAL_DUB_UPDATE_INSTALL": "1", "LOCAL_DUB_AUTO_UPDATE": "0", "LOCAL_DUB_RUNTIME_DIR": str(root)}
                with (state_directory(root) / "install.log").open("ab") as log:
                    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
                    process = subprocess.Popen([str(python), str(helper), "--install", str(root), str(extracted), str(parent_pid)],
                                               cwd=state_directory(root), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
                state["helperPid"] = process.pid
                write_state(root, state)
            return True
        except Exception as error:
            state.update(status="failed", error=str(error)[:500])
            write_state(root, state)
            return False


def run_installer(root, extracted, parent_pid):
    deadline = time.monotonic() + 120
    try:
        while process_alive(parent_pid):
            if time.monotonic() > deadline:
                raise RuntimeError("Engine still has active work; update postponed")
            time.sleep(0.25)
        command = (["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(extracted / "install-engine.ps1")]
                   if os.name == "nt" else ["/bin/bash", str(extracted / "Install LocalTube Dub Engine.command")])
        subprocess.run(command, check=True, timeout=600, stdin=subprocess.DEVNULL)
        state = read_json(state_directory(root) / "state.json")
        if read_json(root / "release.json").get("version") != state.get("availableVersion"):
            raise RuntimeError("Installed Engine version does not match the update")
        state.update(status="updated", error="")
    except Exception as error:
        state = read_json(state_directory(root) / "state.json")
        state.update(status="failed", error=str(error)[:500])
    write_state(root, state)


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--install":
    run_installer(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
