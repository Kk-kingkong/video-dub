# Open Source and Store Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare LocalTube Dub's repository and public documentation for open-source publication and a later Chrome Web Store submission without changing runtime behavior.

**Architecture:** Repository-governance files define contribution and security boundaries. Public compliance documents describe the extension's real data flows and permissions, while release documentation keeps publisher-owned URLs, signing, and the final Store ID as explicit gates. Runtime modules remain unchanged.

**Tech Stack:** Markdown, Chrome Manifest V3 metadata, Bash release tooling, Node.js verification, Python Engine verification.

## Global Constraints

- Keep subtitle extraction, translation, transcription, TTS, and synchronization logic unchanged.
- Use Apache-2.0 for project source.
- Record every packaged version in `CHANGELOG.md`.
- Never include API keys, cookies, generated media, local models, logs, or absolute development paths.

---

### Task 1: Repository governance

**Files:** Create `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `THIRD_PARTY_NOTICES.md`, `SUPPORT.md`, and `.github/` templates. Modify `.gitignore`.

- [x] Add the Apache-2.0 license and contribution boundaries.
- [x] Add private security-reporting and public support guidance.
- [x] Record optional dependency licenses and non-affiliation language.
- [x] Exclude secrets, environments, caches, models, logs, and release artifacts.

### Task 2: Store compliance documents

**Files:** Modify `README.md`, replace `docs/privacy-policy-template.md` with `docs/privacy-policy.md`, and modify `docs/store-listing-draft.md`, `docs/chrome-web-store-permissions.md`, `docs/chrome-web-store-roadmap.md`, and `docs/release-process.md`.

- [x] Align privacy disclosures with local storage, Chrome sync, BYOK providers, audio capture, YouTube cookie fallback, local Engine processing, and Microsoft natural speech.
- [x] Remove undeveloped managed-service claims and describe the single public workflow accurately.
- [x] Add public source, support, privacy, listing asset, reviewer, signing, and final Store-ID release gates.

### Task 3: Release metadata

**Files:** Modify `extension/manifest.json`, `extension/release-info.json`, `extension/popup.html`, `tools/verify_extension_flows.js`, media harness cache tags, `CHANGELOG.md`, and `docs/development-audit.md`.

- [x] Increase the release metadata to `0.1.95` without modifying runtime behavior.
- [x] Add a complete changelog and audit entry for the open-source/compliance release.

### Task 4: Verification

**Files:** Test existing source and generated release artifacts.

- [x] Run JavaScript flow and Provider registry verification.
- [x] Run Python Engine and Native Messaging verification.
- [x] Scan source for credentials, placeholders, absolute paths, and stale public claims.
- [x] Build and verify versioned extension and Engine ZIP files with the current development extension ID.
