"""Regenerate the PAL VHS app artwork with Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "assets" / "icons"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable-nodpi"
INK = "#101b1d"
MINT = "#b9ead5"
CORAL = "#ff7f73"
DARK_TEAL = "#284344"

def cassette(canvas, scale, origin):
    draw = ImageDraw.Draw(canvas)
    x, y = origin

    def box(coords):
        left, top, right, bottom = coords
        return x + left * scale, y + top * scale, x + right * scale, y + bottom * scale

    draw.rounded_rectangle(box((0, 5, 80, 57)), radius=9 * scale, fill=MINT)
    draw.rounded_rectangle(box((8, 15, 72, 43)), radius=5 * scale, fill=INK)
    draw.line([box((28, 29, 52, 29))[:2], box((28, 29, 52, 29))[2:]], fill=MINT, width=3 * scale)
    for center in (24, 56):
        draw.ellipse(box((center - 9, 20, center + 9, 38)), fill=MINT)
        draw.ellipse(box((center - 4, 25, center + 4, 33)), fill=INK)
    draw.polygon([(x + u * scale, y + v * scale) for u, v in
                  ((17, 51), (22, 45), (58, 45), (63, 51))], fill=DARK_TEAL)
    draw.rounded_rectangle(box((7, 55, 56, 60)), radius=2 * scale, fill=CORAL)
    draw.rounded_rectangle(box((61, 55, 73, 60)), radius=2 * scale, fill=CORAL)


def main():
    ICONS.mkdir(parents=True, exist_ok=True)
    ANDROID.mkdir(parents=True, exist_ok=True)
    desktop = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(desktop)
    draw.rounded_rectangle((12, 12, 499, 499), radius=110, fill=INK)
    draw.rounded_rectangle((20, 20, 491, 491), radius=102, outline=DARK_TEAL, width=8)
    cassette(desktop, 5, (56, 90))
    desktop.save(ICONS / "pal-vhs.png")
    desktop.resize((256, 256), Image.Resampling.LANCZOS).save(
        ICONS / "pal-vhs.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]
    )

    foreground = Image.new("RGBA", (432, 432))
    cassette(foreground, 3, (96, 118))
    foreground.save(ANDROID / "pal_vhs_foreground.png")
    mask = Image.new("L", foreground.size)
    mask.putdata([alpha if (r, g, b) != (16, 27, 29) else 0 for r, g, b, alpha in foreground.getdata()])
    monochrome = Image.new("RGBA", foreground.size, "white")
    monochrome.putalpha(mask)
    monochrome.save(ANDROID / "pal_vhs_monochrome.png")


if __name__ == "__main__":
    main()
