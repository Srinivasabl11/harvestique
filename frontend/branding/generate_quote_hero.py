"""Generate the Home quote-hero background from the Karnataka flag image.

Usage (needs Pillow + numpy):
    python branding/generate_quote_hero.py branding/karnataka_flag_source.png assets/images/karnataka_hero.png

Reuses the launcher-icon pipeline: the flat yellow/red fields are redrawn as clean blocks and the
black Karnataka silhouette (with its thin white outline) is taken from the source and upscaled smoothly,
so the full-width hero stays crisp on high-density screens.
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from generate_launcher_icons import load_flag, outlined  # noqa: E402

SIZE = 1440  # square; the hero crops it with BoxFit.cover
SILHOUETTE_HEIGHT = 0.86  # of SIZE


def main(src, dst):
    yellow, red, sil = load_flag(src)
    outline, body = outlined(sil)
    scale = SILHOUETTE_HEIGHT * SIZE / body.height
    w, h = round(body.width * scale), round(body.height * scale)
    outline = outline.resize((w, h), Image.LANCZOS)
    body = body.resize((w, h), Image.LANCZOS)

    img = Image.new("RGB", (SIZE, SIZE), yellow)
    img.paste(red, (0, SIZE // 2, SIZE, SIZE))
    x, y = (SIZE - w) // 2, (SIZE - h) // 2
    img.paste((255, 255, 255), (x, y), outline)
    img.paste((10, 10, 12), (x, y), body)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, optimize=True)
    print(f"wrote {dst} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
