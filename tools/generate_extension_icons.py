#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Pillow is required to regenerate extension icons. "
        "Run this script with the bundled Codex Python runtime or install Pillow."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "extension" / "assets"
SOURCE_ICON = ASSET_DIR / "icon-master.png"
SIZES = (16, 32, 48, 128)
TOOLBAR_ICON_ZOOM = 1.24


def square_image(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def center_zoom(image: Image.Image, zoom: float) -> Image.Image:
    if zoom <= 1:
        return image
    side = round(min(image.size) / zoom)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def main() -> None:
    if not SOURCE_ICON.exists():
        raise SystemExit(f"Missing source icon: {SOURCE_ICON}")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    source = square_image(Image.open(SOURCE_ICON).convert("RGBA"))
    toolbar_source = center_zoom(source, TOOLBAR_ICON_ZOOM)
    resample = Image.Resampling.LANCZOS

    for size in SIZES:
        icon = source.resize((size, size), resample)
        icon.save(ASSET_DIR / f"icon-{size}.png")
        toolbar_icon = toolbar_source.resize((size, size), resample)
        toolbar_icon.putalpha(icon.getchannel("A"))
        toolbar_icon.save(ASSET_DIR / f"toolbar-icon-{size}.png")


if __name__ == "__main__":
    main()
