# Open Source and Store Compliance Design

## Objective

Prepare LocalTube Dub for a public source repository and later Chrome Web Store submission without changing subtitle extraction, translation, transcription, TTS, or synchronization behavior.

## Scope

- License the original project under Apache-2.0.
- Add contribution, security, support, conduct, dependency, and repository templates.
- Make the privacy policy match actual extension and Engine data flows.
- Remove undeveloped managed-service claims from public store copy.
- Document Chrome Web Store permissions, release gates, final extension-ID binding, and public Engine packaging requirements.
- Increase the packaged metadata version and add a changelog entry because the release-facing documentation changes.

## Constraints

- Do not modify core translation, caption, voice, or timing logic.
- Do not add telemetry, payment, accounts, advertising, or remote executable code.
- Do not publish secrets, browser cookies, generated media, local models, logs, or machine-specific paths.
- Keep unresolved publisher-owned values, such as the final Store ID and public HTTPS URLs, as explicit release gates rather than inventing them.

## Verification

Run the existing deterministic JavaScript, Python Engine, and Native Messaging checks; validate manifest/document consistency; scan source and generated archives for secrets and local absolute paths; and verify a release package built with the current development extension ID.
