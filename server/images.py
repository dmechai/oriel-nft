from __future__ import annotations

from collections import deque
from io import BytesIO

from PIL import Image, ImageFilter

CHROMA = (0, 255, 80)


def open_image(raw: bytes) -> Image.Image:
    im = Image.open(BytesIO(raw))
    im.load()
    return im


def to_png_bytes(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def remove_chroma(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    raw = bytearray(im.tobytes())
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if g > 165 and r < 155 and b < 155 and g > r + 30 and g > b + 30:
            raw[i + 3] = 0
        elif g > r + 22 and g > b + 22:
            raw[i + 1] = min(g, max(r, b) + 14)
    return Image.frombytes("RGBA", im.size, bytes(raw))


def alpha_ratio(im: Image.Image, transparent: bool) -> float:
    data = im.convert("RGBA").getchannel("A").tobytes()
    if not data:
        return 0
    step = max(1, len(data) // 8000)
    sample = data[::step]
    if transparent:
        hit = sum(1 for value in sample if value < 20)
    else:
        hit = sum(1 for value in sample if value > 235)
    return hit / len(sample)


def cutout_flat_background(im: Image.Image, tol: int = 36) -> Image.Image | None:
    im = im.convert("RGBA")
    w, h = im.size
    src = im.tobytes()
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]

    def pix(x: int, y: int) -> tuple[int, int, int]:
        i = (y * w + x) * 4
        return src[i], src[i + 1], src[i + 2]

    samples = [pix(x, y) for x, y in corners]
    avg = tuple(sum(sample[i] for sample in samples) // 4 for i in range(3))
    if any(sum(abs(sample[i] - avg[i]) for i in range(3)) > 48 for sample in samples):
        return None
    out = bytearray(src)
    seen = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()
    for x, y in corners:
        seen[y * w + x] = 1
        queue.append((x, y))
    limit = tol * 3
    while queue:
        x, y = queue.popleft()
        i = (y * w + x) * 4
        dist = abs(out[i] - avg[0]) + abs(out[i + 1] - avg[1]) + abs(out[i + 2] - avg[2])
        if dist <= limit:
            out[i + 3] = 0
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                    seen[ny * w + nx] = 1
                    queue.append((nx, ny))
    result = Image.frombytes("RGBA", (w, h), bytes(out))
    if alpha_ratio(result, transparent=True) < 0.08:
        return None
    return result


def dominant_colors(im: Image.Image, count: int = 5) -> list[str]:
    small = im.convert("RGB").resize((48, 48))
    quantized = small.quantize(colors=count, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = quantized.getcolors(48 * 48) or []
    colors.sort(reverse=True)
    hexes = []
    for _, rgb in colors:
        value = "#{:02x}{:02x}{:02x}".format(*rgb)
        if value not in hexes:
            hexes.append(value)
    return hexes[:count]


def mean_rgb(im: Image.Image) -> tuple[int, int, int]:
    small = im.convert("RGBA").resize((32, 32))
    raw = small.tobytes()
    total = [0, 0, 0]
    n = 0
    for i in range(0, len(raw), 4):
        if raw[i + 3] < 20:
            continue
        total[0] += raw[i]
        total[1] += raw[i + 1]
        total[2] += raw[i + 2]
        n += 1
    if not n:
        return (128, 128, 128)
    return tuple(channel // n for channel in total)  # type: ignore[return-value]


def harmonize(piece: Image.Image, reference: Image.Image, amount: float = 0.12) -> Image.Image:
    piece = piece.convert("RGBA")
    target = mean_rgb(reference)
    source = mean_rgb(piece)
    raw = bytearray(piece.tobytes())
    for i in range(0, len(raw), 4):
        if raw[i + 3] < 8:
            continue
        for c in range(3):
            raw[i + c] = int(raw[i + c] * (1 - amount) + target[c] * amount + (source[c] - target[c]) * 0.02)
    return Image.frombytes("RGBA", piece.size, bytes(raw))


def trim_alpha(im: Image.Image, pad: int = 4) -> Image.Image:
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 12 else 0).getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    return im.crop((max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad), min(im.height, y1 + pad)))


def feather(piece: Image.Image, radius: float) -> Image.Image:
    piece = piece.convert("RGBA")
    if radius <= 0:
        return piece
    alpha = piece.getchannel("A")
    softened = alpha.filter(ImageFilter.GaussianBlur(radius))
    piece.putalpha(softened)
    return piece


def dhash(im: Image.Image, size: int = 8) -> int:
    gray = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = gray.tobytes()
    value = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            value = (value << 1) | int(left > right)
    return value


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def similar_pairs(hashes: list[tuple[int, int]], threshold: int = 6) -> list[tuple[int, int, int]]:
    found = []
    for i, (id_a, hash_a) in enumerate(hashes):
        for id_b, hash_b in hashes[i + 1 :]:
            dist = hamming(hash_a, hash_b)
            if dist <= threshold:
                found.append((id_a, id_b, dist))
    return found


def compose(width: int, height: int, layers: list[dict]) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for layer in layers:
        im = layer["image"].convert("RGBA")
        method = layer.get("method") or "full"
        if method in ("background", "character", "full", "base"):
            im = im.resize((width, height), Image.Resampling.LANCZOS)
            canvas.alpha_composite(im)
            continue
        region = layer.get("region") or {"x": 0.34, "y": 0.12, "w": 0.32, "h": 0.24}
        pw = max(1, int(float(region["w"]) * width))
        ph = max(1, int(float(region["h"]) * height))
        px = int(float(region["x"]) * width)
        py = int(float(region["y"]) * height)
        if im.getchannel("A").getbbox() is None:
            continue
        if method == "patch":
            _stamp(canvas, im.resize((pw, ph), Image.Resampling.LANCZOS), px, py)
        else:
            piece = trim_alpha(im)
            piece.thumbnail((pw, ph), Image.Resampling.LANCZOS)
            px += (pw - piece.width) // 2
            py += (ph - piece.height) // 2
            _stamp(canvas, piece, px, py)
    return canvas


def _stamp(canvas: Image.Image, piece: Image.Image, x: int, y: int) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(piece, (x, y))
    canvas.alpha_composite(layer)


def _stamp_shadow(canvas: Image.Image, piece: Image.Image, x: int, y: int) -> None:
    alpha = piece.getchannel("A").filter(ImageFilter.GaussianBlur(5))
    shadow = Image.new("RGBA", piece.size, (28, 22, 16, 0))
    shadow.putalpha(alpha.point(lambda p: int(p * 0.32)))
    _stamp(canvas, shadow, x, y)
