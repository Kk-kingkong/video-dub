# Engine Auto-update Implementation Plan

**Goal:** ship 0.2.8 as the one-time migration to signed automatic Engine updates.

**Spec:** [Approved design](../specs/2026-09-11-engine-auto-update-design.md)

**Architecture:** one stdlib updater module, existing customer installers, and one signed-feed publication workflow. Keep the current on-demand Engine lifecycle and Chrome Web Store distribution.

## Work and ownership

1. `server/engine_updates.py` and `tools/verify_engine_updates.py`: background signed-feed check and verified staging; public status; detached activation helper. APIs: `start_background_check(root)`, `get_update_status(root)`, `is_check_running()`, `begin_install_if_ready(root, parent_pid)`, `installation_in_progress(root)`. Test missing behavior first, then signature, archive and helper failure boundaries.
2. Existing macOS/Windows installers: validate and preserve current owned Native manifest in automatic mode; suppress interactive prompts; verify new Engine identity before deleting backup; restore the previous manifest/runtime on failure. Extend existing isolated installer checks.
3. Engine/server and extension UI: trigger checks only on actual Engine startup, protect in-progress checks from idle shutdown, begin handoff at idle and drain requests, return update status through health and show installing/ready/failure/migration states. Test ordering and passive health.
4. Builders, `tools/sign_engine_update.py`, and release workflow: include updater and public certificate, generate exact signed stable feed from all three verified archives, require successful CI for the release commit. Test missing artifacts and wrong signing key. Keep the private signing key locally in an ignored restricted directory; GitHub verifies the preuploaded public feed and signature without receiving the key.
5. Update version/documentation to 0.2.8, run source and cross-platform installer checks, build packages, sign and verify all release assets, publish GitHub release, and provide the extension and migration Engine paths. Do not submit to Chrome Web Store automatically.
