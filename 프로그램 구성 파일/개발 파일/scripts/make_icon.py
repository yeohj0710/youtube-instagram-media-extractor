from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PNG_PATH = ASSETS / "youtube-instagram-media.png"
ICO_PATH = ASSETS / "youtube-instagram-media.ico"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 4


Color = tuple[int, int, int, int]
Image = list[list[Color]]


def clamp(value: float, low: int = 0, high: int = 255) -> int:
    return max(low, min(high, int(round(value))))


def mix(a: Color, b: Color, amount: float) -> Color:
    return (
        clamp(a[0] + (b[0] - a[0]) * amount),
        clamp(a[1] + (b[1] - a[1]) * amount),
        clamp(a[2] + (b[2] - a[2]) * amount),
        clamp(a[3] + (b[3] - a[3]) * amount),
    )


def over(dst: Color, src: Color) -> Color:
    sa = src[3] / 255.0
    da = dst[3] / 255.0
    out_a = sa + da * (1.0 - sa)
    if out_a == 0:
        return 0, 0, 0, 0
    return (
        clamp((src[0] * sa + dst[0] * da * (1.0 - sa)) / out_a),
        clamp((src[1] * sa + dst[1] * da * (1.0 - sa)) / out_a),
        clamp((src[2] * sa + dst[2] * da * (1.0 - sa)) / out_a),
        clamp(out_a * 255),
    )


def rounded_rect_alpha(px: float, py: float, x0: float, y0: float, x1: float, y1: float, radius: float) -> float:
    cx = min(max(px, x0 + radius), x1 - radius)
    cy = min(max(py, y0 + radius), y1 - radius)
    dist = math.hypot(px - cx, py - cy) - radius
    return max(0.0, min(1.0, 0.5 - dist))


def draw_rounded_rect(img: Image, x0: float, y0: float, x1: float, y1: float, radius: float, color: Color) -> None:
    height = len(img)
    width = len(img[0])
    for y in range(max(0, math.floor(y0 - 1)), min(height, math.ceil(y1 + 1))):
        for x in range(max(0, math.floor(x0 - 1)), min(width, math.ceil(x1 + 1))):
            alpha = rounded_rect_alpha(x + 0.5, y + 0.5, x0, y0, x1, y1, radius)
            if alpha:
                src = color[0], color[1], color[2], clamp(color[3] * alpha)
                img[y][x] = over(img[y][x], src)


def draw_polygon(img: Image, points: tuple[tuple[float, float], ...], color: Color) -> None:
    height = len(img)
    width = len(img[0])
    min_x = max(0, math.floor(min(x for x, _ in points) - 1))
    max_x = min(width, math.ceil(max(x for x, _ in points) + 1))
    min_y = max(0, math.floor(min(y for _, y in points) - 1))
    max_y = min(height, math.ceil(max(y for _, y in points) + 1))

    def inside(px: float, py: float) -> bool:
        hit = False
        j = len(points) - 1
        for i, (xi, yi) in enumerate(points):
            xj, yj = points[j]
            if (yi > py) != (yj > py):
                cross_x = (xj - xi) * (py - yi) / (yj - yi) + xi
                if px < cross_x:
                    hit = not hit
            j = i
        return hit

    for y in range(min_y, max_y):
        for x in range(min_x, max_x):
            if inside(x + 0.5, y + 0.5):
                img[y][x] = over(img[y][x], color)


def render(size: int) -> Image:
    return render_large(size)


def render_small(size: int) -> Image:
    img: Image = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    x0 = y0 = 1.0
    x1 = y1 = size - 1.0
    radius = max(3.0, size * 0.22)
    for y in range(size):
        for x in range(size):
            alpha = rounded_rect_alpha(x + 0.5, y + 0.5, x0, y0, x1, y1, radius)
            if alpha > 0.08:
                img[y][x] = (37, 99, 235, 255)

    draw_rounded_rect(
        img,
        size * 0.44,
        size * 0.22,
        size * 0.56,
        size * 0.56,
        max(0.5, size * 0.04),
        (255, 255, 255, 255),
    )
    arrow = (
        (size * 0.30, size * 0.50),
        (size * 0.50, size * 0.70),
        (size * 0.70, size * 0.50),
        (size * 0.59, size * 0.50),
        (size * 0.50, size * 0.59),
        (size * 0.41, size * 0.50),
    )
    draw_polygon(img, arrow, (255, 255, 255, 255))
    draw_rounded_rect(
        img,
        size * 0.30,
        size * 0.76,
        size * 0.70,
        size * 0.86,
        max(0.5, size * 0.05),
        (255, 255, 255, 245),
    )
    return img


def render_large(size: int) -> Image:
    scale = SUPERSAMPLE
    canvas_size = size * scale
    img: Image = [[(0, 0, 0, 0) for _ in range(canvas_size)] for _ in range(canvas_size)]

    inset = max(1.0, size * 0.045) * scale
    radius = size * 0.24 * scale
    x0 = y0 = inset
    x1 = y1 = canvas_size - inset

    top_left = (59, 130, 246, 255)
    bottom_right = (37, 99, 235, 255)
    for y in range(canvas_size):
        for x in range(canvas_size):
            alpha = rounded_rect_alpha(x + 0.5, y + 0.5, x0, y0, x1, y1, radius)
            if alpha:
                diagonal = (x + y) / max(1, (canvas_size - 1) * 2)
                color = mix(top_left, bottom_right, diagonal)
                img[y][x] = color[0], color[1], color[2], clamp(255 * alpha)

    draw_rounded_rect(
        img,
        size * 0.455 * scale,
        size * 0.22 * scale,
        size * 0.545 * scale,
        size * 0.55 * scale,
        size * 0.045 * scale,
        (255, 255, 255, 255),
    )
    arrow = (
        (size * 0.31 * scale, size * 0.49 * scale),
        (size * 0.50 * scale, size * 0.68 * scale),
        (size * 0.69 * scale, size * 0.49 * scale),
        (size * 0.58 * scale, size * 0.49 * scale),
        (size * 0.50 * scale, size * 0.57 * scale),
        (size * 0.42 * scale, size * 0.49 * scale),
    )
    draw_polygon(img, arrow, (255, 255, 255, 255))
    draw_rounded_rect(
        img,
        size * 0.29 * scale,
        size * 0.75 * scale,
        size * 0.71 * scale,
        size * 0.84 * scale,
        size * 0.045 * scale,
        (255, 255, 255, 245),
    )

    return downsample(img, size)


def downsample(img: Image, target_size: int) -> Image:
    scale = len(img) // target_size
    out: Image = [[(0, 0, 0, 0) for _ in range(target_size)] for _ in range(target_size)]
    area = scale * scale
    for y in range(target_size):
        for x in range(target_size):
            total = [0, 0, 0, 0]
            for sy in range(scale):
                for sx in range(scale):
                    px = img[y * scale + sy][x * scale + sx]
                    for i in range(4):
                        total[i] += px[i]
            out[y][x] = tuple(clamp(total[i] / area) for i in range(4))  # type: ignore[assignment]
    return out


def png_bytes(img: Image) -> bytes:
    height = len(img)
    width = len(img[0])
    raw = bytearray()
    for row in img:
        raw.append(0)
        for r, g, b, a in row:
            raw.extend((r, g, b, a))
    payload = zlib.compress(bytes(raw), level=9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", payload)
        + chunk(b"IEND", b"")
    )


def write_ico(images: list[tuple[int, bytes]]) -> None:
    header = struct.pack("<HHH", 0, 1, len(images))
    directory = bytearray()
    offset = 6 + 16 * len(images)
    payload = bytearray()
    for size, data in images:
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payload.extend(data)
        offset += len(data)
    ICO_PATH.write_bytes(header + directory + payload)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    PNG_PATH.write_bytes(png_bytes(render(256)))
    write_ico([(size, png_bytes(render(size))) for size in ICO_SIZES])
    print(f"Wrote {PNG_PATH}")
    print(f"Wrote {ICO_PATH}")


if __name__ == "__main__":
    main()
