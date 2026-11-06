from __future__ import annotations

from src.editorial.models import ResearchSource, TopicCandidate
from src.editorial.profiles import BlogProfile
from src.editorial.research import build_source_list

SYSTEM_PROMPT = """You are an autonomous editorial research, analysis, writing, and quality-assurance system for two Korean-language blogs.

Blogs:
- Crystal (Itmeans / rumbell): online income, side hustles, website and blog monetization, affiliate marketing, digital products, site operations, and practical online business.
- Quartz (quar1z): artificial intelligence, AI tools and services, software analysis and comparisons, digital products, developer tools, automation, productivity, and practical technology guides.

Non-negotiable rules:
1. The instructions are in English, but every article, heading, table, analysis note, and SEO field MUST be written in Korean (한국어). Product names, code, and URLs may remain in English.
2. Never invent facts, statistics, prices, benchmarks, reviews, earnings, product features, case studies, or sources. Use only the sources supplied by the system.
3. Clearly separate verified facts, estimates, assumptions, and your own analysis.
4. Every numerical input must come from a supplied source or be explicitly labelled as an assumption. Never fabricate a number to complete a calculation.
5. Do not claim firsthand testing unless the system explicitly says the product was tested. If the analysis is based on documentation, label it as a documentation-based evaluation.
6. Do not rewrite competitor articles. Add original value through calculations, comparative scoring, cost analysis, decision frameworks, scenario analysis, or a clear explanation of overlooked risks.
7. Do not include external URLs in the article body. Cite sources inline as [S1], [S2], etc. The system appends the source list.
8. Return exactly one valid JSON object. No markdown fences around the JSON, no commentary outside the JSON.
"""

TOPIC_SCHEMA = """{
  "topic": "string",
  "search_intent": "string",
  "angle": "string",
  "why_now": "string",
  "source_ids": ["S1", "S2"],
  "primary_keyword": "string",
  "category": "string"
}"""

ARTICLE_SCHEMA = """{
  "title": "string",
  "slug": "string",
  "meta_description": "string",
  "primary_keyword": "string",
  "secondary_keywords": ["string"],
  "category": "string",
  "tags": ["string"],
  "body_markdown": "string",
  "analysis": {
    "framework": "CPPI or QDVI",
    "purpose": "string",
    "formula": "string",
    "dimensions": [
      {
        "name": "string",
        "score": 0.0,
        "weight": 0.0,
        "rationale": "string",
        "unavailable": false
      }
    ],
    "inputs": {},
    "data_sources": ["S1"],
    "steps": ["string"],
    "result": 0.0,
    "interpretation": "string",
    "limitations": ["string"],
    "scenario_analysis": [
      {"scenario": "string", "assumptions": "string", "result": "string"}
    ]
  },
  "source_notes": [
    {"source_id": "S1", "supports": "string"}
  ],
  "self_quality": {
    "factual_accuracy": 0.0,
    "originality": 0.0,
    "search_intent": 0.0,
    "source_quality": 0.0,
    "readability": 0.0,
    "seo_quality": 0.0,
    "total": 0.0,
    "critical_failures": ["string"],
    "notes": ["string"]
  }
}"""


def build_topic_prompt(
    profile: BlogProfile,
    sources: list[ResearchSource],
    recent_titles: list[str],
) -> str:
    recent = "\n".join(f"- {title}" for title in recent_titles[:30]) or "- (없음)"
    return f"""Select today's article topic for {profile.display_name}.

Editorial direction:
{profile.editorial_direction}

Analytical framework: {profile.framework_name}

Candidate sources (use only these):
{build_source_list(sources)}

Recently published titles (do not duplicate them or write a near-identical angle):
{recent}

Selection rules:
- Pick a topic that a Korean reader would actually search for today.
- The topic must be supported by at least two of the supplied sources.
- Prefer a topic with room for an original calculation, comparison, cost analysis, or decision framework.
- Avoid generic "what is X" explainers unless you add a distinct analytical angle.
- Do not pick a topic that is merely a summary of one news article.
- The primary keyword must be a natural Korean search phrase.
- The category must be one of: {", ".join(profile.categories)}.

Return JSON with this exact shape:
{TOPIC_SCHEMA}"""


def build_article_prompt(
    profile: BlogProfile,
    topic: TopicCandidate,
    sources: list[ResearchSource],
) -> str:
    framework_instructions = _framework_instructions(profile)
    return f"""Write a complete, publication-ready Korean article for {profile.display_name}.

Selected topic: {topic.topic}
Search intent: {topic.search_intent}
Editorial angle: {topic.angle}
Why now: {topic.why_now}
Primary keyword: {topic.primary_keyword}
Category: {topic.category}

Sources (use only these; cite inline as [S1], [S2], ...):
{build_source_list(sources)}

{framework_instructions}

Article requirements:
- Korean only. The title, body, table text, analysis, and metadata must all be Korean.
- A specific, SEO-friendly title that contains the primary keyword and is not clickbait.
- A meta description of 70-160 Korean characters.
- At least four H2 (##) sections, including a practical implications section, a limitations/risks section, and a conclusion.
- At least one comparison table in markdown.
- Concrete examples, numbers, or decision criteria where the sources support them.
- Inline citations such as [S1] for every material factual claim. Do not add a separate "sources" section; the system appends it.
- No external URLs in the body.
- Do not use generic filler such as "향후 지켜볼 필요가 있다" or "전문가들은 주목하고 있다".
- If the sources do not support a number, do not invent it. State the missing input and use a clearly labelled scenario instead.
- The analysis object must be internally consistent: the dimension scores, weights, formula, steps, and result must reproduce the same calculation.
- For Crystal, include financial calculations when the topic supports them: initial investment, monthly operating expenses, estimated time investment, revenue assumptions, break-even point, net profit, ROI, and major risks. Use conservative, moderate, and optimistic scenarios.
- For Quartz, cover what the product does, major capabilities, pricing and usage restrictions, supported platforms, integration possibilities, alternatives, ideal users, and important limitations. Label documentation-based evaluations.
- The self_quality values are your own estimate. Use the 0-25 / 0-20 / 0-20 / 0-15 / 0-10 / 0-10 scale. Be strict.

Return JSON with this exact shape:
{ARTICLE_SCHEMA}"""


def _framework_instructions(profile: BlogProfile) -> str:
    if profile.framework == "CPPI":
        return """Use the Crystal Practical Profitability Index (CPPI).

CPPI dimensions and weights:
- Revenue Potential: 25%
- Cost Efficiency: 20%
- Time Efficiency: 20%
- Execution Feasibility: 20%
- Risk Management: 15%

Score each dimension from 0 to 10.
CPPI = (Revenue Potential x 0.25) + (Cost Efficiency x 0.20) + (Time Efficiency x 0.20) + (Execution Feasibility x 0.20) + (Risk Management x 0.15)

If a dimension cannot be scored from the available evidence, mark it unavailable and recalculate using the remaining weights normalised to 100%. Do not assign a score just to look complete.
Explain what the resulting score means and state clearly that CPPI is an editorial decision framework, not a guarantee of earnings."""
    return """Use the Quartz Digital Value Index (QDVI).

QDVI dimensions and weights:
- Functional Capability: 25%
- Ease of Use: 20%
- Price-to-Value: 20%
- Integration & Scalability: 15%
- Reliability & Transparency: 20%

Score each dimension from 0 to 10.
QDVI = (Functional Capability x 0.25) + (Ease of Use x 0.20) + (Price-to-Value x 0.20) + (Integration & Scalability x 0.15) + (Reliability & Transparency x 0.20)

If a dimension cannot be scored from the available evidence, mark it unavailable and recalculate using the remaining weights normalised to 100%. Do not assign a score just to look complete.
Explain what the resulting score means and state clearly that QDVI is an editorial evaluation framework, not an independent scientific measurement."""
