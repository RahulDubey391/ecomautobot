import json
import re
import time
from typing import Any, Dict, List, Optional
import requests
from .config import get_gemini_api_key, get_gemini_model


class GeminiGeneratorError(Exception):
    """Raised when Gemini API generation fails."""


class GeminiContentGenerator:
    """Autonomous Gemini-powered digital product ideator, copywriter, and deliverable author."""

    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    FALLBACK_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or get_gemini_api_key()
        if not self.api_key:
            raise GeminiGeneratorError(
                "Missing GEMINI_API_KEY. Set GEMINI_API_KEY in GitHub Actions Secrets, .env, or CREDS.txt."
            )
        preferred = model or get_gemini_model()
        discovered = self._discover_models()
        base_list = [preferred] + discovered + self.FALLBACK_MODELS
        self.models: List[str] = []
        for m in base_list:
            if m and m not in self.models:
                self.models.append(m)

    def _discover_models(self) -> List[str]:
        """Query the Gemini API for available flash/pro models supporting generateContent."""
        try:
            resp = requests.get(f"{self.API_BASE}?key={self.api_key}", timeout=15)
            if not resp.ok:
                return []
            models_data = resp.json().get("models", [])
            supported = []
            for m in models_data:
                methods = m.get("supportedGenerationMethods", [])
                name = m.get("name", "").replace("models/", "")
                if "generateContent" in methods and "gemini" in name and "vision" not in name and "tts" not in name and "image" not in name:
                    supported.append(name)
            # Prioritize flash models for speed & quota
            flash_models = [m for m in supported if "flash" in m]
            other_models = [m for m in supported if "flash" not in m]
            return flash_models + other_models
        except Exception:
            return []

    def _call_gemini(
        self,
        prompt: str,
        system_instruction: str = "",
        response_mime_type: str = "text/plain",
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
    ) -> str:
        last_error: Optional[str] = None

        for model_name in self.models:
            url = f"{self.API_BASE}/{model_name}:generateContent?key={self.api_key}"
            payload: Dict[str, Any] = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_output_tokens,
                    "responseMimeType": response_mime_type,
                },
            }
            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_instruction}]
                }

            for attempt in range(2):
                try:
                    resp = requests.post(url, json=payload, timeout=120)
                    if resp.status_code == 404:
                        last_error = f"404 Not Found ({model_name}): {resp.text[:200]}"
                        break
                    if resp.status_code == 429:
                        last_error = f"429 Quota/RateLimit ({model_name}): {resp.text[:200]}"
                        time.sleep(3 * (attempt + 1))
                        continue
                    if resp.status_code in (500, 502, 503, 504):
                        last_error = f"{resp.status_code} Server Error ({model_name}): {resp.text[:200]}"
                        time.sleep(3 * (attempt + 1))
                        continue
                    if not resp.ok:
                        last_error = f"{resp.status_code} ({model_name}): {resp.text[:300]}"
                        break
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        last_error = f"Empty candidates ({model_name}): {data}"
                        break
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts).strip()
                    if text:
                        return text
                except Exception as exc:
                    last_error = f"{model_name}: {exc}"
                    time.sleep(2)

        raise GeminiGeneratorError(f"All Gemini models failed. Last error: {last_error}")

    @staticmethod
    def _parse_json_response(raw_text: str) -> Any:
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
            if match:
                return json.loads(match.group(1))
            raise

    def ideate_trending_products(
        self,
        trend_reports: List[Dict[str, Any]],
        existing_slugs_and_names: List[str],
        count: int = 1,
    ) -> List[Dict[str, Any]]:
        """Analyze live Gumroad Discover trend signals and return `count` high-converting product blueprints."""
        system_instruction = (
            "You are an elite digital product strategist and top 0.1% Gumroad creator. "
            "Your job is to analyze live Gumroad Discover market signals and design irresistible, "
            "high-converting digital products (prompt vaults, AI coding rule packs, Notion/SOP playbooks, "
            "automation blueprints, UI/copywriting swipe files, developer cheat sheets) that attract maximum "
            "organic Gumroad Discover traffic, social clicks, and instant impulse sales."
        )

        prompt = f"""Analyze the following live Gumroad Discover trend reports and our existing catalog.
Design {count} brand-new, high-demand digital product(s) that do NOT overlap with or duplicate our existing products.

EXISTING PRODUCTS (DO NOT DUPLICATE THESE TOPICS OR SLUGS):
{json.dumps(existing_slugs_and_names, indent=2)}

LIVE GUMROAD DISCOVER SIGNALS:
{json.dumps(trend_reports, indent=2)[:12000]}

Return a JSON array of {count} product blueprint object(s). Each object MUST strictly follow this JSON structure:
[
  {{
    "slug": "url-friendly-kebab-case-slug-max-45-chars",
    "name": "Clear, Specific Product Title (Vary naming; avoid repeating 'Vault' or '50+ Blueprints')",
    "price_cents": 1500,
    "category": "software",
    "custom_summary": "1-sentence punchy value proposition shown directly under the price on Gumroad.",
    "tags": ["short tag 1", "short tag 2", "max 18 chars each", "ai prompts", "automation", "productivity", "saas", "templates", "workflows", "indie hacker"],
    "hashtags": ["#Tag1", "#Tag2", "#Tag3", "#Tag4", "#Tag5", "#Tag6", "#Tag7", "#Tag8", "#Tag9", "#Tag10", "#Tag11", "#Tag12"],
    "visual_theme": {{
      "accent_hex": "#6366f1",
      "secondary_hex": "#06b6d4",
      "badge_text": "COMPLETE PLAYBOOK & TEMPLATES",
      "short_hook": "4-6 Word Bold Thumbnail Headline",
      "feature_pills": [
        "Copy-Paste Prompts & Workflows",
        "Production-Ready Templates",
        "Step-by-Step Implementation Guide"
      ]
    }},
    "modules": [
      {{
        "filename": "01_Master_Architecture_and_Playbook.md",
        "title": "Module 1: Complete Architecture & Core Playbook",
        "description": "Detailed explanation of frameworks, mental models, and step-by-step setup."
      }},
      {{
        "filename": "02_Copy_Paste_Templates_and_Prompts.md",
        "title": "Module 2: Ready-to-Use Templates, Prompts & Configurations",
        "description": "20+ copy-paste templates, exact prompts, or rule files."
      }},
      {{
        "filename": "03_Advanced_Workflows_and_Automations.md",
        "title": "Module 3: Advanced Workflows, Real-World Case Studies & Blueprints",
        "description": "End-to-end execution blueprints and automation pipelines."
      }},
      {{
        "filename": "04_Checklists_Troubleshooting_and_Swipe_File.md",
        "title": "Module 4: Master Checklists, Audit Rubrics & Reference Swipe File",
        "description": "Actionable checklists, verification rubrics, and quick-reference tables."
      }}
    ]
  }}
]
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.75,
        )
        parsed = self._parse_json_response(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed[:count]

    def generate_sales_copy(self, blueprint: Dict[str, Any]) -> str:
        """Generate high-converting Markdown sales copy (`sales_copy.md`) for the Gumroad storefront."""
        system_instruction = (
            "You are a world-class direct-response copywriter for technical and creator digital products. "
            "Write clean, persuasive, high-converting Gumroad sales page copy in Markdown. "
            "Do NOT wrap the entire response in ```markdown code fences."
        )
        prompt = f"""Write the complete Gumroad storefront `sales_copy.md` for this digital product:

Product Name: {blueprint['name']}
Summary Hook: {blueprint['custom_summary']}
Price: ${blueprint.get('price_cents', 1900) / 100:.2f}
Category: {blueprint.get('category', 'software')}
Modules Included:
{json.dumps(blueprint.get('modules', []), indent=2)}

Structure the Markdown sales copy with:
1. `# {blueprint['name']}`
2. A bold 1-sentence transformation hook right at the top.
3. 2 short paragraphs agitating the problem of starting from scratch vs. having a battle-tested system.
4. `---` divider
5. `### What's Inside the Pack` — detailed bulleted breakdown of each of the 4 modules and specific tangible takeaways.
6. `---` divider
7. `### Who This Is Built For` — 3 to 4 specific buyer personas and how it saves them 20+ hours.
8. `---` divider
9. `### Instant Access & Formats Included` — highlight the Styled HTML Handbook, Raw Markdown Templates, and Complete Release `.zip` Archive.
10. `---` divider
11. `### Quick FAQ & 30-Day Money-Back Guarantee` — include a 30-day no-questions-asked refund guarantee, commercial usage rights, and instant download FAQ.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="text/plain",
            temperature=0.65,
        )
        raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        return raw + "\n"

    def generate_devto_post(
        self,
        blueprint: Dict[str, Any],
        buy_url: str,
        deliverable_snippet: str = "",
    ) -> Dict[str, Any]:
        """Generate a high-value educational Dev.to article with popular tags and a buy CTA."""
        system_instruction = (
            "You are a senior developer advocate and technical writer on Dev.to. "
            "Write genuinely useful, educational technical articles that solve a real engineering problem, "
            "include concrete code/config/workflow examples, and naturally link to the full resource at the end. "
            "Never write clickbait or spammy ad copy—Dev.to readers reward practical value."
        )
        price_cents = int(blueprint.get("price_cents", 0) or 0)
        price_label = "Free ($0+ Pay What You Want)" if price_cents == 0 else f"${price_cents / 100:.0f}"

        prompt = f"""Write a Dev.to article for this developer resource and return valid JSON.

Product Title: {blueprint.get('name', '')}
Summary: {blueprint.get('custom_summary', '')}
Price: {price_label}
Buy / Download Link: {buy_url}
Existing Gumroad Tags: {json.dumps(blueprint.get('tags', []))}
Sample Deliverable Excerpt (use real technical details from this if helpful):
{deliverable_snippet[:2500]}

Return a single JSON object with these exact keys:
{{
  "title": "Practical, developer-focused Dev.to article title (60-90 chars, no emojis, not an ad)",
  "tags": ["tag1", "tag2", "tag3", "tag4"],
  "body_markdown": "Complete 500-800 word Markdown article with: (1) Hook & real technical problem, (2) 2-3 actionable patterns/code blocks/checklists readers can use immediately, (3) Natural CTA section at the end linking to {buy_url} ({price_label}) explaining what else is in the full bundle."
}}

Tag rules (STRICT):
- Exactly 4 tags.
- Lowercase alphanumeric ONLY (no spaces, no hyphens, no #). Pick high-reach Dev.to tags like: ai, programming, webdev, typescript, python, productivity, devops, tutorial, opensource, saas, nextjs, automation.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.7,
        )
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, dict):
            raise GeminiGeneratorError("Gemini returned non-object JSON for Dev.to post.")
        return parsed

    def generate_x_post(
        self,
        blueprint: Dict[str, Any],
        buy_url: str,
    ) -> str:
        """Generate a high-converting <= 270 char X (Twitter) post with hashtags and buy link."""
        system_instruction = (
            "You are a top indie-hacker growth copywriter on X (Twitter). "
            "Write punchy, high-signal posts that hook developers/founders with a concrete problem or takeaway, "
            "include the buy/download link, and end with 2-3 relevant hashtags. "
            "STRICT LIMIT: Total post MUST be 270 characters or fewer (including the URL and hashtags)."
        )
        price_cents = int(blueprint.get("price_cents", 0) or 0)
        price_label = "Free ($0+)" if price_cents == 0 else f"${price_cents / 100:.0f}"

        prompt = f"""Write a single X (Twitter) post (MAX 270 characters total) for this digital product:

Product: {blueprint.get('name', '')}
Summary: {blueprint.get('custom_summary', '')}
Price: {price_label}
Link: {buy_url}
Suggested Hashtags: {json.dumps(blueprint.get('hashtags', [])[:5])}

Requirements:
- Hook with a specific pain point or concrete benefit in 1 short line.
- Include the exact link: {buy_url}
- Include 2-3 high-reach hashtags (e.g. #AI #TypeScript #IndieHackers).
- MUST be <= 270 characters total. Return ONLY the raw tweet text, no quotes or markdown fences.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="text/plain",
            temperature=0.7,
        )
        tweet = raw.strip().strip('"').strip("'")
        if buy_url not in tweet:
            tweet = f"{tweet[:210].rstrip()} {buy_url}"
        if len(tweet) > 280:
            # Preserve buy_url at the end if slightly over 280
            without_url = tweet.replace(buy_url, "").strip()
            max_prefix = 280 - len(buy_url) - 1
            tweet = f"{without_url[:max_prefix].rstrip()} {buy_url}"
        return tweet



    def generate_deliverable_module(
        self,
        blueprint: Dict[str, Any],
        module_spec: Dict[str, Any],
    ) -> str:
        """Generate a deep, comprehensive, production-grade Markdown deliverable guide for a module."""
        system_instruction = (
            "You are a senior practitioner and technical author creating a paid digital product deliverable. "
            "Never write shallow summaries or '[insert here]' placeholders. Write complete, exhaustive, "
            "copy-pasteable templates, concrete code/prompt blocks, tables, and step-by-step instructions "
            "that immediately justify the customer's purchase."
        )
        prompt = f"""Write the complete, exhaustive Markdown deliverable file `{module_spec['filename']}` for the paid digital product **{blueprint['name']}**.

Module Title: {module_spec['title']}
Module Focus: {module_spec['description']}
Overall Product Summary: {blueprint['custom_summary']}

Requirements:
- Must be 1,000 to 2,000+ words of dense, immediately actionable content.
- Include concrete copy-paste code blocks, system prompts, checklists, configuration templates, and Markdown tables.
- Use zero placeholders or generic filler — every template or prompt must be 100% complete and ready to use in production.
- Do NOT wrap the entire document in outer ```markdown fences; start directly with `# {module_spec['title']}`.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="text/plain",
            temperature=0.6,
            max_output_tokens=8192,
        )
        raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        return raw + "\n"

    def generate_devto_post(
        self,
        blueprint: Dict[str, Any],
        buy_url: str,
        deliverable_snippet: str = "",
    ) -> Dict[str, Any]:
        """Generate a high-value educational Dev.to article with popular tags and a buy CTA."""
        system_instruction = (
            "You are a senior developer advocate and technical writer on Dev.to. "
            "Write genuinely useful, educational technical articles that solve a real engineering problem, "
            "include concrete code/config/workflow examples, and naturally link to the full resource at the end. "
            "Never write clickbait or spammy ad copy—Dev.to readers reward practical value."
        )
        price_cents = int(blueprint.get("price_cents", 0) or 0)
        price_label = "Free ($0+ Pay What You Want)" if price_cents == 0 else f"${price_cents / 100:.0f}"

        prompt = f"""Write a Dev.to article for this developer resource and return valid JSON.

Product Title: {blueprint.get('name', '')}
Summary: {blueprint.get('custom_summary', '')}
Price: {price_label}
Buy / Download Link: {buy_url}
Existing Gumroad Tags: {json.dumps(blueprint.get('tags', []))}
Sample Deliverable Excerpt (use real technical details from this if helpful):
{deliverable_snippet[:2500]}

Return a single JSON object with these exact keys:
{{
  "title": "Practical, developer-focused Dev.to article title (60-90 chars, no emojis, not an ad)",
  "tags": ["tag1", "tag2", "tag3", "tag4"],
  "body_markdown": "Complete 500-800 word Markdown article with: (1) Hook & real technical problem, (2) 2-3 actionable patterns/code blocks/checklists readers can use immediately, (3) Natural CTA section at the end linking to {buy_url} ({price_label}) explaining what else is in the full bundle."
}}

Tag rules (STRICT):
- Exactly 4 tags.
- Lowercase alphanumeric ONLY (no spaces, no hyphens, no #). Pick high-reach Dev.to tags like: ai, programming, webdev, typescript, python, productivity, devops, tutorial, opensource, saas, nextjs, automation.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.7,
        )
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, dict):
            raise GeminiGeneratorError("Gemini returned non-object JSON for Dev.to post.")
        return parsed

    def generate_x_post(
        self,
        blueprint: Dict[str, Any],
        buy_url: str,
    ) -> str:
        """Generate a high-converting <= 270 char X (Twitter) post with hashtags and buy link."""
        system_instruction = (
            "You are a top indie-hacker growth copywriter on X (Twitter). "
            "Write punchy, high-signal posts that hook developers/founders with a concrete problem or takeaway, "
            "include the buy/download link, and end with 2-3 relevant hashtags. "
            "STRICT LIMIT: Total post MUST be 270 characters or fewer (including the URL and hashtags)."
        )
        price_cents = int(blueprint.get("price_cents", 0) or 0)
        price_label = "Free ($0+)" if price_cents == 0 else f"${price_cents / 100:.0f}"

        prompt = f"""Write a single X (Twitter) post (MAX 270 characters total) for this digital product:

Product: {blueprint.get('name', '')}
Summary: {blueprint.get('custom_summary', '')}
Price: {price_label}
Link: {buy_url}
Suggested Hashtags: {json.dumps(blueprint.get('hashtags', [])[:5])}

Requirements:
- Hook with a specific pain point or concrete benefit in 1 short line.
- Include the exact link: {buy_url}
- Include 2-3 high-reach hashtags (e.g. #AI #TypeScript #IndieHackers).
- MUST be <= 270 characters total. Return ONLY the raw tweet text, no quotes or markdown fences.
"""
        raw = self._call_gemini(
            prompt=prompt,
            system_instruction=system_instruction,
            response_mime_type="text/plain",
            temperature=0.7,
        )
        tweet = raw.strip().strip('"').strip("'")
        if buy_url not in tweet:
            tweet = f"{tweet[:210].rstrip()} {buy_url}"
        if len(tweet) > 280:
            # Preserve buy_url at the end if slightly over 280
            without_url = tweet.replace(buy_url, "").strip()
            max_prefix = 280 - len(buy_url) - 1
            tweet = f"{without_url[:max_prefix].rstrip()} {buy_url}"
        return tweet



