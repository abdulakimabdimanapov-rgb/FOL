#!/usr/bin/env python3
"""Generate a clean jellyfish macOS app icon in purple light.

Inspired by Flaticon flat line jellyfish (ID 874957):
- Clean dome/bell shape at top
- 5 wavy tentacles flowing down
- Simple, recognizable, minimal
- Purple/violet color palette
"""

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageChops

SIZE = 1024
OUTPUT_DIR = Path(__file__).parent

# Purple palette
PURPLE_DARK   = (120, 60, 200)
PURPLE_MID    = (150, 90, 220)
PURPLE_LIGHT  = (180, 130, 255)
PURPLE_GLOW   = (200, 160, 255)
PURPLE_WHITE  = (230, 210, 255)
BG_GLOW       = (100, 50, 180)


def create_jellyfish_icon(frame_phase=0.0):
    """Create a clean, recognizable jellyfish icon."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    cx, cy = SIZE // 2, SIZE // 2

    # ─── 1. Background soft glow ─────────────────────────────
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    for r in range(450, 0, -3):
        alpha = int(15 * (r / 450))
        bg_draw.ellipse(
            [cx - r, cy - r + 30, cx + r, cy + r + 30],
            fill=(*BG_GLOW, alpha),
        )
    img = Image.alpha_composite(img, bg)

    bell_cx, bell_cy = cx, cy - 80

    # ─── 2. Bell body — clean dome shape ─────────────────────
    bell_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bell_layer)

    bw, bh = 340, 220

    # Main dome — filled ellipse, top half only
    # Draw full ellipse then mask to dome
    bd.ellipse(
        [bell_cx - bw // 2, bell_cy - bh // 2,
         bell_cx + bw // 2, bell_cy + bh // 2],
        fill=(*PURPLE_MID, 180),
    )
    # Cut bottom half to make dome
    bd.rectangle(
        [bell_cx - bw // 2, bell_cy + 10,
         bell_cx + bw // 2, bell_cy + bh // 2],
        fill=(0, 0, 0, 0),
    )

    # Rounded bottom edge of dome
    bd.arc(
        [bell_cx - bw // 2, bell_cy - 20,
         bell_cx + bw // 2, bell_cy + 40],
        start=0, end=180,
        fill=(*PURPLE_MID, 180), width=8,
    )

    img = Image.alpha_composite(img, bell_layer)

    # ─── 3. Inner bell gradient (brighter center) ────────────
    inner = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    id_draw = ImageDraw.Draw(inner)

    iw, ih = 240, 150
    id_draw.ellipse(
        [bell_cx - iw // 2, bell_cy - ih // 2 + 20,
         bell_cx + iw // 2, bell_cy + ih // 2 + 5],
        fill=(*PURPLE_LIGHT, 120),
    )
    id_draw.rectangle(
        [bell_cx - iw // 2, bell_cy + 25,
         bell_cx + iw // 2, bell_cy + ih // 2 + 5],
        fill=(0, 0, 0, 0),
    )
    img = Image.alpha_composite(img, inner)

    # ─── 4. Bright inner core ────────────────────────────────
    core = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)

    cw, ch = 160, 100
    cd.ellipse(
        [bell_cx - cw // 2, bell_cy - ch // 2 + 30,
         bell_cx + cw // 2, bell_cy + ch // 2 + 15],
        fill=(*PURPLE_GLOW, 100),
    )
    cd.rectangle(
        [bell_cx - cw // 2, bell_cy + 35,
         bell_cx + cw // 2, bell_cy + ch // 2 + 15],
        fill=(0, 0, 0, 0),
    )
    img = Image.alpha_composite(img, core)

    # ─── 5. Highlight spot (top-left) ────────────────────────
    hl = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    hl_d = ImageDraw.Draw(hl)
    hl_d.ellipse(
        [bell_cx - 80, bell_cy - 85,
         bell_cx - 10, bell_cy - 40],
        fill=(*PURPLE_WHITE, 140),
    )
    hl_d.ellipse(
        [bell_cx - 55, bell_cy - 68,
         bell_cx - 15, bell_cy - 42],
        fill=(255, 240, 255, 180),
    )
    img = Image.alpha_composite(img, hl)

    # ─── 6. Tentacles — 5 wavy lines ─────────────────────────
    tentacle_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    td = ImageDraw.Draw(tentacle_layer)

    tentacle_start_y = bell_cy + 40
    tentacle_end_y = bell_cy + 380
    num_tentacles = 5
    tentacle_spread = 280

    colors = [PURPLE_DARK, PURPLE_MID, PURPLE_LIGHT, PURPLE_MID, PURPLE_DARK]

    for i in range(num_tentacles):
        t = (i / (num_tentacles - 1)) - 0.5  # -0.5 to 0.5
        base_x = bell_cx + t * tentacle_spread

        color = colors[i]
        width = max(4, 10 - i)

        points = []
        num_segments = 60
        for j in range(num_segments + 1):
            frac = j / num_segments
            y = tentacle_start_y + frac * (tentacle_end_y - tentacle_start_y)
            # Wavy: sine with increasing amplitude
            amplitude = 8 + 50 * frac
            wave = math.sin(
                frac * math.pi * 3 + i * 0.7 + frame_phase * math.pi * 2
            ) * amplitude
            x = base_x + wave
            points.append((x, y))

        # Draw with gradient alpha
        for k in range(len(points) - 1):
            frac = k / len(points)
            alpha = int(200 * (1 - frac ** 1.3))
            c = (*color, max(0, alpha))
            w = max(2, int(width * (1 - frac * 0.6)))
            td.line([points[k], points[k + 1]], fill=c, width=w)

    # Soft blur for smoothness
    tentacle_layer = tentacle_layer.filter(ImageFilter.GaussianBlur(radius=1.5))
    img = Image.alpha_composite(img, tentacle_layer)

    # ─── 7. Oral arms — 3 shorter, thicker ───────────────────
    oral_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    od = ImageDraw.Draw(oral_layer)

    oral_start = bell_cy + 50
    oral_end = bell_cy + 250
    num_arms = 3
    arm_spread = 140

    for i in range(num_arms):
        t = (i / (num_arms - 1)) - 0.5
        base_x = bell_cx + t * arm_spread

        points = []
        num_seg = 35
        for j in range(num_seg + 1):
            frac = j / num_seg
            y = oral_start + frac * (oral_end - oral_start)
            amplitude = 6 + 30 * frac
            wave = math.sin(
                frac * math.pi * 2.5 + i * 1.0 + frame_phase * math.pi * 1.5
            ) * amplitude
            x = base_x + wave
            points.append((x, y))

        width = max(5, 12 - i * 2)
        for k in range(len(points) - 1):
            frac = k / len(points)
            alpha = int(160 * (1 - frac ** 1.1))
            c = (*PURPLE_GLOW, max(0, alpha))
            w = max(3, int(width * (1 - frac * 0.4)))
            od.line([points[k], points[k + 1]], fill=c, width=w)

    oral_layer = oral_layer.filter(ImageFilter.GaussianBlur(radius=1.0))
    img = Image.alpha_composite(img, oral_layer)

    # ─── 8. Bell outline stroke ──────────────────────────────
    outline = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    od2 = ImageDraw.Draw(outline)

    # Dome outline
    od2.arc(
        [bell_cx - bw // 2, bell_cy - bh // 2,
         bell_cx + bw // 2, bell_cy + bh // 2],
        start=180, end=360,
        fill=(*PURPLE_LIGHT, 100), width=6,
    )
    # Bottom edge
    od2.arc(
        [bell_cx - bw // 2, bell_cy - 20,
         bell_cx + bw // 2, bell_cy + 40],
        start=0, end=180,
        fill=(*PURPLE_LIGHT, 80), width=5,
    )

    img = Image.alpha_composite(img, outline)

    return img


def generate_icns(img, output_dir):
    """Generate .icns file from PIL image."""
    import subprocess

    iconset_dir = output_dir / "AppIcon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    for name, size in sizes.items():
        resized = img.resize((size, size), Image.LANCZOS)
        resized.save(iconset_dir / name, "PNG")

    icns_path = output_dir / "AppIcon.icns"
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"iconutil error: {result.stderr}")
        img.save(output_dir / "AppIcon.png", "PNG")
    else:
        print(f"Created: {icns_path}")

    return icns_path


def generate_animated_gif(output_dir, num_frames=12, frame_duration_ms=150):
    """Generate animated GIF of jellyfish."""
    frames = []
    for i in range(num_frames):
        phase = i / num_frames
        print(f"  Frame {i + 1}/{num_frames}...")
        frame = create_jellyfish_icon(frame_phase=phase)
        rgb = Image.new("RGB", (SIZE, SIZE), (30, 15, 50))
        rgb.paste(frame, mask=frame.split()[3])
        frames.append(rgb)

    gif_path = output_dir / "jellyfish_animated.gif"
    frames[0].save(
        gif_path, save_all=True, append_images=frames[1:],
        duration=frame_duration_ms, loop=0,
    )
    print(f"Animated GIF: {gif_path}")
    return gif_path


def main():
    print("=" * 50)
    print("  FOL Jellyfish Icon Generator v3.0")
    print("  Purple light, clean flat style")
    print("=" * 50)

    print("\n[1/3] Generating static icon...")
    img = create_jellyfish_icon(frame_phase=0.0)
    preview_path = OUTPUT_DIR / "jellyfish_preview.png"
    img.save(preview_path, "PNG")
    print(f"  Preview: {preview_path}")

    print("\n[2/3] Generating .icns...")
    icns_path = generate_icns(img, OUTPUT_DIR)

    print("\n[3/3] Generating animated GIF...")
    gif_path = generate_animated_gif(OUTPUT_DIR)

    # Copy to project root
    root_png = OUTPUT_DIR.parent.parent / "AppIcon.png"
    img.save(root_png, "PNG")
    print(f"  Root PNG: {root_png}")

    print("\n" + "=" * 50)
    print("  Done!")
    print("=" * 50)


if __name__ == "__main__":
    main()
