import json
import re
from pathlib import Path
from typing import Any, Dict, List
from .config import PRODUCTS_DIR, get_settings
from .gemini_generator import GeminiContentGenerator
from .gumroad_client import GumroadAPIError, GumroadClient
from .media_generator import MediaGenerator
from .product_builder import ProductBuilder
from .trend_scanner import TrendScanner


def _sanitize_slug(raw_slug: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", raw_slug.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48].strip("-") or "ai-digital-vault"


def publish_product_by_slug(slug: str, live: bool = True) -> Dict[str, Any]:
    """Build, upload deliverables/cover/thumbnail, embed rich_content, and publish a product slug."""
    builder = ProductBuilder()
    build_info = builder.build_product(slug)
    prod_dir = builder.get_product_dir(slug)
    manifest_path = prod_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    description_html = Path(build_info["description_html_path"]).read_text(encoding="utf-8")

    client = GumroadClient()
    product_id = manifest.get("gumroad_product_id")

    # 1. Upload deliverable bundle ZIP using Gumroad's native /v2/files/presign -> /v2/files/complete flow
    bundle_zip_path = Path(build_info["bundle_zip_path"])
    gumroad_file_url = manifest.get("gumroad_file_url")
    if not gumroad_file_url and bundle_zip_path.exists():
        gumroad_file_url = client.upload_product_file(bundle_zip_path)
        manifest["gumroad_file_url"] = gumroad_file_url

    file_urls = [gumroad_file_url] if gumroad_file_url else []

    if not product_id:
        existing_products = client.list_products()
        for p in existing_products:
            if p.get("name") == manifest["name"] or p.get("custom_permalink") == manifest.get("custom_permalink"):
                product_id = p.get("id")
                manifest["gumroad_product_id"] = product_id
                manifest["gumroad_short_url"] = p.get("short_url")
                break

    if not product_id:
        created = client.create_product(
            name=manifest["name"],
            price_cents=int(manifest["price_cents"]),
            description_html=description_html,
            custom_summary=manifest.get("custom_summary", ""),
            custom_permalink=manifest.get("custom_permalink"),
            native_type=manifest.get("native_type", "digital"),
            currency=manifest.get("currency", "usd"),
            customizable_price=bool(manifest.get("customizable_price", False)),
            suggested_price_cents=manifest.get("suggested_price_cents"),
            tags=manifest.get("tags", []),
            file_urls=file_urls,
        )
        product_id = created.get("id")
        manifest["gumroad_product_id"] = product_id
        manifest["gumroad_short_url"] = created.get("short_url")
    else:
        created = client.update_product(
            product_id,
            name=manifest["name"],
            price=int(manifest["price_cents"]),
            description=description_html,
            custom_summary=manifest.get("custom_summary", ""),
            custom_permalink=manifest.get("custom_permalink"),
            tags=manifest.get("tags", []),
            file_urls=file_urls,
        )

    # 1b. Embed the attached deliverable file directly onto the Gumroad Content tab (`rich_content` fileEmbed)
    rich_content_status = "skipped"
    if product_id and gumroad_file_url:
        welcome_msg = (
            f"Thank you for downloading {manifest['name']}! "
            "Click the bundle below to download all HTML guides and Markdown templates."
        )
        updated_prod = client.sync_rich_content_files(
            product_id=product_id,
            gumroad_file_url=gumroad_file_url,
            display_name=f"{manifest['name']} (Complete Bundle .ZIP)",
            welcome_text=welcome_msg,
        )
        rich_content_status = f"embedded ({len(updated_prod.get('rich_content', []))} page)"

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    assets_dir = prod_dir / "assets"

    # 2. Upload 16:9 Cover image if not already uploaded
    cover_status = "already_uploaded" if manifest.get("cover_uploaded") else "skipped"
    if not manifest.get("cover_uploaded"):
        for cover_candidate in ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp"):
            cover_file = assets_dir / cover_candidate
            if cover_file.exists():
                client.upload_cover(product_id, str(cover_file))
                manifest["cover_uploaded"] = True
                cover_status = f"uploaded ({cover_candidate})"
                break

    # 3. Upload 1:1 Square Thumbnail image if not already uploaded
    thumbnail_status = "already_uploaded" if manifest.get("thumbnail_uploaded") else "skipped"
    if not manifest.get("thumbnail_uploaded"):
        for thumb_candidate in (
            "thumbnail.png",
            "thumbnail.jpg",
            "thumbnail.jpeg",
            "thumbnail.webp",
            "cover.png",
            "cover.jpg",
        ):
            thumb_file = assets_dir / thumb_candidate
            if thumb_file.exists():
                thumb_resp = client.upload_thumbnail(product_id, str(thumb_file))
                manifest["thumbnail_uploaded"] = True
                manifest["thumbnail_url"] = thumb_resp.get("thumbnail", {}).get("url")
                thumbnail_status = f"uploaded ({thumb_candidate})"
                break

    publish_warning = None
    if live and product_id:
        try:
            published_obj = client.set_published(product_id, True)
            manifest["published"] = published_obj.get("published", True)
        except GumroadAPIError as exc:
            manifest["published"] = created.get("published", False)
            publish_warning = str(exc)
    else:
        manifest["published"] = created.get("published", False)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "status": "published" if manifest["published"] else "draft_synced",
        "slug": slug,
        "name": manifest["name"],
        "gumroad_product_id": product_id,
        "short_url": manifest.get("gumroad_short_url"),
        "bundle_zip": build_info["bundle_zip_path"],
        "gumroad_file_url": gumroad_file_url,
        "rich_content_status": rich_content_status,
        "cover_status": cover_status,
        "thumbnail_status": thumbnail_status,
        "thumbnail_url": manifest.get("thumbnail_url"),
        "tags": manifest.get("tags", []),
        "hashtags": manifest.get("hashtags", []),
        "publish_warning": publish_warning,
    }


def run_autonomous_cycle(count: int = 1, live: bool = True, categories: List[str] | None = None) -> Dict[str, Any]:
    """Full autonomous pipeline: Scan Trends -> Gemini Ideation -> Author Content -> Render Media -> Publish."""
    client = GumroadClient()
    scanner = TrendScanner()
    builder = ProductBuilder()
    gemini = GeminiContentGenerator()
    media = MediaGenerator()

    # 1. Gather existing products from Gumroad + local workspace so we never duplicate
    existing_identifiers: List[str] = []
    try:
        remote_products = client.list_products()
        for rp in remote_products:
            existing_identifiers.append(f"{rp.get('name')} ({rp.get('short_url')})")
    except Exception:
        pass

    if PRODUCTS_DIR.exists():
        for p_dir in PRODUCTS_DIR.iterdir():
            if p_dir.is_dir() and not p_dir.name.startswith("_"):
                existing_identifiers.append(p_dir.name)

    # 2. Scan trending Gumroad Discover categories
    target_categories = categories or list(get_settings().get("discover_categories", {}).keys()) or [
        "software",
        "business",
        "design",
        "education",
    ]
    trend_reports = []
    for cat in target_categories:
        report = scanner.scan_category(cat)
        trend_reports.append(
            {
                "category": cat,
                "label": report.get("category_label"),
                "seed_keywords": report.get("seed_keywords", []),
                "top_discovered": report.get("discovered_products", [])[:12],
            }
        )

    # 3. Ideate non-duplicate trending product blueprints with Gemini
    blueprints = gemini.ideate_trending_products(
        trend_reports=trend_reports,
        existing_slugs_and_names=existing_identifiers,
        count=count,
    )

    published_results = []
    for bp in blueprints:
        slug = _sanitize_slug(bp.get("slug", bp.get("name", "ai-vault")))
        bp["slug"] = slug
        name = bp.get("name", "Ultimate AI Workflow Vault")
        price_cents = int(bp.get("price_cents", 1900))
        summary = bp.get("custom_summary", f"Complete playbook and templates for {name}.")
        tags = bp.get("tags", [])
        category = bp.get("category", "software")

        # 4. Scaffold product workspace
        prod_dir = builder.scaffold_product(
            slug=slug,
            name=name,
            price_cents=price_cents,
            native_type="digital",
            summary=summary,
            tags=tags,
            category=category,
        )

        # Remove default sample deliverable if present
        sample_file = prod_dir / "deliverables" / "01_Main_Guide.md"
        if sample_file.exists():
            sample_file.unlink()

        # 5. Author Sales Copy via Gemini
        sales_copy_md = gemini.generate_sales_copy(bp)
        (prod_dir / "sales_copy.md").write_text(sales_copy_md, encoding="utf-8")

        # 6. Author all Deliverable Modules via Gemini
        modules = bp.get("modules") or [
            {
                "filename": "01_Master_Playbook_and_Architecture.md",
                "title": f"Module 1: {name} Master Playbook",
                "description": "Core architecture, mental models, and step-by-step execution guide.",
            },
            {
                "filename": "02_Copy_Paste_Templates_and_Prompts.md",
                "title": "Module 2: Ready-to-Use Templates & Prompts",
                "description": "Production-ready templates, prompts, and configurations.",
            },
        ]
        for idx, mod in enumerate(modules, start=1):
            raw_fname = mod.get("filename") or f"0{idx}_Module_{idx}.md"
            safe_fname = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_fname)
            if not safe_fname.endswith(".md"):
                safe_fname += ".md"
            mod_content = gemini.generate_deliverable_module(bp, mod)
            (prod_dir / "deliverables" / safe_fname).write_text(mod_content, encoding="utf-8")

        # 7. Generate 16:9 Cover Image and 1:1 Square Thumbnail
        media.generate_cover_and_thumbnail(prod_dir, bp)

        # 8. Build & Publish to Gumroad
        pub_result = publish_product_by_slug(slug=slug, live=live)
        published_results.append(pub_result)

    return {
        "status": "completed",
        "scanned_categories": target_categories,
        "products_processed": len(published_results),
        "results": published_results,
    }

