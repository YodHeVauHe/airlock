"""Build the lablab submission cover image (1280x720) with PIL.

Same identity as the product UI and the deck: near-black, Airlock blue,
containment green accent, terminal motif.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
BG = (13, 17, 23)
PANEL = (17, 22, 31)
PANEL2 = (11, 14, 20)
PRIMARY = (88, 166, 255)
ACCENT = (63, 185, 80)
TEXT = (230, 237, 243)
MUTED = (110, 118, 129)
BORDER = (31, 39, 53)
RISK = (248, 81, 73)

F = "C:/Windows/Fonts"


def font(name, size):
    return ImageFont.truetype(f"{F}/{name}", size)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # subtle grid
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(18, 23, 32))
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(18, 23, 32))

    # top row: brand + hackathon chip
    d.text((64, 52), "air", font=font("segoeuib.ttf", 30), fill=TEXT)
    w = d.textlength("air", font=font("segoeuib.ttf", 30))
    d.text((64 + w, 52), "lock", font=font("segoeuib.ttf", 30), fill=PRIMARY)
    chip_text = "VULTR: AGENT RUSH HACKATHON - CHALLENGE 1: BLAST RADIUS ZERO"
    f_chip = font("consola.ttf", 15)
    cw = d.textlength(chip_text, font=f_chip)
    d.rounded_rectangle((W - 64 - cw - 36, 50, W - 64, 88), radius=17,
                        outline=PRIMARY, width=2)
    d.text((W - 64 - cw - 18, 58), chip_text, font=f_chip, fill=PRIMARY)

    # headline
    d.text((60, 130), "Give your AI agent real work.", font=font("segoeuib.ttf", 52), fill=TEXT)
    d.text((60, 196), "Keep your blast radius at zero.", font=font("segoeuib.ttf", 52), fill=TEXT)

    # pipeline chips
    steps = ["plan", "dispatch", "verify", "destroy"]
    x = 64
    f_chip2 = font("consolab.ttf", 18)
    for i, s_ in enumerate(steps):
        c = ACCENT if s_ == "destroy" else PRIMARY
        cw = d.textlength(s_, font=f_chip2) + 40
        d.rounded_rectangle((x, 290, x + cw, 332), radius=21, fill=c)
        d.text((x + 20, 297), s_, font=f_chip2, fill=BG)
        x += cw + 14
        if i < 3:
            d.text((x - 6, 296), ">", font=font("consola.ttf", 20), fill=MUTED)
            x += 16

    # terminal window (right-bottom hero)
    tx, ty, tw, th = 64, 372, 1152, 226
    d.rounded_rectangle((tx, ty, tx + tw, ty + th), radius=12, fill=PANEL2, outline=BORDER, width=2)
    for i, c in enumerate((RISK, (210, 153, 34), ACCENT)):
        d.ellipse((tx + 18 + i * 26, ty + 14, tx + 32 + i * 26, ty + 28), fill=c)
    d.text((tx + 110, ty + 13), "airlock ~ torture run 7f54db", font=font("consola.ttf", 15), fill=MUTED)
    fm = font("consola.ttf", 19)
    lines = [
        ("$ rm -rf /", TEXT),
        ("attempted inside sandbox #7f54db ......... read-only rootfs: BOUNCED OFF", MUTED),
        ("sandbox.destroyed  ·  host fingerprint before == after  ·  f803ec53...", MUTED),
        ("CONTAINED  -  real executed work. zero blast radius. signed proof.", ACCENT),
    ]
    y = ty + 44
    for t, c in lines:
        d.text((tx + 24, y), t, font=fm, fill=c)
        y += 38

    # bottom strip
    f_small = font("consola.ttf", 16)
    d.text((64, 664), "github.com/YodHeVauHe/airlock", font=f_small, fill=PRIMARY)
    d.text((420, 664), "FastAPI · Docker · Vultr VM · Vultr Serverless Inference",
           font=f_small, fill=MUTED)
    d.text((1032, 664), "18 tests · CI · MIT", font=f_small, fill=MUTED)

    img.save("submission/cover.png")
    print("saved submission/cover.png", img.size)


if __name__ == "__main__":
    main()
