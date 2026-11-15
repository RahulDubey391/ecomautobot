import re
from typing import Dict, List, Tuple

NICHE_TAG_CLUSTERS: Dict[str, Dict[str, List[str]]] = {
    "ai_coding": {
        "keywords": ["cursor", "claude", "windsurf", "copilot", "coding", "developer", "typescript", "python", "fastapi", "nextjs"],
        "gumroad_tags": [
            "ai coding",
            "cursor rules",
            "claude code",
            "prompt engineering",
            "developer tools",
            "software engineering",
            "programming",
        ],
        "hashtags": [
            "#AICoding",
            "#CursorAI",
            "#CursorRules",
            "#ClaudeCode",
            "#PromptEngineering",
            "#SoftwareEngineering",
            "#WebDev",
            "#IndieHacker",
            "#TypeScript",
            "#NextJS",
            "#Python",
            "#DevTools",
        ],
    },
    "solopreneur_automation": {
        "keywords": ["solopreneur", "workflow", "sop", "automation", "agency", "freelance", "make", "n8n", "zapier", "productivity"],
        "gumroad_tags": [
            "ai prompts",
            "solopreneur",
            "automation",
            "productivity",
            "workflows",
            "business templates",
            "chatgpt prompts",
        ],
        "hashtags": [
            "#Solopreneur",
            "#AIAutomation",
            "#AIWorkflows",
            "#PromptEngineering",
            "#ChatGPTPrompts",
            "#ProductivityHacks",
            "#NoCode",
            "#IndieMaker",
            "#DigitalProducts",
            "#BusinessAutomation",
            "#CreatorEconomy",
            "#SOPs",
        ],
    },
    "design_ui": {
        "keywords": ["design", "figma", "ui", "ux", "landing page", "wireframe", "tailwind", "mockup"],
        "gumroad_tags": [
            "ui kit",
            "web design",
            "landing page",
            "figma template",
            "saas design",
            "copywriting",
        ],
        "hashtags": [
            "#UIDesign",
            "#UXDesign",
            "#LandingPage",
            "#SaaS",
            "#Figma",
            "#WebDesign",
            "#IndieHacker",
            "#ConversionRate",
        ],
    },
}


def generate_tags_and_hashtags(
    name: str,
    slug: str,
    summary: str = "",
    existing_tags: List[str] | None = None,
) -> Tuple[List[str], List[str]]:
    """Return (gumroad_discover_tags, reach_hashtags) tailored to the product."""
    corpus = f"{name} {slug} {summary}".lower()

    discover_tags: List[str] = list(existing_tags or [])
    hashtags: List[str] = []

    for cluster in NICHE_TAG_CLUSTERS.values():
        if any(kw in corpus for kw in cluster["keywords"]):
            for t in cluster["gumroad_tags"]:
                if t.lower() not in [x.lower() for x in discover_tags]:
                    discover_tags.append(t)
            for h in cluster["hashtags"]:
                if h.lower() not in [x.lower() for x in hashtags]:
                    hashtags.append(h)

    # Convert any custom discover_tags into CamelCase / clean hashtags as well
    for tag in discover_tags:
        words = re.findall(r"[a-zA-Z0-9]+", tag)
        if words:
            candidate = "#" + "".join(w.capitalize() for w in words)
            if candidate.lower() not in [x.lower() for x in hashtags]:
                hashtags.append(candidate)

    if not hashtags:
        hashtags = ["#DigitalProducts", "#Gumroad", "#Productivity", "#Templates", "#AIWorkflows", "#CreatorTools"]

    return discover_tags[:10], hashtags[:15]

