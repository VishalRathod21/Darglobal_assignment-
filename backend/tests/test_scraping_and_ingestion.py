from app.ingestion.chunk import MAX_CHARS, chunk_record
from app.ingestion.normalize import (
    darglobal_portfolio_records,
    deduplicate,
    normalize_darglobal,
    normalize_wasalt,
)
from app.scrapers.base import RobotsRules, extract_next_data, html_to_text
from app.scrapers.darglobal import DarGlobalScraper
from app.scrapers.wasalt import WasaltScraper

DARGLOBAL_ROBOTS = """
User-agent: *
Disallow: /sitemap_index.xml
Disallow: /*utm_source=
Disallow: /*?s=
Allow: /$
Allow: /projects/
"""
WASALT_ROBOTS = """
User-agent: anthropic-ai
Allow: /search

User-agent: *
Allow: /
Disallow: /search
Disallow: /cdn-cgi/rum
"""


def test_robots_wildcards_and_default_allow():
    rules = RobotsRules(DARGLOBAL_ROBOTS)
    assert rules.allowed("https://www.darglobal.co.uk/dg1")
    assert rules.allowed("https://www.darglobal.co.uk/projects/properties-in-oman")
    assert not rules.allowed("https://www.darglobal.co.uk/sitemap_index.xml")
    assert not rules.allowed("https://www.darglobal.co.uk/dg1?utm_source=newsletter")
    assert not rules.allowed("https://www.darglobal.co.uk/?s=villa")


def test_robots_longest_match_and_agent_groups():
    rules = RobotsRules(WASALT_ROBOTS)
    assert rules.allowed("https://wasalt.sa/en/property/sale/villa-1")
    assert not rules.allowed("https://wasalt.sa/search?q=riyadh")
    # A bot-specific group replaces the wildcard group for that bot only.
    assert RobotsRules(WASALT_ROBOTS, "anthropic-ai").allowed("https://wasalt.sa/search?q=riyadh")


def test_html_to_text_drops_chrome():
    html = "<body><header>Menu</header><p>Villa with pool</p><form>Name</form><script>x()</script><footer>©</footer></body>"
    assert html_to_text(html) == "Villa with pool"


def test_extract_next_data():
    html = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"a":1}}}</script>'
    assert extract_next_data(html) == {"props": {"pageProps": {"a": 1}}}
    assert extract_next_data("<html></html>") is None


def _wasalt_row(**info_overrides) -> dict:
    info = {
        "title": "Apartment with 3 Bedrooms", "description": "<p>Apartment for Sale</p><p>Price: 850000 SAR</p>",
        "country": "Saudi Arabia", "city": "Riyadh", "district": "Al-Mahdiyah", "territory": "West Riyadh",
        "propertySubType": "Apartment", "propertyFor": "sale", "salePrice": 850000, "currencyType": "SAR",
        "slug": "apartment-with-3-bedrooms-1", "expectedRent": "",
    }
    info.update(info_overrides)
    return {
        "url": "https://wasalt.sa/en/property/sale/apartment-with-3-bedrooms-1",
        "scraped_at": "2026-11-18T18:00:00+00:00",
        "data": {
            "id": 1,
            "propertyInfo": info,
            "attributes": [
                {"key": "noOfBedrooms", "name": "Bedrooms", "value": 3},
                {"key": "builtUpArea", "name": "Built-Up Area", "value": "133", "unit": "SQM"},
            ],
            "additionalAttributes": [
                {"key": "completionYear", "label": "Age", "value": "New"},
                {"key": "planNumber", "label": "Plan number", "value": "2566"},
                {"key": "borderEast", "label": "Border from East", "unit": "m"},
            ],
        },
    }


def test_normalize_wasalt_listing():
    record = normalize_wasalt(_wasalt_row())
    assert record is not None
    assert record.id == "wasalt:1" and record.source == "wasalt" and record.doc_type == "listing"
    assert (record.price, record.currency, record.bedrooms, record.area_sqm) == (850000.0, "SAR", 3, 133.0)
    assert record.attributes == {"Area": "West Riyadh", "Age": "New"}  # admin fields dropped
    assert "Price: 850000 SAR" in record.text and "<p>" not in record.text
    assert record.content_hash


def test_wasalt_parser_never_keeps_contact_details():
    page = {
        "props": {"pageProps": {"propertyDetailsV3": {
            "id": 7,
            "propertyInfo": {"title": "Villa", "slug": "villa-7", "propertyFor": "sale", "managedBy": "Some Agency"},
            "leadContactInfo": {"ownerName": "A Person"},
            "propertyOwner": {"resEmployee": "A Person", "falLicenseNumber": "123"},
            "regaVerifiedInfo": [{"fields": [{"key": "responsibleEmployeePhoneNumber"}]}],
        }}}
    }
    import json

    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(page)}</script>'
    listing = WasaltScraper.parse_listing(html)
    assert listing is not None
    serialised = json.dumps(listing)
    for forbidden in ("A Person", "Some Agency", "leadContactInfo", "propertyOwner", "regaVerifiedInfo"):
        assert forbidden not in serialised


def test_content_hash_ignores_scrape_time():
    first = normalize_wasalt(_wasalt_row())
    row = _wasalt_row()
    row["scraped_at"] = "2026-12-01T00:00:00+00:00"
    assert normalize_wasalt(row).content_hash == first.content_hash
    assert normalize_wasalt(_wasalt_row(salePrice=900000)).content_hash != first.content_hash


def _darglobal_row(**overrides) -> dict:
    row = {
        "kind": "project", "url": "https://www.darglobal.co.uk/dg1", "scraped_at": "2026-11-18T18:00:00+00:00",
        "name": "DG1", "location": "Dubai, United Arab Emirates", "page_title": "DG1",
        "text": "DG1\nAn exclusive capsule collection of luxury residences in Business Bay.\n"
                "Property Type\nResidential Tower\nStatus\nUnder Development\nAmenities\nInfinity Swimming Pool",
    }
    row.update(overrides)
    return row


def test_normalize_darglobal_project_folds_spec_table():
    record = normalize_darglobal(_darglobal_row())
    assert record is not None
    assert record.id == "darglobal:dg1" and record.doc_type == "project"
    assert (record.city, record.country) == ("Dubai", "United Arab Emirates")
    assert "Status: Under Development" in record.text
    assert record.attributes["Property Type"] == "Residential Tower"


def test_press_release_gets_readable_date_and_no_guessed_city():
    record = normalize_darglobal(
        _darglobal_row(kind="press", url="https://www.darglobal.co.uk/press/x", date="2026-11-16", location="")
    )
    assert record.doc_type == "article" and record.city is None
    assert record.attributes["Published"] == "16 November 2026"


def test_deduplicate_by_id_and_by_body():
    a = normalize_darglobal(_darglobal_row())
    same_id = normalize_darglobal(_darglobal_row())
    same_body = normalize_darglobal(_darglobal_row(url="https://www.darglobal.co.uk/dg1-copy"))
    other = normalize_darglobal(_darglobal_row(url="https://www.darglobal.co.uk/other", name="Other", text="x" * 200))
    assert [r.id for r in deduplicate([a, same_id, same_body, other])] == ["darglobal:dg1", "darglobal:other"]


def test_portfolio_overview_lists_only_scraped_projects():
    projects = [
        normalize_darglobal(_darglobal_row()),
        normalize_darglobal(_darglobal_row(url="https://www.darglobal.co.uk/aida", name="Aida", location="Muscat, Oman",
                                           text="Aida is a clifftop community in Muscat. " * 5)),
    ]
    overviews = {r.country: r for r in darglobal_portfolio_records(projects)}
    assert set(overviews) == {"United Arab Emirates", "Oman"}
    assert "- Aida (Muscat, Oman)" in overviews["Oman"].text and "DG1" not in overviews["Oman"].text
    assert overviews["Oman"].url.endswith("/projects/properties-in-oman")


def test_listing_is_one_self_contained_chunk():
    chunks = chunk_record(normalize_wasalt(_wasalt_row()))
    assert len(chunks) == 1
    text = chunks[0].text
    assert text.startswith("[Wasalt.sa listing] Apartment with 3 Bedrooms")
    assert "Price: SAR 850,000" in text and "Bedrooms: 3" in text and "Al-Mahdiyah" in text
    assert chunks[0].metadata()["price"] == 850000.0 and "district" in chunks[0].metadata()


def test_long_document_is_split_with_header_on_every_chunk():
    body = "\n".join(f"Paragraph {i}: " + "luxury living by the sea. " * 8 for i in range(12))
    chunks = chunk_record(normalize_darglobal(_darglobal_row(text=body)))
    assert len(chunks) > 1
    assert all(c.text.startswith("[DarGlobal project] DG1 | Dubai, United Arab Emirates") for c in chunks)
    assert all(len(c.text) <= MAX_CHARS + 300 for c in chunks)
    assert [c.id for c in chunks] == [f"darglobal:dg1#{i}" for i in range(len(chunks))]
    assert "city" in chunks[0].metadata() and "price" not in chunks[0].metadata()  # None values dropped


def test_darglobal_clean_text_cuts_cross_project_carousel():
    html = (
        "<body><h1>DG1</h1><p>Tower in Business Bay with canal views and a sky garden.</p>"
        "<div>Other projects</div><p>W Residences</p><div>Register Your Interest</div></body>"
    )
    text = DarGlobalScraper.clean_text(html)
    assert "Business Bay" in text and "W Residences" not in text


def test_discover_projects_reads_cards_and_skips_navigation():
    html = (
        '<body><nav><a href="/about">About</a></nav>'
        '<a href="/dg1"><span>Dubai, United Arab Emirates</span><h3>DG1</h3></a>'
        '<a href="/one-of-one/x"><span>AIDA | Oman</span><h3>Azure Villas</h3><p>tagline</p></a>'
        '<a href="/projects/properties-in-oman"><span>Luxury</span><span>Properties in Oman</span></a>'
        '<a href="/press"><span>News</span></a></body>'
    )
    projects = DarGlobalScraper().discover_projects(html)
    assert projects == [
        {"href": "/dg1", "location": "Dubai, United Arab Emirates", "name": "DG1"},
        {"href": "/one-of-one/x", "location": "AIDA | Oman", "name": "Azure Villas"},
    ]
