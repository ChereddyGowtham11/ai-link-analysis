import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.metrics import measure
from app.schemas import Competitor
from app.services.website_extractor import WebsiteExtractor, clean, origin
from app.utils.validators import AnalysisError, validate_url

logger = logging.getLogger(__name__)
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def unverified_suggestions(
    candidates: list[Competitor], brand_name: str
) -> list[Competitor]:
    """Keep candidate names when independent competitor evidence is unavailable."""
    seen = {" ".join(brand_name.casefold().split())}
    suggestions = []
    for candidate in candidates:
        name = candidate.name
        key = " ".join(name.casefold().split())
        if not key or key in seen or len(name) > 100 or "://" in name:
            continue
        seen.add(key)
        suggestions.append(
            Competitor(
                name=name,
                website=None,
                main_services=[],
                target_market="",
                strengths=[],
                weaknesses=[],
                competitive_gap="",
                evidence_status="unverified",
                sources=[],
            )
        )
    return suggestions


def mentions(text: str, phrase: str) -> bool:
    return bool(
        re.search(rf"(?<!\w){re.escape(phrase.casefold())}(?!\w)", text.casefold())
    )


def domain(url: httpx.URL) -> str:
    return url.host.removeprefix("www.")


async def research_competitors(
    candidates: list[Competitor],
    brand_name: str,
    subject_url: str,
    offerings: list[str],
    extractor: WebsiteExtractor,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[Competitor], str]:
    competitors = unverified_suggestions(candidates, brand_name)
    secret = extractor.settings.brave_search_api_key
    key = secret.get_secret_value().strip() if secret else ""
    if not key or key == "your_api_key_here":
        return competitors, "Competitor suggestions are unverified. Search is disabled."
    terms = list(
        dict.fromkeys(clean(term) for term in offerings if 4 <= len(clean(term)) <= 80)
    )[:5]
    if not terms or not competitors:
        return (
            competitors,
            "The analysis found too little evidence to research competitors.",
        )
    source_domain = domain(httpx.URL(subject_url))
    seen = {source_domain}
    try:
        with measure("competitors"):
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    timeout=4,
                    trust_env=False,
                    follow_redirects=False,
                    transport=transport,
                    headers={"X-Subscription-Token": key, "Accept": "application/json"},
                ) as client,
            ):
                for index, competitor in enumerate(competitors):
                    researched = await find_competitor(
                        client, competitor, terms, seen, extractor
                    )
                    if researched:
                        competitors[index] = researched
    except (TimeoutError, httpx.HTTPError, ValueError):
        logger.warning("competitor_research incomplete")
        return (
            competitors,
            "Competitor research was incomplete. Check each evidence label.",
        )
    verified = sum(row.evidence_status == "verified" for row in competitors)
    return competitors, (
        f"Competitors with matching first-party evidence: {verified}. "
        "Inferred entries cite search excerpts. Search coverage may be incomplete."
    )


async def find_competitor(
    client: httpx.AsyncClient,
    candidate: Competitor,
    terms: list[str],
    seen: set[str],
    extractor: WebsiteExtractor,
) -> Competitor | None:
    query = clean(f"{candidate.name} {terms[0]}")[:190]
    response = await client.get(
        BRAVE_URL, params={"q": query, "count": 4, "safesearch": "strict"}
    )
    response.raise_for_status()
    payload = response.json()
    web = payload.get("web") if isinstance(payload, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return None
    for item in results[:4]:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        try:
            source = validate_url(item["url"]).copy_with(query=None)
        except AnalysisError:
            continue
        title = clean(
            BeautifulSoup(str(item.get("title", ""))[:500], "html.parser").get_text()
        )
        if (
            source.scheme != "https"
            or domain(source) in seen
            or not mentions(title, candidate.name)
        ):
            continue
        excerpt = clean(
            BeautifulSoup(
                str(item.get("description") or "")[:900], "html.parser"
            ).get_text()
        )
        excerpt_terms = [term for term in terms if mentions(excerpt, term)]
        try:
            page = await extractor.fetch_page(source, same_origin=origin(source))
        except AnalysisError:
            continue
        site_name = clean(page.data.get("brand_name"))
        site_title = clean(page.data.get("title"))
        domain_label = domain(source).split(".", 1)[0]
        brand_label = "".join(re.findall(r"[a-z0-9]", candidate.name.casefold()))
        if not mentions(site_name, candidate.name) and not (
            brand_label
            and domain_label.replace("-", "") == brand_label
            and mentions(site_title, candidate.name)
        ):
            continue
        sections = page.data.get("sections", {})
        offerings_text = " ".join(
            [
                page.data.get("meta_description") or "",
                sections.get("services", ""),
                sections.get("products", ""),
            ]
        )
        supported = [term for term in terms if mentions(offerings_text, term)]
        if not supported and not excerpt_terms:
            continue
        offerings = supported or excerpt_terms
        seen.add(domain(source))
        return candidate.model_copy(
            update={
                "website": page.url,
                "main_services": offerings,
                "strengths": [
                    f"Highlights {term} in its public material." for term in offerings
                ],
                "competitive_gap": (
                    "Potential positioning opportunity: explain how the brand delivers "
                    f"{offerings[0]} and substantiate any difference with examples."
                ),
                "evidence_status": "verified" if supported else "inferred",
                "sources": list(dict.fromkeys([page.url, str(source)])),
            }
        )
    return None
