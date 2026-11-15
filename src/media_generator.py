import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from .config import get_gemini_api_key

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageFont = None  # type: ignore


def _hex_to_rgb(hex_color: str, default: Tuple[int, int, int] = (99, 102, 241)) -> Tuple[int, int, int]:
    clean = (hex_color or "").strip().lstrip("#")
    if len(clean) == 6:
        try:
            return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
        except ValueError:
            pass
    return default


def _load_font(size: int, bold: bool = False) -> Any:
    candidates = (
        [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        test_line = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _create_cyber_canvas(
    width: int,
    height: int,
    accent_rgb: Tuple[int, int, int],
    secondary_rgb: Tuple[int, int, int],
) -> Any:
    base = Image.new("RGBA", (width, height), (11, 15, 29, 255))
    draw = ImageDraw.Draw(base)

    # Subtle cyber grid
    grid_spacing = 48
    for x in range(0, width, grid_spacing):
        draw.line([(x, 0), (x, height)], fill=(30, 41, 59, 95), width=1)
    for y in range(0, height, grid_spacing):
        draw.line([(0, y), (width, y)], fill=(30, 41, 59, 95), width=1)

    # Ambient glowing orbs
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    g_draw.ellipse(
        [(-int(width * 0.15), -int(height * 0.25)), (int(width * 0.55), int(height * 0.65))],
        fill=(*accent_rgb, 95),
    )
    g_draw.ellipse(
        [(int(width * 0.45), int(height * 0.30)), (int(width * 1.15), int(height * 1.15))],
        fill=(*secondary_rgb, 85),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=90))
    combined = Image.alpha_composite(base, glow)
    return combined.convert("RGB")


class MediaGenerator:
    """Generates 16:9 Cover Images and 1:1 Square Thumbnails for Gumroad products."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_gemini_api_key()

    def _try_gemini_imagen(self, prompt: str, aspect_ratio: str = "16:9") -> Optional[Any]:
        """Attempt optional Imagen 3 generation via Gemini API if enabled on the key."""
        if not self.api_key:
            return None
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"imagen-3.0-generate-002:predict?key={self.api_key}"
        )
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
        }
        try:
            resp = requests.post(url, json=payload, timeout=45)
            if not resp.ok:
                return None
            preds = resp.json().get("predictions", [])
            if preds and "bytesBase64Encoded" in preds[0]:
                raw_bytes = base64.b64decode(preds[0]["bytesBase64Encoded"])
                return Image.open(BytesIO(raw_bytes)).convert("RGB")
        except Exception:
            return None
        return None

    def generate_cover_and_thumbnail(
        self,
        prod_dir: Path,
        blueprint: Dict[str, Any],
    ) -> Dict[str, str]:
        assets_dir = prod_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        cover_path = assets_dir / "cover.jpg"
        thumb_path = assets_dir / "thumbnail.jpg"

        theme = blueprint.get("visual_theme", {}) or {}
        accent_rgb = _hex_to_rgb(theme.get("accent_hex", "#6366f1"), (99, 102, 241))
        secondary_rgb = _hex_to_rgb(theme.get("secondary_hex", "#06b6d4"), (6, 182, 212))

        cover_img = self._render_cover_16x9(blueprint, accent_rgb, secondary_rgb)
        cover_img.save(cover_path, format="JPEG", quality=95)

        thumb_img = self._render_thumbnail_1x1(blueprint, accent_rgb, secondary_rgb)
        thumb_img.save(thumb_path, format="JPEG", quality=95)

        return {
            "cover_path": str(cover_path),
            "thumbnail_path": str(thumb_path),
        }

    def _render_cover_16x9(
        self,
        blueprint: Dict[str, Any],
        accent_rgb: Tuple[int, int, int],
        secondary_rgb: Tuple[int, int, int],
    ) -> Any:
        width, height = 1280, 720
        img = _create_cyber_canvas(width, height, accent_rgb, secondary_rgb)
        draw = ImageDraw.Draw(img)

        theme = blueprint.get("visual_theme", {}) or {}
        badge_text = (theme.get("badge_text") or "INSTANT ACCESS DIGITAL VAULT").upper()
        title = blueprint.get("name", "Ultimate AI Digital Product Vault")
        summary = blueprint.get("custom_summary", "")
        pills = theme.get("feature_pills") or [
            "Complete Step-by-Step Playbook (HTML & MD)",
            "Copy-Paste Templates, Prompts & Workflows",
            "Production-Ready System Checklists",
        ]

        # Outer frame border
        draw.rounded_rectangle(
            [(28, 28), (width - 28, height - 28)],
            radius=24,
            outline=(51, 65, 85),
            width=2,
        )

        # Top badge pill
        font_badge = _load_font(18, bold=True)
        badge_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        badge_w = (badge_bbox[2] - badge_bbox[0]) + 36
        draw.rounded_rectangle(
            [(72, 68), (72 + badge_w, 110)],
            radius=20,
            fill=(15, 23, 42),
            outline=accent_rgb,
            width=2,
        )
        draw.text((90, 78), badge_text, font=font_badge, fill=(226, 232, 240))

        # Main Title (Left column)
        font_title = _load_font(50, bold=True)
        title_lines = _wrap_text(draw, title, font_title, max_width=680)[:3]
        y_cursor = 140
        for line in title_lines:
            draw.text((72, y_cursor), line, font=font_title, fill=(248, 250, 252))
            y_cursor += 62

        # Subtitle / summary
        font_sub = _load_font(23, bold=False)
        sub_lines = _wrap_text(draw, summary, font_sub, max_width=670)[:3]
        y_cursor += 16
        for line in sub_lines:
            draw.text((72, y_cursor), line, font=font_sub, fill=(148, 163, 184))
            y_cursor += 34

        # Feature Pills at bottom left
        font_pill = _load_font(20, bold=True)
        y_pill = max(y_cursor + 28, 490)
        for pill in pills[:3]:
            if y_pill + 48 > height - 48:
                break
            draw.rounded_rectangle(
                [(72, y_pill), (740, y_pill + 44)],
                radius=12,
                fill=(15, 23, 42),
                outline=(51, 65, 85),
                width=2,
            )
            draw.ellipse([(90, y_pill + 14), (106, y_pill + 30)], fill=secondary_rgb)
            draw.text((120, y_pill + 10), pill[:52], font=font_pill, fill=(241, 245, 249))
            y_pill += 56

        # Right-hand 3D UI Mockup Card
        card_x1, card_y1, card_x2, card_y2 = 800, 96, 1208, 624
        draw.rounded_rectangle(
            [(card_x1, card_y1), (card_x2, card_y2)],
            radius=22,
            fill=(15, 23, 42),
            outline=accent_rgb,
            width=3,
        )
        # Window controls bar
        draw.ellipse([(card_x1 + 24, card_y1 + 22), (card_x1 + 38, card_y1 + 36)], fill=(239, 68, 68))
        draw.ellipse([(card_x1 + 48, card_y1 + 22), (card_x1 + 62, card_y1 + 36)], fill=(245, 158, 11))
        draw.ellipse([(card_x1 + 72, card_y1 + 22), (card_x1 + 86, card_y1 + 36)], fill=(16, 185, 129))

        font_card_hdr = _load_font(18, bold=True)
        draw.text((card_x1 + 105, card_y1 + 18), "INCLUDED MODULES", font=font_card_hdr, fill=(148, 163, 184))
        draw.line([(card_x1, card_y1 + 54), (card_x2, card_y1 + 54)], fill=(51, 65, 85), width=2)

        modules = blueprint.get("modules") or []
        font_mod_title = _load_font(18, bold=True)
        font_mod_tag = _load_font(14, bold=False)
        mod_y = card_y1 + 78
        for idx, mod in enumerate(modules[:4], start=1):
            draw.rounded_rectangle(
                [(card_x1 + 24, mod_y), (card_x2 - 24, mod_y + 96)],
                radius=14,
                fill=(30, 41, 59),
                outline=(71, 85, 105),
                width=1,
            )
            draw.text(
                (card_x1 + 40, mod_y + 14),
                f"MODULE 0{idx}",
                font=font_mod_tag,
                fill=secondary_rgb,
            )
            clean_m_title = mod.get("title", f"Module {idx}").replace(f"Module {idx}:", "").strip()
            wrapped_m = _wrap_text(draw, clean_m_title, font_mod_title, max_width=325)[:2]
            my = mod_y + 36
            for ml in wrapped_m:
                draw.text((card_x1 + 40, my), ml, font=font_mod_title, fill=(248, 250, 252))
                my += 24
            mod_y += 110

        return img

    def _render_thumbnail_1x1(
        self,
        blueprint: Dict[str, Any],
        accent_rgb: Tuple[int, int, int],
        secondary_rgb: Tuple[int, int, int],
    ) -> Any:
        size = 1000
        img = _create_cyber_canvas(size, size, accent_rgb, secondary_rgb)
        draw = ImageDraw.Draw(img)

        theme = blueprint.get("visual_theme", {}) or {}
        badge_text = (theme.get("badge_text") or "DIGITAL VAULT").upper()
        title = blueprint.get("name", "AI Workflow Pack")
        pills = theme.get("feature_pills") or [
            "Copy-Paste Prompts & Rules",
            "Complete HTML + MD Guides",
            "Instant .ZIP Download",
        ]

        # Outer high-contrast border for Gumroad Discover grid visibility
        draw.rounded_rectangle(
            [(24, 24), (size - 24, size - 24)],
            radius=32,
            outline=accent_rgb,
            width=4,
        )

        # Top badge
        font_badge = _load_font(24, bold=True)
        bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        bw = (bbox[2] - bbox[0]) + 48
        bx = (size - bw) // 2
        draw.rounded_rectangle(
            [(bx, 76), (bx + bw, 132)],
            radius=28,
            fill=(15, 23, 42),
            outline=secondary_rgb,
            width=3,
        )
        draw.text((bx + 24, 89), badge_text, font=font_badge, fill=(248, 250, 252))

        # Big bold centered title
        font_title = _load_font(62, bold=True)
        lines = _wrap_text(draw, title, font_title, max_width=840)[:4]
        y_cursor = 185
        for line in lines:
            lb = draw.textbbox((0, 0), line, font=font_title)
            lw = lb[2] - lb[0]
            draw.text(((size - lw) // 2, y_cursor), line, font=font_title, fill=(255, 255, 255))
            y_cursor += 76

        # Feature cards at bottom
        font_pill = _load_font(28, bold=True)
        y_card = max(y_cursor + 40, 560)
        for pill in pills[:3]:
            if y_card + 90 > size - 60:
                break
            draw.rounded_rectangle(
                [(80, y_card), (size - 80, y_card + 78)],
                radius=18,
                fill=(15, 23, 42),
                outline=(71, 85, 105),
                width=2,
            )
            draw.ellipse([(112, y_card + 25), (140, y_card + 53)], fill=secondary_rgb)
            draw.text((164, y_card + 21), pill[:40], font=font_pill, fill=(241, 245, 249))
            y_card += 96

        return img
