"""
Gera o avatar do bot Recall (Acordito) no formato exigido pelo Recall.ai:
JPEG 16:9, 1280x720, <=1.3MB. Acordito centralizado sobre fundo amostrado
do canto da imagem original (blend suave).

Uso: python scripts/make_bot_avatar.py
Saída: assets/acordito_bot.jpg
Rode de novo se trocar a imagem-fonte assets/Acordito.png.
"""

import os
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "assets", "Acordito.png")
OUT = os.path.join(ROOT, "assets", "acordito_bot.jpg")

W, H = 1280, 720
MARGIN = 40  # respiro vertical


def build():
    src = Image.open(SRC).convert("RGB")

    # cor de fundo = média do canto superior esquerdo (fundo cinza do render)
    bg = src.crop((0, 0, 12, 12)).resize((1, 1)).getpixel((0, 0))
    canvas = Image.new("RGB", (W, H), bg)

    # escala a coruja para caber na altura com margem
    target_h = H - 2 * MARGIN
    scale = target_h / src.height
    new_w = int(src.width * scale)
    new_h = target_h
    fig = src.resize((new_w, new_h), Image.LANCZOS)

    canvas.paste(fig, ((W - new_w) // 2, (H - new_h) // 2))

    # salva com qualidade alta, garantindo <=1.3MB
    q = 92
    while True:
        canvas.save(OUT, "JPEG", quality=q, optimize=True)
        if os.path.getsize(OUT) <= 1_300_000 or q <= 70:
            break
        q -= 3

    print(f"OK -> {OUT}  ({W}x{H}, {os.path.getsize(OUT)//1024} KB, q={q}, bg={bg})")


if __name__ == "__main__":
    build()
