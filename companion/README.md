# LocalTube Dub Engine

This folder contains the local companion process used by the Chrome Web Store version of LocalTube Dub.

The extension can be installed from the store, but the local AI engine must be installed separately because Chrome extensions cannot bundle or silently launch native executables. The native host lets Chrome start the local engine through the official Native Messaging API.

## Customer packages

Version `0.2.8` prepares matching Engine archives for macOS Apple Silicon, macOS Intel, and Windows 10/11 x64. Each archive contains a pinned private runtime; customers do not need to install Python, pip, Homebrew, or a compiler.

- macOS: unzip the matching architecture package and open `Install LocalTube Dub Engine.command`.
- Windows: unzip the x64 package and run `Install LocalTube Dub Engine.cmd`.

Both installers register the current-user Native Messaging host and remove legacy login startup. Windows briefly starts the loopback Engine to verify installation, then stops it. User operations start Engine on demand; it exits after five idle minutes. Active requests, background jobs, model downloads and audio downloads prevent idle exit. Passive status checks do not wake it or extend its idle timer. The current development packages are unsigned and unnotarized.

For an unpacked extension or ZIP test build, Chrome may assign a different ID from the Store ID used by a double-click installation. Copy LocalTube Dub's actual ID from the extension install page or `chrome://extensions`. From the extracted Engine package directory, replace `YOUR_EXTENSION_ID` and run:

```bash
# macOS
bash "./Install LocalTube Dub Engine.command" YOUR_EXTENSION_ID
```

```powershell
# Windows (PowerShell)
& ".\Install LocalTube Dub Engine.cmd" -ExtensionId YOUR_EXTENSION_ID
```

On macOS, an already installed Engine can also be rebound with `bash "$HOME/Library/Application Support/LocalTube Dub/engine-runtime/companion/install_native_host_macos.sh" YOUR_EXTENSION_ID`. A Native Messaging `forbidden` error means the extension is not authorized by the host; restarting Chrome alone does not fix an ID mismatch. Recheck Engine after registration. Keep the unpacked extension directory unchanged when upgrading; rebind if moving it changes its ID. The `0.2.8` manual installer retains valid existing IDs registered to the same runtime and adds the explicitly requested ID; subsequent automatic upgrades preserve that registration.

Kokoro is optional and not bundled in the Engine ZIP. Select **Kokoro high-quality local** in the extension and click **Install model**. The Engine downloads and verifies the fixed model data before local Chinese/English synthesis becomes available.

## Automatic updates and one-time migration

Install the matching `0.2.8` Engine package manually once to add the updater to an older installation. Thereafter, actual Engine startup checks the fixed GitHub stable release feed at most once every six hours. Source installs do not opt into automatic binary replacement. Passive health checks remain local and do not wake Engine.

Only newer releases with a matching protocol, platform, and architecture qualify. Engine verifies the pinned update signature, package size and SHA-256, and archive layout before staging. Installation waits for the existing five-minute idle boundary and for accepted work to finish. The old process exits before a detached helper invokes the extracted package's installer. Native requests during this handoff report that Engine is updating.

Automatic installation keeps the original valid Native manifest, including any explicitly registered unpacked extension IDs, and preserves settings and models outside the runtime. New-runtime health must match the expected release before the backup is discarded. Activation failure restores the previous runtime and registration. Updates never replace Chrome extension code: Chrome manages Store installs, while ZIP/source extensions still require manual replacement and reload.

Updates download from this project's GitHub releases without sending captions, video URLs, audio, credentials, or cookies. The signed update feed is separate from operating-system code signing; current desktop installers remain unsigned and unnotarized. See [release operations](../docs/release-process.md) and [privacy](../docs/privacy-policy.md).

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

The installer copies Engine, Native Host, and their Python environment to `~/Library/Application Support/LocalTube Dub/engine-runtime`, then points Chrome's Native Messaging manifest at the launcher in that stable location. This avoids macOS blocking background Python while it opens a development checkout under the privacy-protected `~/Documents` folder. The launcher restores a normal terminal-like PATH before running `native_host.py`. Legacy LaunchAgents are removed; Engine starts through Native Messaging when needed and writes logs to `~/Library/Logs/LocalTube Dub`.

The install guide can repair on-demand startup through Native Messaging. The legacy-named install script now deploys the runtime and removes login startup; the uninstall script removes any old entry:

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

The release package is built and smoke-tested on Windows:

```powershell
py scripts\build_release_windows.py
py tools\verify_windows_package.py --install-smoke dist\LocalTube-Dub-Engine-v0.2.8-Windows-x64.zip
```

## Smoke tests

```bash
../.venv/bin/python native_host.py --health
../.venv/bin/python native_host.py --demo
../.venv/bin/python ../tools/verify_native_messaging.py
```

If Ollama is not running, `--demo` returns passthrough captions with a warning. That is expected for development.

## Product packaging path

The release builders package this folder with the Engine and scripts:

```bash
./scripts/build_release_macos.sh FINAL_CHROME_EXTENSION_ID
py scripts/build_release_windows.py
```

The generated ZIPs include install, repair/startup, health, and uninstall flows bound to the Store extension ID by default; an explicit validated ID supports unpacked testing. They remain unsigned and unnotarized. Before describing them as signed production installers:

- macOS: signed and notarized `.pkg` or `.dmg` that installs the native host manifest and app binary.
- Windows: signed `.msi` or `.exe` that writes the Native Messaging registry key.
- Linux: `.deb`/`.rpm` or shell installer for the native host manifest path.

The installer must write `allowed_origins` with the final Chrome Web Store extension ID or the explicitly supplied unpacked extension ID.
