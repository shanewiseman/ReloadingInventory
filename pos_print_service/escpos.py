from __future__ import annotations

import io
import socket
import textwrap

import qrcode
from PIL import Image


INIT = b"\x1b@"
CUT = b"\x1dV\x00"
FEED_3 = b"\n\n\n"
ALIGN_LEFT = b"\x1ba\x00"
ALIGN_CENTER = b"\x1ba\x01"
BOLD_ON = b"\x1bE\x01"
BOLD_OFF = b"\x1bE\x00"


def text_bytes(text):
    return text.encode("cp437", errors="replace")


def command_text(text, width=42):
    lines = []
    for raw_line in str(text or "").splitlines():
        if not raw_line:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=width, replace_whitespace=False) or [""])
    return text_bytes("\n".join(lines) + "\n")


def normalize_image(image, max_width_px=576):
    image = image.convert("RGBA")
    background = Image.new("RGBA", image.size, "WHITE")
    background.alpha_composite(image)
    image = background.convert("L")
    if image.width > max_width_px:
        ratio = max_width_px / image.width
        image = image.resize((max_width_px, max(1, int(image.height * ratio))))
    return image.point(lambda pixel: 0 if pixel < 175 else 255, "1")


def image_bytes(image, max_width_px=576):
    mono = normalize_image(image, max_width_px=max_width_px)
    width_bytes = (mono.width + 7) // 8
    height = mono.height
    rows = bytearray()
    pixels = mono.load()
    for y in range(height):
        for x_byte in range(width_bytes):
            value = 0
            for bit in range(8):
                x = x_byte * 8 + bit
                if x < mono.width and pixels[x, y] == 0:
                    value |= 0x80 >> bit
            rows.append(value)
    return (
        b"\x1dv0\x00"
        + bytes([width_bytes & 0xFF, width_bytes >> 8, height & 0xFF, height >> 8])
        + bytes(rows)
        + b"\n"
    )


def image_from_bytes(content):
    return Image.open(io.BytesIO(content))


def qr_image(value, box_size=6):
    qr = qrcode.QRCode(border=2, box_size=box_size)
    qr.add_data(value)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def build_document(parts, feed_and_cut=True):
    output = bytearray(INIT)
    for part in parts:
        output.extend(part)
    if feed_and_cut:
        output.extend(FEED_3)
        output.extend(CUT)
    return bytes(output)


def send_tcp_print_job(host, port, content, timeout=5):
    if not host:
        raise RuntimeError("PRINTER_HOST is not configured")
    with socket.create_connection((host, int(port)), timeout=float(timeout)) as connection:
        connection.sendall(content)
