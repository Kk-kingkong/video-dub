# LocalTube Dub Release Process

Chrome Web Store Item ID: `ikoenamldegccnhmjjnlkffocdkbbbmo`

## Inputs

- A version already synchronized across `extension/manifest.json`, popup fallback text, tests, and `CHANGELOG.md`.
- The final 32-character Chrome Web Store extension ID. Chrome IDs contain only letters `a` through `p`.
- A macOS build machine with `python3`, `zip`, `unzip`, `ditto`, and `shasum`.
- Public HTTPS URLs for the [source repository](https://github.com/Kk-kingkong/video-dub), [project homepage](https://kk-kingkong.github.io/video-dub/), [privacy policy](https://kk-kingkong.github.io/video-dub/privacy-policy.html), [support page](https://kk-kingkong.github.io/video-dub/support.html), and signed Engine download.
- A Chrome Web Store developer account with two-step verification enabled.

The Engine package must be rebuilt whenever the Web Store extension ID changes because Native Messaging `allowed_origins` is bound to that ID.

The source repository excludes `dist/`. Publish verified binaries and checksums through a versioned release instead of committing historical ZIP files.

## Build

From the repository root:

```bash
./scripts/build_release_macos.sh FINAL_CHROME_EXTENSION_ID
```

For a customer-facing build, inject the hosted Engine and support pages at build time. Both values are optional for an offline private beta, but any configured URL must use HTTPS:

```bash
LOCAL_DUB_ENGINE_DOWNLOAD_URL=https://downloads.example.com/LocalTube-Dub-Engine.zip \
LOCAL_DUB_SUPPORT_URL=https://kk-kingkong.github.io/video-dub/support.html \
./scripts/build_release_macos.sh FINAL_CHROME_EXTENSION_ID
```

The command creates three files under `dist/`:

- `LocalTube-Dub-extension-vVERSION.zip`: upload this file to Chrome Web Store. `manifest.json` is at the ZIP root.
- `LocalTube-Dub-Engine-vVERSION-macOS.zip`: distribute this optional local Engine package from the product download/support page.
- `LocalTube-Dub-vVERSION-SHA256SUMS.txt`: publish beside both ZIP files.

The build automatically verifies manifest references, secrets, unsafe ZIP paths, extension-ID binding, release metadata, executable permissions, isolated Native Host/LaunchAgent generation, and uninstall dry-run.

The source install page remains in development mode. During release assembly, `release-info.json` is replaced with the exact channel, version, extension ID, Engine filename, and HTTPS links for that build. Customer packages hide source checkout paths, Terminal commands, and developer-only diagnostics; an offline beta with no hosted URL tells the tester to obtain the matching Engine ZIP from the same release.

## Private Beta Customer Flow

1. Install the Chrome extension.
2. Download the matching macOS Engine ZIP from the same release.
3. Unzip it and double-click `Install LocalTube Dub Engine.command`.
4. Restart Chrome and click “检查 Engine”.
5. Only users who need no-caption local transcription double-click `Install No-Caption Whisper.command`.

The private-beta package is deliberately marked `signed: false` and `notarized: false`. Customers may need to right-click the `.command` file and choose Open.

## Public Release Gates

Do not describe the Engine bundle as a signed public installer until all items below are complete:

1. Wrap or replace the bootstrap bundle with a Developer ID signed macOS app/pkg.
2. Notarize and staple the public artifact.
3. Host the Engine package and SHA-256 file on a stable HTTPS support/download page.
4. Replace all placeholder support and privacy-policy values.
5. Build and test a signed Windows Native Messaging installer.
6. Rebuild the Engine package with the final Web Store ID and verify `allowed_origins`.
7. Run the full release checks in `docs/development-audit.md`.
8. Publish `LICENSE`, `SECURITY.md`, `SUPPORT.md`, `THIRD_PARTY_NOTICES.md`, and the final `docs/privacy-policy.md` from the same public source revision.
9. Complete the Web Store single-purpose, permission-justification, data-use, distribution, and reviewer-instruction fields so they match the submitted source.
10. Prepare the 128 x 128 icon, at least one 1280 x 800 screenshot, the 440 x 280 promotional tile, and localized listing copy.
11. Run a clean-profile acceptance test with no saved cache, no API key, and no preinstalled Engine, then repeat with the matching Engine installer.
12. Confirm the repository and generated archives contain no keys, cookies, logs, models, generated media, absolute checkout paths, or copied proprietary extension assets.

## Recommended Store Sequence

1. Create the Store item and upload a draft ZIP to obtain the final extension ID.
2. Keep the same item unlisted while testing; do not create a duplicate production listing.
3. Rebuild and sign the Engine installer with that ID in `allowed_origins`.
4. Host the privacy, support, source, Engine, and checksum pages over HTTPS.
5. Complete the listing and privacy fields from `docs/store-listing-draft.md` and `docs/chrome-web-store-permissions.md`.
6. Submit the unlisted item for review, complete reviewer testing, then change the same item to public after acceptance testing.

## Verification Commands

```bash
python3 tools/verify_release_packages.py \
  dist/LocalTube-Dub-extension-vVERSION.zip \
  dist/LocalTube-Dub-Engine-vVERSION-macOS.zip \
  FINAL_CHROME_EXTENSION_ID \
  VERSION

cd dist
shasum -a 256 -c LocalTube-Dub-vVERSION-SHA256SUMS.txt
```
