"""Raw scraper output -> canonical Record objects.

Each source has its own messy shape; everything downstream only ever sees `Record`.
"""
import logging
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.models.records import Record
from app.scrapers.base import html_to_text

logger = logging.getLogger("ingestion.normalize")

# ---------------------------------------------------------------- Wasalt

# Listing attributes that are administrative noise for a property question.
_WASALT_SKIP_ATTRS = {
    "adSource", "planNumber", "landNumber", "zipCode", "regaAdvLicDate", "additionalNumber",
    "buildingNumber", "obligations", "regaGuaranteeDuration", "propertyMainType",
}


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def normalize_wasalt(row: dict[str, Any]) -> Record | None:
    data = row["data"]
    info = data.get("propertyInfo") or {}
    listing_id = data.get("id")
    if not listing_id or not info.get("title"):
        return None

    quick = {a.get("key"): a for a in data.get("attributes") or [] if a.get("value") not in (None, "")}
    attributes: dict[str, str] = {}
    for attr in quick.values():
        if attr["key"] in ("noOfBedrooms", "noOfBathrooms", "builtUpArea"):
            continue
        unit = f" {attr['unit']}" if attr.get("unit") else ""
        attributes[attr.get("name") or attr["key"]] = f"{attr['value']}{unit}"
    for attr in data.get("additionalAttributes") or []:
        key, value = attr.get("key", ""), attr.get("value")
        if value in (None, "", "-") or key in _WASALT_SKIP_ATTRS or key.startswith(("border", "length")):
            continue
        unit = f" {attr['unit']}" if attr.get("unit") else ""
        attributes[attr.get("label") or key] = f"{value}{unit}"

    purpose = info.get("propertyFor") if info.get("propertyFor") in ("sale", "rent") else None
    price = _to_float(info.get("salePrice")) if purpose == "sale" else _to_float(info.get("expectedRent"))
    area = _to_float((quick.get("builtUpArea") or {}).get("value")) or _to_float(data.get("floorSize"))
    amenities = [
        str(item.get("name") or item.get("label") or item) if isinstance(item, dict) else str(item)
        for item in (data.get("amenities") or []) + (data.get("fittings") or []) + (data.get("featureAmenities") or [])
    ]

    rent_freq_raw = info.get("rentFreq")
    if isinstance(rent_freq_raw, dict):
        rent_frequency = next(iter(rent_freq_raw.keys()), None)
    elif rent_freq_raw:
        rent_frequency = str(rent_freq_raw)
    else:
        rent_frequency = None

    record = Record(
        id=f"wasalt:{listing_id}",
        source="wasalt",
        doc_type="listing",
        url=row["url"],
        title=str(info["title"]).strip(),
        text=html_to_text(info.get("description") or ""),
        country=info.get("country"),
        city=info.get("city"),
        district=info.get("district") or info.get("zone"),
        property_type=info.get("propertySubType"),
        purpose=purpose,
        price=price,
        currency=info.get("currencyType") or "SAR",
        rent_frequency=rent_frequency if purpose == "rent" else None,
        bedrooms=_to_int((quick.get("noOfBedrooms") or {}).get("value")),
        bathrooms=_to_int((quick.get("noOfBathrooms") or {}).get("value")),
        area_sqm=area,
        amenities=sorted(set(a for a in amenities if a)),
        attributes={"Area": info["territory"], **attributes} if info.get("territory") else attributes,
        published_at=data.get("publishedAt"),
        updated_at=data.get("updatedAt"),
        scraped_at=row["scraped_at"],
    )
    record.content_hash = record.compute_hash()
    return record


# ---------------------------------------------------------------- DarGlobal

_COUNTRY_HINTS: list[tuple[str, str]] = [
    (r"\b(uae|united arab emirates|dubai|rak|ras al khaimah)\b", "United Arab Emirates"),
    (r"\b(ksa|saudi|riyadh|jeddah)\b", "Saudi Arabia"),
    (r"\boman|muscat\b", "Oman"),
    (r"\bqatar|doha\b", "Qatar"),
    (r"\bspain\b", "Spain"),
    (r"\b(uk|united kingdom|england|london)\b", "United Kingdom"),
    (r"\bmaldives\b", "Maldives"),
]
_CITY_HINTS: list[tuple[str, str]] = [
    (r"\bdubai\b", "Dubai"),
    (r"\b(rak|ras al khaimah|al marjan)\b", "Ras Al Khaimah"),
    (r"\b(muscat|aida)\b", "Muscat"),
    (r"\bsimaisma\b", "Simaisma"),
    (r"\bdoha\b", "Doha"),
    (r"\blondon\b", "London"),
    (r"\bjeddah\b", "Jeddah"),
    (r"\b(riyadh|wadi safar)\b", "Riyadh"),
    (r"\bbenahav[ií]s\b", "Benahavís"),
    (r"\bcortesin\b", "Casares"),
]
# "Label" on one line, its value on the next: rendered spec tables on project pages.
_SPEC_LABELS = {
    "Property Type", "Status", "Unit type", "Unit Type", "Area (SQFT)", "Area (SQM)", "Starting Price",
    "Starting price", "Completion", "Handover", "Number of Units", "Units", "Plot Size", "Bedrooms",
}


def _first_match(hints: list[tuple[str, str]], text: str) -> str | None:
    lowered = text.lower()
    for pattern, value in hints:
        if re.search(pattern, lowered):
            return value
    return None


def _fold_spec_lines(text: str) -> tuple[str, dict[str, str]]:
    """Turn 'Status\\nUnder Development' into 'Status: Under Development' and collect the pairs."""
    lines = text.splitlines()
    out: list[str] = []
    specs: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line in _SPEC_LABELS and index + 1 < len(lines) and lines[index + 1] not in _SPEC_LABELS:
            specs[line] = lines[index + 1]
            out.append(f"{line}: {lines[index + 1]}")
            index += 2
            continue
        out.append(line)
        index += 1
    return "\n".join(out), specs


def _readable_date(value: str) -> str:
    """ISO date to "16 November 2026", so a question that says "November 2026" matches."""
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


_COUNTRY_SLUGS = {
    "United Arab Emirates": "uae", "Saudi Arabia": "saudi-arabia", "Oman": "oman",
    "Qatar": "qatar", "Spain": "spain", "United Kingdom": "uk",
}


def darglobal_portfolio_records(projects: list[Record]) -> list[Record]:
    """One overview document per country, listing every project scraped from the /projects page.

    "Which projects does DarGlobal have in Oman?" is an aggregation question: the answer is
    spread over a dozen project pages and top-k retrieval can only return a few of them.
    This restructures facts already present on the public /projects listing (name + location)
    into one retrievable passage per country. Nothing is added that the site does not state.
    """
    by_country: dict[str, list[Record]] = {}
    for project in projects:
        if project.doc_type == "project" and project.country:
            by_country.setdefault(project.country, []).append(project)
    overviews: list[Record] = []
    for country, items in sorted(by_country.items()):
        lines = [f"DarGlobal lists {len(items)} projects in {country} on its projects page:"]
        lines += [f"- {item.title} ({item.attributes.get('Location', country)})" for item in items]
        slug = _COUNTRY_SLUGS.get(country)
        base = "https://www.darglobal.co.uk/projects"
        record = Record(
            id=f"darglobal:portfolio-{(slug or country).lower()}",
            source="darglobal",
            doc_type="page",
            url=f"{base}/properties-in-{slug}" if slug else base,
            title=f"DarGlobal projects in {country}",
            text="\n".join(lines),
            country=country,
            scraped_at=max(item.scraped_at for item in items),
        )
        record.content_hash = record.compute_hash()
        overviews.append(record)
    return overviews


def normalize_darglobal(row: dict[str, Any]) -> Record | None:
    kind = row.get("kind")
    path = urlsplit(row["url"]).path.strip("/") or "home"
    text, specs = _fold_spec_lines(row.get("text") or "")
    if len(text) < 80:
        return None

    title = (row.get("name") or row.get("page_title") or path).strip()
    location = (row.get("location") or "").strip()
    doc_type = {"project": "project", "press": "article"}.get(kind, "page")
    attributes = dict(specs)
    if location:
        attributes["Location"] = location
    if row.get("date"):
        attributes["Published"] = _readable_date(row["date"])

    # Geography is only inferred for projects, from the location printed on the project card.
    geo_text = location if doc_type == "project" else ""
    record = Record(
        id=f"darglobal:{path.lower()}",
        source="darglobal",
        doc_type=doc_type,
        url=row["url"],
        title=title,
        text=text,
        country=_first_match(_COUNTRY_HINTS, geo_text) if geo_text else None,
        city=_first_match(_CITY_HINTS, geo_text) if geo_text else None,
        property_type=specs.get("Property Type"),
        attributes=attributes,
        published_at=row.get("date"),
        scraped_at=row["scraped_at"],
    )
    record.content_hash = record.compute_hash()
    return record


# ---------------------------------------------------------------- shared

def deduplicate(records: list[Record]) -> list[Record]:
    """Drop repeated ids (same page reached twice) and exact content duplicates
    (same body published under two URLs). The first occurrence wins."""
    seen_ids: set[str] = set()
    seen_bodies: set[tuple[str, str]] = set()
    unique: list[Record] = []
    for record in records:
        body_key = (record.source, re.sub(r"\s+", " ", f"{record.title}|{record.text}").lower())
        if record.id in seen_ids or (record.doc_type != "listing" and body_key in seen_bodies):
            continue
        seen_ids.add(record.id)
        seen_bodies.add(body_key)
        unique.append(record)
    dropped = len(records) - len(unique)
    if dropped:
        logger.info("duplicates removed", extra={"dropped": dropped})
    return unique
