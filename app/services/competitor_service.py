from app.schemas import Competitor


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
