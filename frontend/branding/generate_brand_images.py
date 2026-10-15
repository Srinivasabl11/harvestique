"""Generate every Harvestique brand image from the seedling photo (the official brand image).

Usage (needs Pillow + numpy):
    python branding/generate_brand_images.py branding/seedling_source.png .

Writes, relative to the Flutter project root given as the second argument:
* android/app/src/main/res/mipmap-<density>/ic_launcher.png, ic_launcher_round.png   legacy icons (rounded square,
  circle) for launchers before Android 8
* .../ic_launcher_foreground.png   adaptive-icon foreground: the full-bleed photo, seedling centred inside the 66dp
  safe zone so no launcher mask crops the leaves
* android/app/src/main/res/drawable-xxhdpi/splash_seedling.png   round seedling for the launch screen
* android/app/src/main/res/values/ic_launcher_colors.xml          adaptive-icon background (the photo's dark green)
* assets/images/seedling_hero.jpg   Home hero background (the whole photo)
* assets/images/seedling_logo.png   round logo for the sign-in screen

The Android 13 themed icon (drawable/ic_launcher_monochrome.xml) is a hand-drawn vector of the same seedling: the
backlit right leaf is too pale to cut out of the photo cleanly, and a flat silhouette is what themed icons need.

The source photo is about 600 x 390 px (crops scale to its exact size), so the largest crops are scaled up a little; every output is resampled with
Lanczos and the photo's soft background hides most of it. A larger original can replace seedling_source.png and
this script regenerates everything.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}
# Crops of the 595 x 392 source (left, top, side). The seedling's leaves span about x 165-395, y 105-225 and the stem
# meets the soil at about y 310.
ADAPTIVE_CROP = (87, 0, 392)  # whole height: leaves take ~59 % of the width, inside the 61 % safe circle
ICON_CROP = (128, 62, 310)  # tighter: the seedling fills the small legacy icon
LOGO_CROP = (118, 40, 330)


BASE = (595, 392)  # the crops below were measured on a 595 x 392 copy; other sizes of the same photo are scaled


def crop(img, box, size):
    sx, sy = img.width / BASE[0], img.height / BASE[1]
    left, top, side = round(box[0] * sx), round(box[1] * sy), box[2] * min(sx, sy)
    side = round(min(side, img.width - left, img.height - top))
    return img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)


def clip(img, shape):
    """Rounded square (legacy icon) or circle; anti-aliased by drawing the mask 4x larger."""
    s = img.width * 4
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    if shape == "circle":
        d.ellipse([0, 0, s - 1, s - 1], fill=255)
    else:
        inset = round(s * 0.04)
        d.rounded_rectangle([inset, inset, s - 1 - inset, s - 1 - inset], radius=round(s * 0.16), fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize(img.size, Image.LANCZOS))
    return out



def main(src_path, project):
    root = Path(project)
    res = root / "android/app/src/main/res"
    src = Image.open(src_path).convert("RGB")
    if abs(src.width / src.height - BASE[0] / BASE[1]) > 0.05:
        print(f"note: crops were chosen for a {BASE[0]}x{BASE[1]} photo; this one is {src.size}, check the outputs")

    for name, f in DENSITIES.items():
        d = res / f"mipmap-{name}"
        d.mkdir(parents=True, exist_ok=True)
        legacy, adaptive = round(48 * f), round(108 * f)
        icon = crop(src, ICON_CROP, legacy)
        clip(icon, "square").save(d / "ic_launcher.png", optimize=True)
        clip(icon, "circle").save(d / "ic_launcher_round.png", optimize=True)
        crop(src, ADAPTIVE_CROP, adaptive).save(d / "ic_launcher_foreground.png", optimize=True)
        (d / "ic_launcher_monochrome.png").unlink(missing_ok=True)  # replaced by the vector drawable

    splash = res / "drawable-xxhdpi"
    splash.mkdir(parents=True, exist_ok=True)
    clip(crop(src, LOGO_CROP, 432), "circle").save(splash / "splash_seedling.png", optimize=True)

    # adaptive-icon background behind the (opaque) foreground: the photo's dark green, seen only during parallax
    edge = np.asarray(crop(src, ADAPTIVE_CROP, 108)).reshape(-1, 3)
    bg = tuple(int(v) for v in np.median(edge, axis=0))
    (res / "values" / "ic_launcher_colors.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">#FF{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )

    assets = root / "assets/images"
    assets.mkdir(parents=True, exist_ok=True)
    src.save(assets / "seedling_hero.jpg", quality=92, optimize=True)
    clip(crop(src, LOGO_CROP, 330), "circle").save(assets / "seedling_logo.png", optimize=True)
    print("background", bg, "- wrote icons, splash, hero and logo")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
