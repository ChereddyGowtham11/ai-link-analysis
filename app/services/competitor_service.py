import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app.metrics import measure
from app.schemas import Competitor
from app.services.evidence import (
    citation_url,
    mentions,
    positive_mention,
    sanitize_evidence,
)
from app.services.website_extractor import WebsiteExtractor, clean
from app.utils.validators import AnalysisError, validate_url

logger = logging.getLogger(__name__)
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = (
    "DxoraLinkAnalysis/1.0 (https://github.com/ChereddyGowtham11/ai-link-analysis)"
)


@dataclass(frozen=True)
class CandidateSource:
    url: str
    title: str
    excerpt: str = ""
    reference: str | None = None


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
    key = "" if key == "your_api_key_here" else key
    if not key and extractor.settings.competitor_research != "wikidata":
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
    incomplete = False
    try:
        with measure("competitors"):
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    timeout=4,
                    trust_env=False,
                    follow_redirects=False,
                    transport=transport,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                ) as client,
            ):
                for index, competitor in enumerate(competitors):
                    try:
                        sources = (
                            await brave_sources(client, competitor.name, terms[0], key)
                            if key
                            else await wikidata_sources(client, competitor.name)
                        )
                    except (
                        httpx.HTTPError,
                        AttributeError,
                        TypeError,
                        ValueError,
                    ) as error:
                        incomplete = True
                        if isinstance(error, httpx.HTTPStatusError) and (
                            error.response.status_code in (401, 403, 429)
                        ):
                            break
                        continue
                    researched = await find_competitor(
                        competitor, terms, seen, extractor, sources
                    )
                    if researched:
                        competitors[index] = researched
    except (TimeoutError, httpx.HTTPError, ValueError):
        incomplete = True
    if incomplete:
        logger.warning("competitor_research incomplete")
        return (
            competitors,
            "Competitor research was incomplete. Check each evidence label.",
        )
    verified = sum(row.evidence_status == "verified" for row in competitors)
    return competitors, (
        f"Competitors with matching first-party evidence: {verified}. "
        "Inferred entries cite discovery sources. Coverage may be incomplete."
    )


async def brave_sources(
    client: httpx.AsyncClient,
    name: str,
    term: str,
    key: str,
) -> list[CandidateSource]:
    query = clean(f"{name} {term}")[:190]
    response = await client.get(
        BRAVE_URL,
        params={"q": query, "count": 4, "safesearch": "strict"},
        headers={"X-Subscription-Token": key},
    )
    response.raise_for_status()
    payload = response.json()
    web = payload.get("web") if isinstance(payload, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return []
    sources = []
    for item in results[:4]:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        title = BeautifulSoup(str(item.get("title") or "")[:500], "html.parser")
        excerpt = BeautifulSoup(str(item.get("description") or "")[:900], "html.parser")
        sources.append(
            CandidateSource(
                item["url"], clean(title.get_text()), clean(excerpt.get_text())
            )
        )
    return sources


async def wikidata_sources(
    client: httpx.AsyncClient, name: str
) -> list[CandidateSource]:
    response = await client.get(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 4,
            "format": "json",
        },
    )
    response.raise_for_status()
    hits = {
        item["id"]: item
        for item in response.json().get("search", [])[:4]
        if re.fullmatch(r"Q[1-9]\d*", item.get("id", ""))
        and mentions(item.get("label") or "", name)
    }
    if not hits:
        return []
    response = await client.get(
        WIKIDATA_API,
        params={
            "action": "wbgetentities",
            "ids": "|".join(hits),
            "props": "claims",
            "format": "json",
        },
    )
    response.raise_for_status()
    sources = []
    for item_id, entity in response.json().get("entities", {}).items():
        if item_id not in hits:
            continue
        for claim in entity.get("claims", {}).get("P856", [])[:2]:
            address = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(address, str) and claim.get("rank") != "deprecated":
                sources.append(
                    CandidateSource(
                        address,
                        hits[item_id]["label"],
                        excerpt=hits[item_id].get("description") or "",
                        reference=f"https://www.wikidata.org/wiki/{item_id}",
                    )
                )
    return sources[:4]


async def find_competitor(
    candidate: Competitor,
    terms: list[str],
    seen: set[str],
    extractor: WebsiteExtractor,
    sources: list[CandidateSource],
) -> Competitor | None:
    for item in sources:
        try:
            source = validate_url(item.url).copy_with(query=None)
        except AnalysisError:
            continue
        if (
            source.scheme != "https"
            or domain(source) in seen
            or not mentions(item.title, candidate.name)
        ):
            continue
        excerpt_terms = [term for term in terms if mentions(item.excerpt, term)]
        try:
            page = await extractor.fetch_page(source)
        except AnalysisError:
            continue
        final = httpx.URL(page.url)
        if final.scheme != "https" or domain(final) != domain(source):
            continue
        site_name = clean(page.data.get("brand_name"))
        site_title = clean(page.data.get("title"))
        domain_label = domain(final).split(".", 1)[0]
        brand_label = "".join(re.findall(r"[a-z0-9]", candidate.name.casefold()))
        if not mentions(site_name, candidate.name) and not (
            brand_label
            and domain_label.replace("-", "") == brand_label
            and (item.reference or mentions(site_title, candidate.name))
        ):
            continue
        sections = page.data.get("sections", {})
        offerings_text = sanitize_evidence(
            " ".join(
                [
                    site_title,
                    page.data.get("meta_description") or "",
                    sections.get("services", ""),
                    sections.get("products", ""),
                    *(heading["text"] for heading in page.data.get("headings", [])),
                ]
            )
        )
        body = sanitize_evidence(page.data.get("text") or "")
        supported = [
            term
            for term in terms
            if positive_mention(offerings_text, term) or positive_mention(body, term)
        ]
        excerpt_terms = [
            term
            for term in excerpt_terms
            if not mentions(f"{offerings_text} {body}", term) or term in supported
        ]
        if not supported and not excerpt_terms:
            continue
        offerings = supported or excerpt_terms
        subject_only = [
            term
            for term in terms
            if term not in offerings
            and not any(
                mentions(term, overlap) or mentions(overlap, term)
                for overlap in offerings
            )
        ]
        gap = ""
        if supported and subject_only:
            gap = (
                f"Both sites mention {supported[0]}. The subject site mentions "
                f"{subject_only[0]}, which was absent from the competitor's sampled "
                "offering text. Check other pages before drawing a conclusion."
            )
        url = citation_url(page.url)
        references = list(
            dict.fromkeys(
                [url, str(source)] + ([item.reference] if item.reference else [])
            )
        )
        seen.add(domain(final))
        return candidate.model_copy(
            update={
                "website": url,
                "main_services": offerings,
                "strengths": [
                    f"Highlights {term} in its public material." for term in offerings
                ],
                "competitive_gap": gap,
                "evidence_status": "verified" if supported else "inferred",
                "sources": references,
            }
        )
    return None
