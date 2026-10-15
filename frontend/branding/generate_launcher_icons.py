"""Generate Harvestique Android launcher icons from the Karnataka flag image.

Usage (needs Pillow + numpy):
    python branding/generate_launcher_icons.py branding/karnataka_flag_source.png android/app/src/main/res

The flag's flat yellow/red fields are redrawn as clean colour blocks; only the
black Karnataka silhouette is taken from the source image (upscaled smoothly),
so every density stays crisp. The adaptive foreground keeps the silhouette
inside the 66dp safe circle so no launcher mask can crop it.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}
SS = 4  # supersampling factor for anti-aliased rendering


def load_flag(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    h, w, _ = a.shape
    yellow = tuple(int(v) for v in np.median(a[5 : h // 2 - 20, 5:60].reshape(-1, 3), axis=0))
    red = tuple(int(v) for v in np.median(a[h // 2 + 20 : h - 5, 5:60].reshape(-1, 3), axis=0))

    # Soft "darkness" alpha keeps the source's anti-aliased edge information.
    darkness = np.clip((140 - a.max(axis=2)) / 80.0, 0.0, 1.0)
    ys, xs = np.where(darkness > 0.5)
    pad = 6
    box = (xs.min() - pad, ys.min() - pad, xs.max() + pad + 1, ys.max() + pad + 1)
    mask = Image.fromarray((darkness * 255).astype(np.uint8)).crop(box)

    # Upscale 8x, smooth, then re-threshold to get a clean high-res silhouette.
    up = mask.resize((mask.width * 8, mask.height * 8), Image.LANCZOS)
    up = up.filter(ImageFilter.GaussianBlur(6))
    up = up.point(lambda v: 255 if v >= 128 else 0)
    up = up.filter(ImageFilter.GaussianBlur(1.5))
    up = up.crop(up.point(lambda v: 255 if v > 0 else 0).getbbox())
    return yellow, red, up


def outlined(sil):
    """Silhouette with the flag's thin white outline: returns (outline_mask, sil_mask) on a padded canvas."""
    stroke = max(4, round(sil.height * 0.014))
    pad = stroke * 3
    canvas = Image.new("L", (sil.width + 2 * pad, sil.height + 2 * pad), 0)
    canvas.paste(sil, (pad, pad))
    grown = canvas.filter(ImageFilter.GaussianBlur(stroke)).point(lambda v: 255 if v > 20 else 0)
    grown = grown.filter(ImageFilter.GaussianBlur(1.5))
    return grown, canvas


def fit_scale(mask, size, radius_frac):
    """Scale so every opaque pixel of `mask` (centred) lies within radius_frac*size of the centre."""
    m = np.asarray(mask) > 10
    ys, xs = np.where(m)
    cy, cx = mask.height / 2, mask.width / 2
    rmax = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2).max()
    return radius_frac * size / rmax


def render(size, yellow, red, outline_mask, sil_mask, radius_frac, background, shape=None, mono=False):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if background:
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, S, S // 2], fill=yellow + (255,))
        d.rectangle([0, S // 2, S, S], fill=red + (255,))

    k = fit_scale(outline_mask, S, radius_frac)
    nw, nh = round(outline_mask.width * k), round(outline_mask.height * k)
    ox, oy = (S - nw) // 2, (S - nh) // 2
    om = outline_mask.resize((nw, nh), Image.LANCZOS)
    sm = sil_mask.resize((nw, nh), Image.LANCZOS)
    if mono:
        img.paste(Image.new("RGBA", (nw, nh), (255, 255, 255, 255)), (ox, oy), sm)
    else:
        img.paste(Image.new("RGBA", (nw, nh), (255, 255, 255, 255)), (ox, oy), om)
        img.paste(Image.new("RGBA", (nw, nh), (12, 12, 12, 255)), (ox, oy), sm)

    if shape:
        clip = Image.new("L", (S, S), 0)
        d = ImageDraw.Draw(clip)
        if shape == "circle":
            d.ellipse([0, 0, S - 1, S - 1], fill=255)
        else:  # rounded square for the legacy (pre-API 26) icon
            inset = round(S * 0.04)
            d.rounded_rectangle([inset, inset, S - 1 - inset, S - 1 - inset], radius=round(S * 0.16), fill=255)
        alpha = Image.fromarray(np.minimum(np.asarray(img.getchannel("A")), np.asarray(clip)))
        img.putalpha(alpha)
    return img.resize((size, size), Image.LANCZOS)


def hex_rgb(c):
    return "#FF%02X%02X%02X" % c


def main(src, res_dir):
    res = Path(res_dir)
    yellow, red, sil = load_flag(src)
    outline_mask, sil_mask = outlined(sil)
    print("yellow", yellow, "red", red, "silhouette px", sil.size)

    for name, f in DENSITIES.items():
        d = res / f"mipmap-{name}"
        d.mkdir(parents=True, exist_ok=True)
        legacy = round(48 * f)
        adaptive = round(108 * f)
        render(legacy, yellow, red, outline_mask, sil_mask, 0.40, True, "square").save(d / "ic_launcher.png")
        render(legacy, yellow, red, outline_mask, sil_mask, 0.40, True, "circle").save(d / "ic_launcher_round.png")
        # Safe zone is a 66dp circle in a 108dp canvas (radius 0.3056); stay a bit inside it.
        render(adaptive, yellow, red, outline_mask, sil_mask, 0.29, False).save(d / "ic_launcher_foreground.png")
        render(adaptive, yellow, red, outline_mask, sil_mask, 0.29, False, mono=True).save(d / "ic_launcher_monochrome.png")

    (res / "values").mkdir(exist_ok=True)
    (res / "values" / "ic_launcher_colors.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_flag_yellow">{hex_rgb(yellow)}</color>\n'
        f'    <color name="ic_launcher_flag_red">{hex_rgb(red)}</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
