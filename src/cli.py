import argparse
import json
import sys
from pathlib import Path
from .auto_pipeline import publish_devto_post_for_slug, publish_product_by_slug, run_autonomous_cycle
from .config import is_auto_publish_enabled, ENV_PATH
from .devto_client import DevToAPIError
from .gemini_generator import GeminiGeneratorError
from .gumroad_client import GumroadAPIError, GumroadClient
from .product_builder import ProductBuilder
from .trend_scanner import TrendScanner


def cmd_verify(_args: argparse.Namespace) -> None:
    client = GumroadClient()
    user = client.verify_user()
    print(json.dumps({"status": "authenticated", "user": user}, indent=2))


def cmd_oauth_url(_args: argparse.Namespace) -> None:
    url = GumroadClient.build_oauth_authorize_url()
    print(json.dumps({"oauth_authorize_url": url}, indent=2))


def cmd_exchange_code(args: argparse.Namespace) -> None:
    payload = GumroadClient.exchange_oauth_code(args.code)
    token = payload["access_token"]
    env_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if "GUMROAD_ACCESS_TOKEN=" in env_text:
        lines = [
            f"GUMROAD_ACCESS_TOKEN={token}" if l.startswith("GUMROAD_ACCESS_TOKEN=") else l
            for l in env_text.splitlines()
        ]
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        with open(ENV_PATH, "a", encoding="utf-8") as f:
            f.write(f"\nGUMROAD_ACCESS_TOKEN={token}\n")
    print(json.dumps({"status": "token_saved_to_env"}, indent=2))


def cmd_list_products(_args: argparse.Namespace) -> None:
    client = GumroadClient()
    products = client.list_products()
    summary = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "price_cents": p.get("price"),
            "published": p.get("published"),
            "short_url": p.get("short_url"),
            "thumbnail_url": p.get("thumbnail_url"),
            "preview_url": p.get("preview_url"),
            "tags": p.get("tags", []),
            "file_info": p.get("file_info"),
            "sales_count": p.get("sales_count"),
        }
        for p in products
    ]
    print(json.dumps({"count": len(summary), "products": summary}, indent=2))


def cmd_scan_trends(args: argparse.Namespace) -> None:
    scanner = TrendScanner()
    report = scanner.scan_category(args.category)
    print(json.dumps(report, indent=2))


def cmd_scaffold(args: argparse.Namespace) -> None:
    builder = ProductBuilder()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    prod_dir = builder.scaffold_product(
        slug=args.slug,
        name=args.name,
        price_cents=args.price,
        native_type=args.type,
        summary=args.summary or "",
        tags=tags,
    )
    print(json.dumps({"status": "scaffolded", "product_dir": str(prod_dir)}, indent=2))


def cmd_build(args: argparse.Namespace) -> None:
    builder = ProductBuilder()
    result = builder.build_product(args.slug)
    print(json.dumps({"status": "built", **result}, indent=2))


def cmd_publish(args: argparse.Namespace) -> None:
    should_publish = args.live or is_auto_publish_enabled()
    result = publish_product_by_slug(slug=args.slug, live=should_publish)
    print(json.dumps(result, indent=2))


def cmd_publish_devto(args: argparse.Namespace) -> None:
    result = publish_devto_post_for_slug(slug=args.slug, live=not args.draft)
    print(json.dumps(result, indent=2))


def cmd_auto_run(args: argparse.Namespace) -> None:
    should_publish = args.live or is_auto_publish_enabled()
    categories = [c.strip() for c in args.categories.split(",") if c.strip()] if args.categories else None
    result = run_autonomous_cycle(
        count=args.count,
        live=should_publish,
        categories=categories,
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Gumroad Content Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="Verify Gumroad API token and print account details")
    sub.add_parser("oauth-url", help="Generate OAuth authorization URL from CREDS.txt Application ID")

    p_ex = sub.add_parser("exchange-code", help="Exchange OAuth redirect code for an access token")
    p_ex.add_argument("--code", required=True, help="Authorization code from redirect URL")

    sub.add_parser("list-products", help="List all products in your Gumroad account")

    p_scan = sub.add_parser("scan-trends", help="Scan Gumroad Discover category for trending products")
    p_scan.add_argument("--category", default="software", help="Category key (software, business, design, education)")

    p_scaffold = sub.add_parser("scaffold", help="Scaffold a new digital product directory")
    p_scaffold.add_argument("--slug", required=True, help="URL-friendly product slug")
    p_scaffold.add_argument("--name", required=True, help="Product display title")
    p_scaffold.add_argument("--price", type=int, default=1200, help="Price in cents (e.g. 1200 = $12.00, 0 = Free/PWYW)")
    p_scaffold.add_argument("--type", default="digital", choices=["digital", "ebook", "course", "bundle", "membership"])
    p_scaffold.add_argument("--summary", default="", help="Short summary shown under product price")
    p_scaffold.add_argument("--tags", default="", help="Comma-separated list of discovery tags")

    p_build = sub.add_parser("build", help="Compile product deliverables, HTML descriptions, and release ZIP")
    p_build.add_argument("--slug", required=True, help="Product slug inside products/")

    p_pub = sub.add_parser("publish", help="Sync and publish a built product to Gumroad")
    p_pub.add_argument("--slug", required=True, help="Product slug inside products/")
    p_pub.add_argument("--live", action="store_true", help="Publish live immediately instead of keeping as draft")

    p_devto = sub.add_parser("publish-devto", help="Generate and publish a Dev.to article for a product")
    p_devto.add_argument("--slug", required=True, help="Product slug inside products/")
    p_devto.add_argument("--draft", action="store_true", help="Save as draft on Dev.to instead of publishing live")

    p_auto = sub.add_parser(
        "auto-run",
        help="Autonomous end-to-end run: scan trends -> Gemini ideate & author -> render cover/thumbnail -> publish",
    )
    p_auto.add_argument("--count", type=int, default=1, help="Number of new trending products to create & publish")
    p_auto.add_argument("--categories", default="", help="Optional comma-separated categories to scan")
    p_auto.add_argument("--live", action="store_true", help="Publish live immediately on Gumroad")

    args = parser.parse_args()
    try:
        if args.command == "verify":
            cmd_verify(args)
        elif args.command == "oauth-url":
            cmd_oauth_url(args)
        elif args.command == "exchange-code":
            cmd_exchange_code(args)
        elif args.command == "list-products":
            cmd_list_products(args)
        elif args.command == "scan-trends":
            cmd_scan_trends(args)
        elif args.command == "scaffold":
            cmd_scaffold(args)
        elif args.command == "build":
            cmd_build(args)
        elif args.command == "publish":
            cmd_publish(args)
        elif args.command == "publish-devto":
            cmd_publish_devto(args)
        elif args.command == "auto-run":
            cmd_auto_run(args)
    except (GumroadAPIError, GeminiGeneratorError, DevToAPIError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
