# Contributing to LocalTube Dub

Thanks for helping improve LocalTube Dub. Contributions should keep the extension's purpose narrow: translating, transcribing, and synchronizing dubbing for the active YouTube video.

## Before opening a change

- Search existing issues and describe the user-visible problem before proposing a large implementation.
- Keep API keys, YouTube cookies, generated audio, local models, logs, and machine-specific paths out of commits.
- Do not submit code, assets, or text copied from proprietary browser extensions or services.
- Confirm that any new dependency has a license compatible with Apache-2.0 and record it in `THIRD_PARTY_NOTICES.md`.
- Do not add telemetry, advertising, affiliate links, payment flows, or remote executable code.

## Development setup

Load `extension/` as an unpacked Chrome extension. The optional Engine setup and platform-specific commands are documented in `README.md` and `companion/README.md`.

Run the deterministic checks before submitting a pull request:

```bash
node tools/verify_extension_flows.js
node tools/verify_provider_registry.js
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py
```

Run syntax checks for every file you change. For release-related changes, also follow `docs/release-process.md` and verify the generated ZIP files.

## Pull requests

- Keep each pull request focused on one behavior or documentation goal.
- Add or update regression checks for behavior changes.
- Increase the extension version for a packaged release and add a matching top entry to `CHANGELOG.md`.
- Explain user-data, permission, and external-service changes explicitly.
- Include manual Chrome test steps when browser behavior cannot be covered deterministically.

By submitting a contribution, you agree that it may be distributed under the Apache License 2.0.
