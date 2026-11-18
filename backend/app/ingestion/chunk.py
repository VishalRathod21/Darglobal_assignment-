"""Record -> retrievable chunks.

Two strategies, because the two document shapes are different:
  * Listings are short and structured: one self-contained "card" per listing. Splitting
    a listing would separate the price from the bedrooms and hurt both retrieval and answers.
  * Projects / articles are long prose: split on line boundaries into ~900 character
    windows with a small overlap, and prefix every chunk with a header naming the document.
    Without that header a chunk like "Amenities: gym, pool" has no idea which project it is.
"""
from app.models.records import SOURCE_LABELS, Chunk, Record

MAX_CHARS = 1000
OVERLAP_LINES = 1


def _money(value: float, currency: str | None) -> str:
    return f"{currency or ''} {value:,.0f}".strip()


def _listing_card(record: Record) -> str:
    kind = " ".join(p for p in [record.property_type, f"for {record.purpose}" if record.purpose else None] if p)
    location = ", ".join(p for p in [record.district, record.attributes.get("Area"), record.city, record.country] if p)
    facts: list[str] = []
    if record.price is not None:
        suffix = f" ({record.rent_frequency})" if record.rent_frequency else ""
        facts.append(f"Price: {_money(record.price, record.currency)}{suffix}")
    if record.bedrooms is not None:
        facts.append(f"Bedrooms: {record.bedrooms}")
    if record.bathrooms is not None:
        facts.append(f"Bathrooms: {record.bathrooms}")
    if record.area_sqm is not None:
        facts.append(f"Built-up area: {record.area_sqm:,.0f} sqm")
    details = "; ".join(f"{k}: {v}" for k, v in record.attributes.items() if k != "Area")
    lines = [
        f"[{SOURCE_LABELS[record.source]} listing] {record.title}",
        f"Type: {kind}" if kind else "",
        f"Location: {location}" if location else "",
        " | ".join(facts),
        f"Details: {details}" if details else "",
        f"Amenities: {', '.join(record.amenities)}" if record.amenities else "",
        f"Description: {' '.join(record.text.split())}" if record.text else "",
    ]
    return "\n".join(line for line in lines if line)


def _header(record: Record) -> str:
    label = {"project": "project", "article": "press release", "page": "page"}[record.doc_type]
    extras = [record.attributes.get("Location"), record.attributes.get("Published")]
    suffix = " | ".join(e for e in extras if e)
    return f"[{SOURCE_LABELS[record.source]} {label}] {record.title}" + (f" | {suffix}" if suffix else "")


def _split_prose(text: str) -> list[str]:
    windows: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        # A single very long paragraph is cut at sentence-ish boundaries.
        pieces = [line[i:i + MAX_CHARS] for i in range(0, len(line), MAX_CHARS)] or [line]
        for piece in pieces:
            if current and size + len(piece) > MAX_CHARS:
                windows.append("\n".join(current))
                current = current[-OVERLAP_LINES:]
                size = sum(len(c) for c in current)
            current.append(piece)
            size += len(piece)
    if current:
        windows.append("\n".join(current))
    return windows


def chunk_record(record: Record) -> list[Chunk]:
    if record.doc_type == "listing":
        texts = [_listing_card(record)]
    else:
        header = _header(record)
        texts = [f"{header}\n{window}" for window in _split_prose(record.text)]
    return [
        Chunk(
            id=f"{record.id}#{index}",
            record_id=record.id,
            text=text,
            source=record.source,
            doc_type=record.doc_type,
            url=record.url,
            title=record.title,
            city=record.city,
            district=record.district,
            property_type=record.property_type,
            purpose=record.purpose,
            price=record.price,
            currency=record.currency,
            bedrooms=record.bedrooms,
            area_sqm=record.area_sqm,
            scraped_at=record.scraped_at,
            content_hash=record.content_hash,
        )
        for index, text in enumerate(texts)
    ]
