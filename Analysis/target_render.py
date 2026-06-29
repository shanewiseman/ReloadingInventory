from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

TARGET_RADIUS_INCHES = 6
DEFAULT_IMAGE_SIZE = 1200
DEFAULT_PIXELS_PER_INCH = 80


def render_target(shots=None, image_size=DEFAULT_IMAGE_SIZE, pixels_per_inch=DEFAULT_PIXELS_PER_INCH):
    shots = shots or []
    image = Image.new("RGB", (image_size, image_size), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    center = image_size // 2
    outer_radius = TARGET_RADIUS_INCHES * pixels_per_inch

    _draw_rings(draw, center, pixels_per_inch)
    _draw_axes(draw, center, outer_radius, pixels_per_inch, font)
    _draw_center(draw, center, pixels_per_inch)
    _draw_shots(draw, center, pixels_per_inch, shots, font)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_rings(draw, center, pixels_per_inch):
    for radius_inches in range(1, TARGET_RADIUS_INCHES + 1):
        radius = radius_inches * pixels_per_inch
        draw.ellipse(
            (center - radius, center - radius, center + radius, center + radius),
            outline="black",
            width=3,
        )


def _draw_axes(draw, center, outer_radius, pixels_per_inch, font):
    axis_extent = outer_radius + int(pixels_per_inch * 0.55)
    draw.line((center - axis_extent, center, center + axis_extent, center), fill="black", width=8)
    draw.line((center, center - axis_extent, center, center + axis_extent), fill="black", width=8)

    tick_half = 18
    for value in range(1, TARGET_RADIUS_INCHES + 1):
        offset = value * pixels_per_inch
        for direction in (-1, 1):
            x = center + direction * offset
            draw.line((x, center - tick_half, x, center + tick_half), fill="black", width=8)
            label_x = x + (24 if direction > 0 else -38)
            _draw_text(draw, str(value), label_x, center + 26, font)

            y = center - direction * offset
            draw.line((center - tick_half, y, center + tick_half, y), fill="black", width=8)
            label_y = y - 36 if direction > 0 else y + 14
            _draw_text(draw, str(value), center + 28, label_y, font)


def _draw_center(draw, center, pixels_per_inch):
    red_radius = pixels_per_inch / 2
    border_radius = red_radius + 11
    draw.ellipse(
        (
            center - border_radius,
            center - border_radius,
            center + border_radius,
            center + border_radius,
        ),
        fill="white",
        outline="black",
        width=3,
    )
    draw.ellipse(
        (
            center - red_radius,
            center - red_radius,
            center + red_radius,
            center + red_radius,
        ),
        fill="red",
        outline="red",
    )


def _draw_shots(draw, center, pixels_per_inch, shots, font):
    for shot in shots:
        x = center + float(shot["x_inches"]) * pixels_per_inch
        y = center - float(shot["y_inches"]) * pixels_per_inch
        dot_radius = 11
        draw.ellipse(
            (x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius),
            fill="#0f6ea8",
            outline="white",
            width=3,
        )
        _draw_text(draw, str(shot["shot_id"]), x + 14, y - 18, font, fill="#0f3858")


def _draw_text(draw, text, x, y, font, fill="black"):
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2), fill="white")
    draw.text((x, y), text, fill=fill, font=font)
