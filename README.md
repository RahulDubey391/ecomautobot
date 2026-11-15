# Gumroad Autonomous Content Agent (`ecomautobot`)

An end-to-end autonomous pipeline powered by **Gemini** and **GitHub Actions** that runs **twice a day** to:
1. **Scan Trending Digital Products** across Gumroad Discover (`software`, `business`, `design`, `education`).
2. **Ideate High-Converting Products** via Gemini (`gemini-2.5-flash` / `gemini-2.0-flash`) while avoiding duplicates in your store.
3. **Author Multi-Module Deliverables & Sales Copy** (4 comprehensive Markdown & styled HTML playbooks, templates, prompts, and checklists + `sales_copy.md`).
4. **Render Storefront Graphics & SEO Hashtags** (16:9 `cover.jpg`, 1:1 square `thumbnail.jpg`, 10 Gumroad Discover tags, and 15 social reach hashtags).
5. **Publish Live to Gumroad** (uploads the `.zip` bundle via Gumroad's native S3 multipart presign API, embeds the file on the Content tab via `rich_content`, attaches the cover & thumbnail, enables the product live, commits the catalog update, and exits).

---

## GitHub Actions Setup (2x Daily Automation)

The workflow in [`.github/workflows/gumroad_auto_agent.yml`](.github/workflows/gumroad_auto_agent.yml) runs automatically twice a day (`03:30 UTC` / `9:00 AM IST` and `15:30 UTC` / `9:00 PM IST`) and also supports 1-click manual triggers via **Workflow Dispatch**.

### Required GitHub Repository Secrets
Go to your GitHub repository → **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Description |
| :--- | :--- |
| `GUMROAD_ACCESS_TOKEN` | Your Gumroad API v2 Access Token (from Gumroad **Settings → Advanced → Applications**) |
| `GEMINI_API_KEY` | Your Google Gemini API Key (from [Google AI Studio](https://aistudio.google.com/app/apikey)) |

*(Optional Repository Variable)*: Set `GEMINI_MODEL` (defaults to `gemini-2.5-flash` with automatic fallback to `gemini-2.0-flash` and `gemini-2.5-pro`).

---

## CLI Commands (Local & CI Execution)

```bash
# Install dependencies
pip install -r requirements.txt

# 1. Verify Gumroad account connection
python -m src.cli verify

# 2. Run the full autonomous pipeline (Scan Trends -> Gemini Author -> Cover/Thumbnail -> Publish Live)
python -m src.cli auto-run --count 1 --live

# 3. Individual pipeline commands
python -m src.cli list-products
python -m src.cli scan-trends --category software
python -m src.cli build --slug "ai-coding-cursor-rules-pack"
python -m src.cli publish --slug "ai-coding-cursor-rules-pack" --live
```
