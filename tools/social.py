"""1280x640 social card (GitHub profile, abdani.github.io, link previews) in the same layout as the
other apps: icon + name left, the app's window with a soft shadow right. Uses docs/images/console.png
from tools/capture.py.   usage (from the repo root): python tools/social.py -> docs/images/social-preview.png"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

IMG = "docs/images"
FONTS = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
BLUE, RED = (45, 140, 255), (235, 60, 60)  # the icon's camera and lightning


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def gradient(w, h):
    bg = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(bg)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=(round(14 - 4 * t), round(18 - 6 * t), round(34 - 12 * t)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-w * 0.2, -h * 0.35, w * 0.45, h * 0.4), fill=BLUE + (130,))
    g.ellipse((w * 0.55, h * 0.45, w * 1.25, h * 1.35), fill=RED + (95,))
    return Image.alpha_composite(bg.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(min(w, h) // 5)))


def window(name, scale, r=8):
    im = Image.open(os.path.join(IMG, name)).convert("RGB")
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    ImageDraw.Draw(out).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, outline=(255, 255, 255, 40))
    return out


def place(canvas, win, x, y, blur=24, drop=16, opacity=200):
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    m = Image.new("L", win.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, win.width - 1, win.height - 1), 12, fill=opacity)
    shadow.paste((0, 0, 0, 255), (x, y + drop), m)
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(win, (x, y))


def social():
    W, H = 1280, 640
    c = gradient(W, H)
    d = ImageDraw.Draw(c)
    icon = Image.open(os.path.join(IMG, "icon.png")).convert("RGBA")
    icon = icon.crop(icon.getchannel("A").getbbox()).resize((140, 140), Image.LANCZOS)
    c.alpha_composite(icon, (75, 150))
    title = font("segoeuib.ttf", 80)
    d.text((70, 312), "Zoom", font=title, fill=(255, 255, 255))
    d.text((70, 396), "War", font=title, fill=(255, 255, 255))
    d.text((75, 503), "Get into a full Zoom meeting", font=font("segoeuil.ttf", 27), fill=(216, 222, 240))
    d.text((75, 541), "auto-retry  ·  alarm  ·  rejoin  ·  open source", font=font("segoeuil.ttf", 21), fill=(150, 160, 190))
    place(c, window("console.png", 0.72), 560, 206)
    out = os.path.join(IMG, "social-preview.png")
    c.convert("RGB").save(out, optimize=True)
    print(out, c.size, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    social()
