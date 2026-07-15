# LocalTube Dub Engine

This folder contains the local companion process used by the Chrome Web Store version of LocalTube Dub.

The extension can be installed from the store, but the local AI engine must be installed separately because Chrome extensions cannot bundle or silently launch native executables. The native host lets Chrome start the local engine through the official Native Messaging API.

## Development install on macOS

1. Load or install the Chrome extension.
2. Copy the extension ID from `chrome://extensions`.
3. Prepare the Engine runtime from the project root. Current yt-dlp needs Python 3.10 or newer; this script creates a project `.venv` and installs a current Homebrew Python first when the Mac only has Apple's Python 3.9:

```bash
cd $HOME/Documents/code/localtube-dub
./scripts/install_engine_deps_macos.sh
```

4. Register the Native Host:

```bash
cd $HOME/Documents/code/localtube-dub/companion
./install_native_host_macos.sh YOUR_EXTENSION_ID
```

The installer copies Engine, Native Host, and their Python environment to `~/Library/Application Support/LocalTube Dub/engine-runtime`, then points Chrome's Native Messaging manifest at the launcher in that stable location. This avoids macOS blocking background Python while it opens a development checkout under the privacy-protected `~/Documents` folder. The launcher restores a normal terminal-like PATH before running `native_host.py`. A user LaunchAgent starts Engine after login, keeps it alive, and writes logs to `~/Library/Logs/LocalTube Dub`.

The install guide can repair auto-start through Native Messaging. The equivalent manual commands are:

```bash
./scripts/install_engine_autostart_macos.sh
./scripts/uninstall_engine_autostart_macos.sh
```

5. Restart Chrome or reload the extension.
6. In the extension popup, click "检查 Engine".

For free local transcription of videos without captions, open the extension install guide and click "一键安装本地转写", or run:

```bash
cd $HOME/Documents/code/localtube-dub
./scripts/install_local_whisper_macos.sh
```

## Development install on Windows

Run PowerShell from the `companion` folder:

```powershell
.\install_native_host_windows.ps1 -ExtensionId YOUR_EXTENSION_ID
```

## Smoke tests

```bash
../.venv/bin/python native_host.py --health
../.venv/bin/python native_host.py --demo
../.venv/bin/python ../tools/verify_native_messaging.py
```

If Ollama is not running, `--demo` returns passthrough captions with a warning. That is expected for development.

## Product packaging path

The private-beta release builder now packages this folder with the Engine and scripts:

```bash
./scripts/build_release_macos.sh FINAL_CHROME_EXTENSION_ID
```

The generated macOS ZIP has double-click install, optional Whisper install, and uninstall commands bound to that extension ID. It remains unsigned and unnotarized. For public release it must become a signed installer:

- macOS: signed and notarized `.pkg` or `.dmg` that installs the native host manifest and app binary.
- Windows: signed `.msi` or `.exe` that writes the Native Messaging registry key.
- Linux: `.deb`/`.rpm` or shell installer for the native host manifest path.

The installer must write `allowed_origins` with the final Chrome Web Store extension ID.
