import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from .config import PRODUCTS_DIR
from .seo_hashtags import generate_tags_and_hashtags


HTML_WRAPPER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      line-height: 1.65;
      color: #1e293b;
      max-width: 820px;
      margin: 40px auto;
      padding: 0 24px;
    }}
    h1, h2, h3 {{ color: #0f172a; }}
    h1 {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; }}
    code {{
      background: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.92em;
    }}
    pre {{
      background: #0f172a;
      color: #f8fafc;
      padding: 16px;
      border-radius: 8px;
      overflow-x: auto;
    }}
    pre code {{ background: transparent; color: inherit; padding: 0; }}
    blockquote {{
      border-left: 4px solid #6366f1;
      background: #f8fafc;
      margin: 16px 0;
      padding: 12px 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 10px 12px;
      text-align: left;
    }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _render_markdown_to_html(md_text: str) -> str:
    try:
        import markdown
        return markdown.markdown(md_text, extensions=["extra", "tables", "fenced_code"])
    except ImportError:
        pass

    lines = md_text.splitlines()
    out = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{_inline_md(stripped[2:])}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline_md(stripped[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_inline_md(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline_md(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


class ProductBuilder:
    """Scaffolds, compiles, and packages digital products for Gumroad."""

    def __init__(self):
        PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

    def get_product_dir(self, slug: str) -> Path:
        return PRODUCTS_DIR / slug

    def scaffold_product(
        self,
        slug: str,
        name: str,
        price_cents: int = 1200,
        native_type: str = "digital",
        summary: str = "",
        tags: Optional[list] = None,
        category: str = "software",
    ) -> Path:
        """Create a new product workspace folder with manifest, sales copy, and deliverable directories."""
        prod_dir = self.get_product_dir(slug)
        (prod_dir / "deliverables").mkdir(parents=True, exist_ok=True)
        (prod_dir / "assets").mkdir(parents=True, exist_ok=True)
        (prod_dir / "dist").mkdir(parents=True, exist_ok=True)

        custom_summary = summary or f"Instant access to {name}."
        discover_tags, hashtags = generate_tags_and_hashtags(
            name=name,
            slug=slug,
            summary=custom_summary,
            existing_tags=tags,
        )

        manifest = {
            "slug": slug,
            "name": name,
            "price_cents": price_cents,
            "suggested_price_cents": price_cents + 500 if price_cents == 0 else None,
            "customizable_price": price_cents == 0,
            "currency": "usd",
            "native_type": native_type,
            "custom_permalink": slug,
            "custom_summary": custom_summary,
            "category": category,
            "tags": discover_tags,
            "hashtags": hashtags,
            "gumroad_product_id": None,
            "gumroad_short_url": None,
            "published": False,
        }

        manifest_path = prod_dir / "manifest.json"
        if not manifest_path.exists():
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

        copy_path = prod_dir / "sales_copy.md"
        if not copy_path.exists():
            copy_path.write_text(
                f"# {name}\n\n"
                f"**Stop wasting hours starting from scratch.** Get the complete, ready-to-use **{name}**.\n\n"
                "### What You'll Get Inside\n"
                "- **Complete Core Guide & Playbook** (Styled HTML & Markdown)\n"
                "- **Copy-Paste Templates, Checklists & Prompts**\n"
                "- **Lifetime Updates Included**\n\n"
                "### Who This Is For\n"
                "- Creators, developers, and operators looking for immediate, actionable templates.\n",
                encoding="utf-8",
            )

        sample_deliverable = prod_dir / "deliverables" / "01_Main_Guide.md"
        if not sample_deliverable.exists():
            sample_deliverable.write_text(
                f"# {name} — Complete Guide & Resource Pack\n\n"
                "Welcome! This package contains your complete templates, workflows, and step-by-step instructions.\n",
                encoding="utf-8",
            )

        return prod_dir

    def build_product(self, slug: str) -> Dict[str, Any]:
        """Compile Markdown deliverables into styled HTML, enrich SEO tags & hashtags, and create a release ZIP."""
        prod_dir = self.get_product_dir(slug)
        manifest_path = prod_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Product '{slug}' not found at {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        deliverables_dir = prod_dir / "deliverables"
        dist_dir = prod_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)

        # Enrich Gumroad Discover tags and SEO hashtags automatically
        discover_tags, hashtags = generate_tags_and_hashtags(
            name=manifest.get("name", ""),
            slug=slug,
            summary=manifest.get("custom_summary", ""),
            existing_tags=manifest.get("tags", []),
        )
        manifest["tags"] = discover_tags
        manifest["hashtags"] = hashtags
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        # 1. Convert sales_copy.md -> dist/description.html (with SEO Hashtag block appended)
        sales_copy_md = (prod_dir / "sales_copy.md").read_text(encoding="utf-8")
        hashtag_line = " ".join(hashtags)
        if hashtag_line and hashtag_line not in sales_copy_md:
            full_sales_md = f"{sales_copy_md.rstrip()}\n\n---\n\n**Search Tags & Topics:** `{hashtag_line}`\n"
        else:
            full_sales_md = sales_copy_md

        description_html = _render_markdown_to_html(full_sales_md)
        desc_html_path = dist_dir / "description.html"
        desc_html_path.write_text(description_html, encoding="utf-8")

        # Save ready-to-post social promo copy with hashtags
        short_url = manifest.get("gumroad_short_url") or f"https://gumroad.com/l/{slug}"
        social_promo_path = dist_dir / "social_promo_hashtags.txt"
        social_promo_path.write_text(
            f"🚀 Just launched: {manifest.get('name')}\n\n"
            f"{manifest.get('custom_summary', '')}\n\n"
            f"👉 Grab it here: {short_url}\n\n"
            f"{hashtag_line}\n",
            encoding="utf-8",
        )

        # 2. Convert any Markdown deliverables to styled standalone HTML guides as well
        compiled_files = []
        for md_file in sorted(deliverables_dir.glob("*.md")):
            raw_md = md_file.read_text(encoding="utf-8")
            body_html = _render_markdown_to_html(raw_md)
            full_html = HTML_WRAPPER_TEMPLATE.format(title=manifest["name"], body=body_html)
            html_out = deliverables_dir / f"{md_file.stem}.html"
            html_out.write_text(full_html, encoding="utf-8")
            compiled_files.append(str(html_out))

        # 3. Package all files in deliverables/ into dist/<slug>-bundle.zip
        zip_path = dist_dir / f"{slug}-bundle.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(deliverables_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.relative_to(deliverables_dir))

        return {
            "slug": slug,
            "description_html_path": str(desc_html_path),
            "social_promo_path": str(social_promo_path),
            "bundle_zip_path": str(zip_path),
            "compiled_html_guides": compiled_files,
            "tags": discover_tags,
            "hashtags": hashtags,
        }
