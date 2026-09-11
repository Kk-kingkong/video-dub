# Engine automatic updates

Approved in the task on 2026-09-11: install once, then automatically follow compatible stable releases without interrupting translation, speech, or exports. Existing 0.2.7 customers need one manual migration. Chrome Web Store continues to deliver extension code; this updater never replaces browser extension files.

## Runtime flow

Only an installed bundled Engine with `autoUpdate: true` checks updates, after real HTTP Engine startup. Passive health remains passive. Check the fixed project's stable GitHub release feed at most once per six hours. Download in the background; wait for the existing five-minute idle boundary before applying. Protect an active check/download as work. Set an installation marker before stopping the server, drain accepted work, and let a detached helper wait for the old process to exit. Native work requests report `ENGINE_UPDATING` during the handoff.

The helper uses the verified candidate package's Python, so Windows can replace the old private runtime. Reuse the customer installers with `LOCAL_DUB_UPDATE_INSTALL=1` and `LOCAL_DUB_AUTO_UPDATE=0`. Keep the previous runtime until registration and exact new Engine health pass. Preserve owned Native manifest bindings byte-for-byte, Chrome settings, models and caches. Ordinary download, verification and installation failures retain the previous usable version.

## Trust and publication

Use RSA PKCS#1 v1.5 / SHA-256 signatures through platform crypto (OpenSSL or Windows .NET), with a DER public certificate bundled in the Engine. The private key stays in an ignored restricted local directory; sign locally before uploading the public manifest and signature. GitHub only verifies publication and never receives the private key. Verify exact manifest bytes before parsing download instructions, then verify asset sizes/SHA-256, version, protocol, platform and architecture before extraction/execution. Reject unsafe ZIP paths and escaping symlinks. No caller-supplied download URL or arbitrary execution endpoint.

Stable feed schema: `schemaVersion`, `channel`, `version`, `protocolVersion`, and three `packages` entries containing `platform`, `architecture`, `url`, `size`, `sha256`. Signature assets are `LocalTube-Dub-update.json` and `LocalTube-Dub-update.sig`. A stable release publication workflow requires passing cross-platform CI for its commit and complete matching assets. Prereleases receive no stable update feed. Platform code signing/notarization remains separate from the update signature and must not be falsely claimed.

## Verification

Real signature/tamper checks; wrong channel/version/platform/URL rejection; safe ZIP checks; failed download leaves installation untouched; passive health causes no checks; active requests delay handoff; Native requests during installation return an actionable state; automatic installers preserve multiple valid bindings and roll back on failure. Run existing source checks and macOS ARM/Intel plus Windows installation CI before publishing 0.2.8.
