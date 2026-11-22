import json
import logging
from time import perf_counter

from app.schemas import LinkAnalysisResponse, Service
from app.services.competitor_service import unverified_suggestions
from app.services.llm_service import ModelProvider
from app.services.website_extractor import Website, WebsiteExtractor, clean
from app.utils.validators import validate_url

logger = logging.getLogger(__name__)
EVIDENCE_FIELDS = (
    "title",
    "meta_description",
    "brand_name",
    "business_category",
    "text",
    "headings",
    "sections",
    "canonical_url",
    "open_graph",
    "json_ld",
    "contact",
)


def evidence_payload(website: Website, budget: int) -> tuple[str, list[dict]]:
    def serialize() -> str:
        return json.dumps(
            {"pages": pages, "limitations": website.limitations},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def fit_text(page: dict, prefix: str, limit: int) -> None:
        low, high = 0, len(prefix)
        while low < high:
            mid = (low + high + 1) // 2
            page["text"] = prefix[:mid]
            if len(serialize()) <= limit:
                low = mid
            else:
                high = mid - 1
        page["text"] = prefix[:low]

    pages = []
    used_text = set()
    for index, page in enumerate(website.pages):
        count = len(website.pages)
        limit = (
            budget * (count + index + 1) // (2 * count) if index + 1 < count else budget
        )
        entry = {"url": page.url}
        pages.append(entry)
        if len(serialize()) > limit - 100 and index:
            pages.pop()
            continue
        for key in EVIDENCE_FIELDS:
            value = page.data.get(key)
            if not value:
                continue
            if key == "text":
                if value.casefold() in used_text:
                    continue
                used_text.add(value.casefold())
                entry[key] = ""
                fit_text(entry, value, limit - min(1200, budget // 5))
                if not entry[key]:
                    entry.pop(key)
                continue
            entry[key] = value
            if len(serialize()) > limit:
                entry.pop(key)
    return serialize(), pages


def ground_services(services: list[Service], pages: list[dict]) -> list[Service]:
    evidence = {}
    for page in pages:
        headings = [item["text"] for item in page.get("headings", [])]
        evidence[page["url"]] = [
            clean(item).casefold()
            for item in [
                page.get("text", ""),
                *headings,
                *page.get("sections", {}).values(),
            ]
        ]
    for item in services:
        quote = clean(item.evidence_quote).casefold()
        name = clean(item.service_name).casefold()
        if (
            item.evidence_status == "verified"
            and name
            and name in quote
            and any(quote in text for text in evidence.get(item.source_url, []))
        ):
            continue
        item.evidence_status = "inferred"
        item.source_url = None
        item.evidence_quote = None
    return sorted(services, key=lambda item: item.evidence_status != "verified")


class AnalysisService:
    def __init__(self, extractor: WebsiteExtractor, llm: ModelProvider) -> None:
        self.extractor = extractor
        self.llm = llm

    async def analyze(self, raw_url: str) -> LinkAnalysisResponse:
        started = perf_counter()
        website = await self.extractor.extract(validate_url(raw_url))
        payload, pages = evidence_payload(
            website, self.extractor.settings.max_website_chars
        )
        result = await self.llm.analyze(payload)
        analysis = result.analysis
        competitors = analysis.competitor_analysis
        competitors.competitors = unverified_suggestions(
            competitors.competitors, result.brand.name
        )
        analysis.top_services = ground_services(analysis.top_services, pages)
        verified_count = sum(
            item.evidence_status == "verified" for item in analysis.top_services
        )
        analysis.top_services_note = (
            f"Services with supporting website excerpts: {verified_count}. "
            "Inferred entries are suggestions. Fewer than five may be available."
        )
        landing = website.pages[0]
        analysis.seo_improvements.current_title = landing.data["title"]
        analysis.seo_improvements.current_meta_description = landing.data[
            "meta_description"
        ]
        limitations = [
            *website.limitations,
            "Analysis uses static website content. "
            "Competitor suggestions are unverified.",
        ]
        if len(pages) < len(website.pages):
            limitations.append("The evidence limit excluded some fetched pages.")
        logger.info(
            "analysis_completed pages=%d duration_ms=%d",
            len(pages),
            round((perf_counter() - started) * 1000),
        )
        return LinkAnalysisResponse(
            brand=result.brand,
            analysis=analysis,
            website=landing.url,
            pages_analyzed=[page["url"] for page in pages],
            limitations=limitations,
        )
