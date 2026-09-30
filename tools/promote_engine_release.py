#!/usr/bin/env python3
"""Verify private release assets before making an Engine update public."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from sign_engine_update import MANIFEST_NAME, SIGNATURE_NAME, TARGETS, PublicationError, publish


def api(repository: str, endpoint: str, *, payload: dict | None = None):
    command = ["gh", "api", "--method", "PATCH" if payload is not None else "GET",
               f"repos/{repository}/{endpoint}"]
    if payload is not None:
        command += ["--input", "-"]
    return json.loads(subprocess.check_output(command, input=json.dumps(payload).encode() if payload is not None else None))


def release_for_tag(repository: str, tag: str) -> dict:
    # Draft releases are not resolved through the published-release-by-tag endpoint.
    page = 1
    while True:
        releases = api(repository, f"releases?per_page=100&page={page}")
        matches = [release for release in releases if release.get("tag_name") == tag]
        if matches:
            if len(matches) != 1:
                raise PublicationError("Ambiguous release tag")
            return matches[0]
        if len(releases) < 100:
            raise PublicationError("Release not found; prepare a draft with all signed assets first")
        page += 1


def verified_commit(repository: str, tag: str) -> str:
    commit = api(repository, f"commits/{tag}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublicationError("Invalid release commit")
    runs = api(repository, "actions/workflows/cross-platform-engine.yml/runs"
               f"?head_sha={commit}&per_page=100")["workflow_runs"]
    eligible = [run for run in runs if run.get("head_sha") == commit
                and run.get("event") in ("push", "workflow_dispatch")
                and run.get("path") == ".github/workflows/cross-platform-engine.yml"]
    latest = max(eligible, key=lambda run: (run.get("run_started_at", ""), run["id"], run.get("run_attempt", 1)), default={})
    if (any(run.get("status") != "completed" for run in eligible)
            or latest.get("status") != "completed" or latest.get("conclusion") != "success"):
        raise PublicationError("The latest cross-platform Engine CI run for this exact commit must succeed")
    return commit


def asset_snapshot(release: dict, tag: str, *, draft: bool) -> list[dict]:
    if (release.get("tag_name") != tag or release.get("draft") is not draft
            or release.get("prerelease") is not False or type(release.get("id")) is not int):
        raise PublicationError("Release must remain a stable draft until verified" if draft else "Expected a published stable release")
    names = {f"LocalTube-Dub-Engine-{tag}-{suffix}.zip" for _, _, suffix in TARGETS}
    names.update((MANIFEST_NAME, SIGNATURE_NAME))
    assets = [asset for asset in release.get("assets", []) if asset.get("name") in names]
    if len(assets) != len(names) or {asset["name"] for asset in assets} != names:
        raise PublicationError("Release must contain exactly one of each Engine package, manifest and signature")
    for asset in assets:
        if (asset.get("state") != "uploaded" or type(asset.get("id")) is not int
                or asset["id"] <= 0 or type(asset.get("size")) is not int or asset["size"] <= 0):
            raise PublicationError("Release assets have not finished uploading")
    return sorted(({key: asset.get(key) for key in ("id", "name", "size", "updated_at", "digest", "state")}
                   for asset in assets), key=lambda asset: asset["name"])


def download_asset(repository: str, asset: dict, destination: Path) -> None:
    with destination.open("wb") as output:
        subprocess.run(["gh", "api", f"repos/{repository}/releases/assets/{asset['id']}",
                        "-H", "Accept: application/octet-stream"], stdout=output, check=True)
    if destination.stat().st_size != asset["size"]:
        raise PublicationError(f"Downloaded asset size changed: {asset['name']}")


def promote(repository: str, tag: str, *, verify_only: bool = False) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*", repository):
        raise PublicationError("Invalid repository")
    if not re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", tag):
        raise PublicationError("Only stable vMAJOR.MINOR.PATCH tags are accepted")
    release = release_for_tag(repository, tag)
    assets = asset_snapshot(release, tag, draft=not verify_only)
    commit = verified_commit(repository, tag)
    with tempfile.TemporaryDirectory(prefix="localtube-release-gate-") as temporary:
        root = Path(temporary)
        for asset in assets:
            download_asset(repository, asset, root / asset["name"])
        publish(tag[1:], root, None, root, verify=True)
        current = api(repository, f"releases/{release['id']}")
        if asset_snapshot(current, tag, draft=not verify_only) != assets or current["id"] != release["id"]:
            raise PublicationError("Release assets changed during verification; retry the unchanged draft")
        if verified_commit(repository, tag) != commit:
            raise PublicationError("Release tag moved during verification")
        if not verify_only:
            result = api(repository, f"releases/{release['id']}",
                         payload={"draft": False, "prerelease": False, "make_latest": "true"})
            if result.get("id") != release["id"] or asset_snapshot(result, tag, draft=False) != assets:
                raise PublicationError("Published release response does not match the verified assets")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--verify-only", action="store_true", help="Recheck an already published release without writes")
    args = parser.parse_args()
    try:
        promote(os.environ.get("GH_REPO", ""), args.tag, verify_only=args.verify_only)
    except (PublicationError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Engine release gate failed: {error}")
        return 1
    print(f"{'Verified' if args.verify_only else 'Verified and published'} {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
