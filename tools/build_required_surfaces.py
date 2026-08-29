#!/usr/bin/env python3
"""Build exact-50 localized support-site surfaces from a local source contract."""

from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "surface_source.json"
BUILD_RECEIPT = ROOT / "surface-build.json"
GENERATED_CSS = ROOT / "surface-generated.css"


def read_source() -> dict:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    if source.get("schema") != "support-required-surfaces/v1":
        raise SystemExit("surface_source.json has an unsupported schema")
    locales = source.get("official_locales", [])
    if len(locales) != 50 or len(set(locales)) != 50:
        raise SystemExit("surface_source.json must declare 50 unique locales")
    if set(source.get("locale_names", {})) != set(locales):
        raise SystemExit("locale_names must exactly match official_locales")
    required = {
        f"{locale}/{name}"
        for locale in locales
        for name in ("index.html", "support.html", "privacy.html")
    }
    preserved = set(source.get("preserved_surfaces", []))
    generated = set(source.get("generated_surfaces", []))
    if preserved | generated != required or preserved & generated:
        raise SystemExit(
            "preserved_surfaces and generated_surfaces must partition all 150 routes"
        )
    if set(source.get("preserved_surface_sha256", {})) != preserved:
        raise SystemExit("preserved_surface_sha256 must cover every preserved route")
    if not source.get("verified_app_store_urls"):
        raise SystemExit("verified_app_store_urls must not be empty")
    return source


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direction(locale: str, source: dict) -> str:
    return "rtl" if locale in set(source["rtl_locales"]) else "ltr"


def route_path(locale: str, surface: str) -> Path:
    name = "index.html" if surface == "index" else f"{surface}.html"
    return ROOT / locale / name


def canonical_url(source: dict, locale: str, surface: str) -> str:
    base = source["base_url"].rstrip("/") + "/"
    suffix = "" if surface == "index" else f"{surface}.html"
    return f"{base}{locale}/{suffix}"


def default_url(source: dict, surface: str) -> str:
    targets = source.get("preserved_root_hreflang_targets", {})
    if surface in targets:
        return targets[surface]
    base = source["base_url"].rstrip("/") + "/"
    return base if surface == "index" else f"{base}{surface}.html"


def og_locale(locale: str) -> str:
    explicit = {
        "zh-Hans": "zh_CN",
        "zh-Hant": "zh_TW",
        "ca": "ca_ES",
        "hr": "hr_HR",
        "cs": "cs_CZ",
        "da": "da_DK",
        "fi": "fi_FI",
        "el": "el_GR",
        "he": "he_IL",
        "hi": "hi_IN",
        "hu": "hu_HU",
        "id": "id_ID",
        "it": "it_IT",
        "ja": "ja_JP",
        "ko": "ko_KR",
        "ms": "ms_MY",
        "no": "nb_NO",
        "pl": "pl_PL",
        "ro": "ro_RO",
        "ru": "ru_RU",
        "sk": "sk_SK",
        "sv": "sv_SE",
        "th": "th_TH",
        "tr": "tr_TR",
        "uk": "uk_UA",
        "vi": "vi_VN",
    }
    if locale in explicit:
        return explicit[locale]
    parts = locale.replace("-", "_").split("_", 1)
    return parts[0] if len(parts) == 1 else f"{parts[0]}_{parts[1].upper()}"


def alternates(source: dict, surface: str) -> str:
    rows = []
    for locale in source["official_locales"]:
        rows.append(
            '<link rel="alternate" hreflang="{}" href="{}">'.format(
                html.escape(locale, quote=True),
                html.escape(canonical_url(source, locale, surface), quote=True),
            )
        )
    rows.append(
        '<link rel="alternate" hreflang="x-default" href="{}">'.format(
            html.escape(default_url(source, surface), quote=True)
        )
    )
    return "\n".join(rows)


def normalize_description(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= 180:
        return value
    prefix = value[:180]
    cut = max(prefix.rfind(mark) + 1 for mark in ".!?。！？")
    if cut < 100:
        cut = prefix.rfind(" ")
    if cut < 100:
        cut = 180
    return prefix[:cut].rstrip(" ,;:，；：")


def schema_payload(
    source: dict, locale: str, surface: str, content: dict, canonical: str
) -> dict:
    questions = [
        (heading, body)
        for heading, body in content.get("sections", [])
        if any(mark in heading for mark in ("?", "؟", "？"))
    ]
    payload: dict = {
        "@context": "https://schema.org",
        "@type": "FAQPage" if surface == "support" and questions else "WebPage",
        "name": content["title"],
        "description": content["description"],
        "inLanguage": locale,
        "url": canonical,
        "isPartOf": {
            "@type": "WebSite",
            "name": source["app"]["name"],
            "url": source["base_url"],
        },
    }
    app_id = source["app"].get("app_store_id")
    if app_id:
        payload["about"] = {
            "@type": "MobileApplication",
            "name": source["app"]["name"],
            "operatingSystem": "iOS",
            "sameAs": f"https://apps.apple.com/app/id{app_id}",
        }
    if surface == "support" and questions:
        payload["mainEntity"] = [
            {
                "@type": "Question",
                "name": heading,
                "acceptedAnswer": {"@type": "Answer", "text": body},
            }
            for heading, body in questions
        ]
    return payload


def language_links(source: dict, surface: str, current: str) -> str:
    links = []
    for locale in source["official_locales"]:
        current_attr = ' aria-current="page"' if locale == current else ""
        links.append(
            '<a hreflang="{}" lang="{}" href="{}"{}>{}</a>'.format(
                html.escape(locale, quote=True),
                html.escape(locale, quote=True),
                html.escape(canonical_url(source, locale, surface), quote=True),
                current_attr,
                html.escape(source["locale_names"][locale]),
            )
        )
    return "\n".join(links)


def crosspromo_assets(source: dict) -> tuple[list[tuple[str, str, str]], str]:
    source_path = ROOT / source["crosspromo_source"]
    raw = source_path.read_bytes().decode("utf-8")
    match = re.search(
        r"<!-- ls-family:start -->(.*?)<!-- ls-family:end -->", raw, re.S
    )
    if not match:
        raise SystemExit(f"{source_path.relative_to(ROOT)} lacks the cross-promo block")
    block = match.group(1)
    cards = []
    for card in re.finditer(
        r'<a\s+href="(https://apps\.apple\.com/[^"]+)"[^>]*>'
        r'.*?<img\s+src="([^"]+)"[^>]*>'
        r".*?<strong[^>]*>(.*?)</strong>",
        block,
        re.I | re.S,
    ):
        url = html.unescape(card.group(1))
        image = html.unescape(card.group(2))
        name = html.unescape(re.sub(r"<[^>]+>", "", card.group(3))).strip()
        cards.append((url, image, name))
    guide_match = re.search(
        r'href="(https://alice51849\.github\.io/ios-app-guide/[^"]*)"',
        block,
        re.I,
    )
    if len(cards) != 4 or not guide_match:
        raise SystemExit("cross-promo source must contain four app cards and one guide")
    allowed = set(source["verified_app_store_urls"])
    if any(url not in allowed for url, _, _ in cards):
        raise SystemExit("cross-promo source contains an unverified App Store URL")
    return cards, html.unescape(guide_match.group(1))


def render_crosspromo(source: dict, locale: str, content: dict) -> str:
    cards, guide_url = crosspromo_assets(source)
    labels = source["crosspromo_labels"][locale]
    card_rows = []
    for url, image, name in cards:
        card_rows.append(
            f'<a href="{html.escape(url, quote=True)}" rel="noopener" '
            'style="display:flex;align-items:center;gap:12px;padding:12px 14px;'
            'background:rgba(127,127,127,.10);border:1px solid '
            'rgba(127,127,127,.22);border-radius:16px;text-decoration:none;'
            'color:inherit;min-width:0">'
            f'<img src="{html.escape(image, quote=True)}" alt="" width="46" '
            'height="46" loading="lazy" style="border-radius:11px;flex:0 0 auto">'
            '<span style="min-width:0">'
            f'<strong style="display:block;font-size:14px;line-height:1.35">'
            f"{html.escape(name)}</strong>"
            '<span style="display:block;font-size:12px;line-height:1.4;opacity:.72">'
            f'{html.escape(content["labels"]["app_store"])}</span></span></a>'
        )
    text_align = "right" if direction(locale, source) == "rtl" else "left"
    return (
        '<!-- ls-family:start --><section data-surface-crosspromo="true" '
        f'dir="{direction(locale, source)}" '
        f'aria-label="{html.escape(labels["heading"], quote=True)}" '
        'style="max-width:920px;margin:34px auto 26px;padding:20px 22px;'
        'background:rgba(127,127,127,.08);border:1px solid '
        'rgba(127,127,127,.18);border-radius:20px;font-family:inherit;'
        f'color:inherit;text-align:{text_align}">'
        '<h2 style="margin:0 0 14px;font-size:17px;color:inherit">'
        f'{html.escape(labels["heading"])}</h2>'
        '<div style="display:grid;grid-template-columns:'
        'repeat(auto-fit,minmax(240px,1fr));gap:10px">'
        f'{"".join(card_rows)}</div>'
        '<p style="margin:10px 0 0;font-size:12px;opacity:.66">'
        f'{html.escape(labels["store_note"])}</p>'
        '<p style="margin:6px 0 0;font-size:12px;opacity:.66">'
        f'<a href="{html.escape(guide_url, quote=True)}" rel="noopener" '
        'style="color:inherit;text-decoration:underline">'
        f'{html.escape(labels["guides"])}</a></p></section>'
        '<!-- ls-family:end -->'
    )


def render_generated_page(
    source: dict, locale: str, surface: str, content: dict
) -> str:
    canonical = canonical_url(source, locale, surface)
    title = normalize_description(content["title"])
    description = normalize_description(content["description"])
    app_name = content.get("app_name") or source["app"]["name"]
    home_label = content["labels"]["home"]
    support_label = content["labels"]["support"]
    privacy_label = content["labels"]["privacy"]
    contact_label = content["labels"]["contact"]
    locale_label = content["labels"]["language"]
    nav = (
        f'<a href="{html.escape(canonical_url(source, locale, "index"), quote=True)}">'
        f"{html.escape(home_label)}</a>"
        f'<a href="{html.escape(canonical_url(source, locale, "support"), quote=True)}">'
        f"{html.escape(support_label)}</a>"
        f'<a href="{html.escape(canonical_url(source, locale, "privacy"), quote=True)}">'
        f"{html.escape(privacy_label)}</a>"
    )
    notice = ""
    if source["app"].get("kids"):
        notice_text = source["parent_notice"][locale]
        notice = (
            '<aside class="surface-notice" data-surface-parent-notice="true">'
            f"{html.escape(notice_text)}</aside>"
        )
    sections = []
    for heading, body in content.get("sections", []):
        sections.append(
            "<section class=\"surface-card\">"
            f"<h2>{html.escape(heading)}</h2>"
            f"<p>{html.escape(body)}</p>"
            "</section>"
        )
    app_cta = ""
    app_id = source["app"].get("app_store_id")
    if app_id:
        app_cta = (
            '<a class="surface-button" data-surface-own-app="true" '
            f'href="https://apps.apple.com/app/id{app_id}" rel="noopener">'
            f'{html.escape(content["labels"]["app_store"])}</a>'
        )
    email_subject = quote(f'{source["app"]["name"]} support')
    contact = (
        '<section class="surface-card surface-contact">'
        f"<h2>{html.escape(contact_label)}</h2>"
        f"<p>{html.escape(content['contact'])}</p>"
        f'<a class="surface-mail" href="mailto:hourstag.app@gmail.com?subject={email_subject}">'
        "hourstag.app@gmail.com</a>"
        f"{app_cta}</section>"
    )
    schema_content = dict(content)
    schema_content["description"] = description
    schema = json.dumps(
        schema_payload(source, locale, surface, schema_content, canonical),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    crosspromo = render_crosspromo(source, locale, content)
    return f"""<!doctype html>
<html lang="{html.escape(locale, quote=True)}" dir="{direction(locale, source)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
{alternates(source, surface)}
<meta property="og:type" content="website">
<meta property="og:locale" content="{html.escape(og_locale(locale), quote=True)}">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{html.escape(canonical, quote=True)}">
<link rel="stylesheet" href="../surface-generated.css">
<script type="application/ld+json">{schema}</script>
</head>
<body>
<header class="surface-header">
  <a class="surface-brand" href="{html.escape(canonical_url(source, locale, 'index'), quote=True)}">{html.escape(app_name)}</a>
  <nav aria-label="Primary">{nav}</nav>
</header>
<main>
  {notice}
  <section class="surface-hero">
    <p class="surface-eyebrow">{html.escape(content["eyebrow"])}</p>
    <h1>{html.escape(content["heading"])}</h1>
    <p>{html.escape(content["lead"])}</p>
  </section>
  {"".join(sections)}
  {contact}
</main>
{crosspromo}
<details class="surface-languages">
  <summary>{html.escape(locale_label)} · {html.escape(source["locale_names"][locale])}</summary>
  <nav aria-label="{html.escape(locale_label, quote=True)}">
    {language_links(source, surface, locale)}
  </nav>
</details>
<footer>© 2026 Lumi Studio · {html.escape(app_name)}</footer>
</body>
</html>
"""


class SurfaceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attrs: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.alternates: dict[str, list[str]] = {}
        self.ld_json: list[str] = []
        self._ld = False
        self._ld_parts: list[str] = []
        self._skip = 0
        self.visible: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag == "html":
            self.html_attrs = values
        if tag in {"style", "script"}:
            self._skip += 1
        if tag == "link":
            rel = values.get("rel", "").casefold()
            if rel == "canonical":
                self.canonicals.append(values.get("href", ""))
            elif rel == "alternate":
                self.alternates.setdefault(
                    values.get("hreflang", ""), []
                ).append(values.get("href", ""))
        if (
            tag == "script"
            and values.get("type", "").casefold() == "application/ld+json"
        ):
            self._ld = True
            self._ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld:
            self.ld_json.append("".join(self._ld_parts))
            self._ld = False
            self._ld_parts = []
        if tag in {"style", "script"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._ld:
            self._ld_parts.append(data)
        if not self._skip:
            self.visible.append(data)


MANAGED_ALT_RE = re.compile(
    r"<!-- surface-contract-alternates:start -->\n.*?"
    r"<!-- surface-contract-alternates:end -->\n",
    re.S,
)
MANAGED_SCHEMA_RE = re.compile(
    r"<!-- surface-contract-schema:start -->\n.*?"
    r"<!-- surface-contract-schema:end -->\n",
    re.S,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
APP_STORE_RE = re.compile(r"https://apps\.apple\.com/[^\s\"'<>]+")
RAW_TOKEN_RE = re.compile(
    r"(?:\{\{.*?\}\}|%s|\b(?:TODO|TBD|LOREM|PLACEHOLDER|XXX)\b|"
    r"\b(?:support|privacy|feature|button|screen|creator)\.[a-z0-9_.-]+\b)",
    re.S,
)


def parse_surface(text: str) -> SurfaceParser:
    parser = SurfaceParser()
    parser.feed(text)
    parser.close()
    return parser


def strip_managed_blocks(text: str) -> str:
    return MANAGED_SCHEMA_RE.sub("", MANAGED_ALT_RE.sub("", text))


def valid_schema(parser: SurfaceParser, locale: str, canonical: str) -> bool:
    for raw in parser.ld_json:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid pre-existing JSON-LD: {exc}") from exc
        candidates = value if isinstance(value, list) else [value]
        if any(
            isinstance(item, dict)
            and item.get("@context") == "https://schema.org"
            and item.get("inLanguage") == locale
            and item.get("url") == canonical
            for item in candidates
        ):
            return True
    return False


def expected_alternate_url(
    source: dict, locale: str, surface: str, preserved: bool
) -> str:
    if locale == "x-default":
        return default_url(source, surface)
    if preserved and locale in set(source["preserved_root_hreflang_locales"]):
        return default_url(source, surface)
    return canonical_url(source, locale, surface)


def verify_preserved_base(
    source: dict, locale: str, surface: str, relative: str, text: str
) -> SurfaceParser:
    expected_sha = source["preserved_surface_sha256"][relative]
    actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_sha != expected_sha:
        raise SystemExit(
            f"{relative}: remote-authored bytes changed outside managed augmentations"
        )
    parser = parse_surface(text)
    canonical = canonical_url(source, locale, surface)
    if parser.html_attrs.get("lang") != locale:
        raise SystemExit(f"{relative}: remote lang is objectively deficient")
    if parser.html_attrs.get("dir") != direction(locale, source):
        raise SystemExit(f"{relative}: remote dir is objectively deficient")
    if parser.canonicals != [canonical]:
        raise SystemExit(f"{relative}: remote canonical is objectively deficient")
    if text.count("<!-- ls-family:start -->") != 1 or text.count(
        "<!-- ls-family:end -->"
    ) != 1:
        raise SystemExit(f"{relative}: remote cross-promo is objectively deficient")
    emails = {value.casefold().rstrip(".") for value in EMAIL_RE.findall(text)}
    if emails != {"hourstag.app@gmail.com"}:
        raise SystemExit(f"{relative}: remote contact email is objectively deficient")
    if RAW_TOKEN_RE.search(" ".join(parser.visible)):
        raise SystemExit(f"{relative}: remote page contains a raw localization token")
    allowed_urls = set(source["verified_app_store_urls"])
    for match in APP_STORE_RE.findall(text):
        url = html.unescape(match).rstrip(".,;:)]}")
        if url not in allowed_urls:
            raise SystemExit(f"{relative}: unverified App Store URL {url}")
    permitted = (
        set(source["official_locales"])
        | {"x-default"}
        | set(source["preserved_hreflang_aliases"])
    )
    if not set(parser.alternates).issubset(permitted):
        raise SystemExit(f"{relative}: unexpected remote hreflang")
    for key, values in parser.alternates.items():
        expected = expected_alternate_url(source, key, surface, True)
        if values != [expected]:
            raise SystemExit(f"{relative}: invalid or duplicate {key} alternate")
    return parser


def augment_preserved_page(
    source: dict, locale: str, surface: str, relative: str, current: str
) -> str:
    base = strip_managed_blocks(current)
    parser = verify_preserved_base(source, locale, surface, relative, base)
    missing = [
        value
        for value in [*source["official_locales"], "x-default"]
        if value not in parser.alternates
    ]
    text = base
    if missing:
        rows = [
            '<link rel="alternate" hreflang="{}" href="{}">'.format(
                html.escape(value, quote=True),
                html.escape(
                    expected_alternate_url(source, value, surface, False),
                    quote=True,
                ),
            )
            for value in missing
        ]
        block = (
            "<!-- surface-contract-alternates:start -->\n"
            + "\n".join(rows)
            + "\n<!-- surface-contract-alternates:end -->\n"
        )
        xdefault = re.search(
            r"<link\b(?=[^>]*\brel=[\"']alternate[\"'])"
            r"(?=[^>]*\bhreflang=[\"']x-default[\"'])[^>]*>",
            text,
            re.I,
        )
        head_end = re.search(r"</head\s*>", text, re.I)
        position = xdefault.start() if xdefault else (
            head_end.start() if head_end else -1
        )
        if position < 0:
            raise SystemExit(f"{relative}: missing </head>")
        text = text[:position] + block + text[position:]
    canonical = canonical_url(source, locale, surface)
    if not valid_schema(parser, locale, canonical):
        block = (
            "<!-- surface-contract-schema:start -->\n"
            '<script type="application/ld+json">'
            f"{managed_schema_from_text(source, locale, canonical, base)}"
            "</script>\n"
            "<!-- surface-contract-schema:end -->\n"
        )
        head_end = re.search(r"</head\s*>", text, re.I)
        if not head_end:
            raise SystemExit(f"{relative}: missing </head>")
        position = head_end.start()
        text = text[:position] + block + text[position:]
    return text


def managed_schema_from_text(
    source: dict, locale: str, canonical: str, text: str
) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", text, re.I | re.S)
    title = (
        html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
        if match
        else source["app"]["name"]
    )
    payload = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "inLanguage": locale,
        "url": canonical,
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).replace("</", "<\\/")


def inject_parent_notice(source: dict, locale: str, text: str) -> str:
    if not source["app"].get("kids"):
        return text
    text = re.sub(
        r"\s*<!-- surface-parent-notice:start -->.*?<!-- surface-parent-notice:end -->\s*",
        "\n",
        text,
        flags=re.S,
    )
    notice = (
        "\n<!-- surface-parent-notice:start -->"
        '<aside data-surface-parent-notice="true" '
        'style="max-width:1060px;margin:16px auto;padding:12px 16px;'
        'border:1px solid currentColor;border-radius:14px;opacity:.88">'
        f"{html.escape(source['parent_notice'][locale])}</aside>"
        "<!-- surface-parent-notice:end -->\n"
    )
    return re.sub(r"<body\b[^>]*>", lambda m: m.group(0) + notice, text, count=1, flags=re.I)


def patch_hourstag_faq(source: dict, locale: str, text: str) -> str:
    if source["site_key"] != "hourstag-support":
        return text
    if 'data-surface-paid-contract="true"' in text:
        return re.sub(
            r'(<details\s+class=["\']faq["\'][^>]*'
            r'data-surface-paid-contract=["\']true["\'][^>]*>.*?'
            r"<summary\b[^>]*>.*?</summary>\s*<p\b[^>]*>).*?(</p>\s*</details>)",
            lambda match: (
                match.group(1)
                + html.escape(source["hourstag_paid"][locale]["answer"])
                + match.group(2)
            ),
            text,
            count=1,
            flags=re.I | re.S,
        )
    blocks = list(
        re.finditer(
            r'<details\s+class=["\']faq["\'][^>]*>.*?</details>',
            text,
            re.I | re.S,
        )
    )
    if len(blocks) < 7:
        return text
    first, last = blocks[0].start(), blocks[-1].end()
    raw_blocks = [match.group(0) for match in blocks]
    question_match = re.search(
        r"<summary\b[^>]*>(.*?)</summary>", raw_blocks[3], re.I | re.S
    )
    question = (
        question_match.group(1)
        if question_match
        else html.escape(source["hourstag_paid"][locale]["question"])
    )
    corrected = (
        '<details class="faq" data-surface-paid-contract="true">'
        f"<summary>{question}</summary>"
        f"<p>{html.escape(source['hourstag_paid'][locale]['answer'])}</p>"
        "</details>"
    )
    kept = raw_blocks[:3] + [corrected] + raw_blocks[6:]
    return text[:first] + "".join(kept) + text[last:]


def infer_help_locale(path: Path) -> str:
    if path.name == "help.html":
        return "en-US"
    match = re.fullmatch(r"help\.([^.]+(?:-[^.]+)?)\.html", path.name)
    return match.group(1) if match else "en-US"


def patch_hourstag_help(source: dict, locale: str, text: str) -> str:
    if source["site_key"] != "hourstag-support":
        return text
    paid = source["hourstag_paid"][locale]["answer"]
    already_managed = 'data-surface-paid-contract="true"' in text
    pair_pattern = re.compile(
        r'(<p\s+class=["\']hd-q["\'][^>]*>.*?</p>)\s*'
        r'(<p\s+class=["\']hd-a["\'][^>]*>.*?</p>)',
        re.I | re.S,
    )
    pairs = list(pair_pattern.finditer(text))
    if len(pairs) >= 5:
        if already_managed:
            text = re.sub(
                r'(<p\s+class=["\']hd-a["\'][^>]*'
                r'data-surface-paid-contract=["\']true["\'][^>]*>).*?(</p>)',
                lambda match: match.group(1) + html.escape(paid) + match.group(2),
                text,
                count=1,
                flags=re.I | re.S,
            )
        else:
            first, last = pairs[0].start(), pairs[-1].end()
            raw_pairs = [match.group(0) for match in pairs]
            paid_pair = re.sub(
                r'<p\s+class=["\']hd-a["\'][^>]*>.*?</p>',
                (
                    '<p class="hd-a" data-surface-paid-contract="true">'
                    f"{html.escape(paid)}</p>"
                ),
                raw_pairs[1],
                count=1,
                flags=re.I | re.S,
            )
            kept = raw_pairs[:1] + [paid_pair] + raw_pairs[2:3] + raw_pairs[4:]
            text = text[:first] + "".join(kept) + text[last:]

    def update_schema(match: re.Match[str]) -> str:
        raw = match.group(2)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return match.group(0)
        if not isinstance(payload, dict) or payload.get("@type") != "FAQPage":
            return match.group(0)
        entities = payload.get("mainEntity")
        if not isinstance(entities, list) or len(entities) < 2:
            return match.group(0)
        answer = entities[1].get("acceptedAnswer")
        if isinstance(answer, dict):
            answer["text"] = paid
        if not already_managed and len(entities) >= 4:
            del entities[3]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return match.group(1) + encoded.replace("</", "<\\/") + match.group(3)

    text = re.sub(
        r'(<script\s+type=["\']application/ld\+json["\'][^>]*>)(.*?)(</script>)',
        update_schema,
        text,
        flags=re.I | re.S,
    )
    section_match = re.search(
        r'(<section\s+id=["\']troubleshooting["\'][^>]*>)(.*?)(</section>)',
        text,
        re.I | re.S,
    )
    if section_match:
        body = section_match.group(2)
        rows = list(
            re.finditer(r"(<h3\b[^>]*>.*?</h3>)\s*(<p\b[^>]*>.*?</p>)", body, re.I | re.S)
        )
        if rows:
            last = rows[-1]
            replacement = (
                last.group(1)
                + '<p data-surface-paid-reinstall="true">'
                + html.escape(paid)
                + "</p>"
            )
            body = body[: last.start()] + replacement + body[last.end() :]
            text = (
                text[: section_match.start()]
                + section_match.group(1)
                + body
                + section_match.group(3)
                + text[section_match.end() :]
            )
    return text


def write_css(source: dict) -> None:
    accent = source["palette"]["accent"]
    accent2 = source["palette"]["accent2"]
    GENERATED_CSS.write_text(
        f"""*{{box-sizing:border-box}}html{{color-scheme:light dark}}body{{margin:0;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",sans-serif;line-height:1.65;color:#272334;background:radial-gradient(circle at 12% 0,{accent}24,transparent 34rem),radial-gradient(circle at 90% 8%,{accent2}20,transparent 32rem),#faf9fd}}a{{color:{accent}}}.surface-header,.surface-header nav,.surface-contact,.surface-languages nav{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}.surface-header{{max-width:1040px;margin:auto;padding:22px 20px;justify-content:space-between}}.surface-brand{{font-size:1.05rem;font-weight:750;text-decoration:none;color:inherit}}.surface-header nav a{{padding:8px 10px;text-decoration:none}}main,.surface-languages,footer{{width:min(920px,calc(100% - 32px));margin:auto}}.surface-notice{{margin:4px 0 16px;padding:12px 16px;border:1px solid {accent}55;border-radius:15px;background:{accent}12}}.surface-hero{{padding:44px 0 24px}}.surface-eyebrow{{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:{accent};font-weight:700}}h1{{font-size:clamp(2rem,7vw,4.2rem);line-height:1.05;letter-spacing:-.035em;margin:.25em 0}}h2{{font-size:1.2rem;margin-top:0}}.surface-card{{padding:22px;margin:14px 0;border:1px solid {accent}30;border-radius:22px;background:rgba(255,255,255,.78);box-shadow:0 20px 60px {accent}12}}.surface-contact{{align-items:flex-start;flex-direction:column}}.surface-mail,.surface-button{{display:inline-flex;min-height:44px;align-items:center;padding:10px 16px;border-radius:14px;text-decoration:none;font-weight:700}}.surface-mail{{border:1px solid {accent}55}}.surface-button{{color:white;background:linear-gradient(135deg,{accent},{accent2})}}.surface-languages{{margin-top:28px;padding:16px;border:1px solid {accent}30;border-radius:18px}}.surface-languages summary{{cursor:pointer;font-weight:700}}.surface-languages nav{{padding-top:12px;align-items:stretch}}.surface-languages nav a{{padding:7px 10px;border-radius:9px;text-decoration:none;background:{accent}0d}}footer{{padding:30px 0 44px;opacity:.65}}[dir=rtl] .surface-header,[dir=rtl] .surface-contact{{text-align:right}}@media(prefers-color-scheme:dark){{body{{color:#f5f0ff;background:radial-gradient(circle at 12% 0,{accent}38,transparent 34rem),radial-gradient(circle at 90% 8%,{accent2}28,transparent 32rem),#100d17}}.surface-card{{background:rgba(28,23,39,.86)}}}}""",
        encoding="utf-8",
    )


def update_sitemap(source: dict) -> None:
    path = ROOT / "sitemap.xml"
    marker = re.compile(
        r"<!-- surface-contract-routes:start -->\n.*?"
        r"<!-- surface-contract-routes:end -->\n",
        re.S,
    )
    current = path.read_bytes().decode("utf-8")
    base = marker.sub("", current)
    if hashlib.sha256(base.encode("utf-8")).hexdigest() != source[
        "preserved_sitemap_sha256"
    ]:
        raise SystemExit("sitemap.xml changed outside the managed route block")
    urls = {
        html.unescape(value.strip())
        for value in re.findall(r"<loc\b[^>]*>(.*?)</loc>", base, re.I | re.S)
        if value.strip()
    }
    missing: list[str] = []
    for locale in source["official_locales"]:
        for surface in ("index", "support", "privacy"):
            url = canonical_url(source, locale, surface)
            if url not in urls:
                missing.append(url)
    text = base
    if missing:
        block = (
            "<!-- surface-contract-routes:start -->\n"
            + "\n".join(
                f"  <url><loc>{html.escape(url)}</loc></url>"
                for url in sorted(missing)
            )
            + "\n<!-- surface-contract-routes:end -->\n"
        )
        urlset_end = re.search(r"</urlset\s*>", text, re.I)
        if not urlset_end:
            raise SystemExit("sitemap.xml lacks </urlset>")
        position = urlset_end.start()
        text = text[:position] + block + text[position:]
    path.write_bytes(text.encode("utf-8"))


def main() -> None:
    source = read_source()
    write_css(source)
    outputs: list[Path] = []
    preserved = set(source["preserved_surfaces"])
    generated = set(source["generated_surfaces"])
    content = source.get("content", {})
    for locale in source["official_locales"]:
        locale_content = content.get(locale, {})
        for surface in ("index", "support", "privacy"):
            path = route_path(locale, surface)
            relative = str(path.relative_to(ROOT))
            if relative in generated:
                if surface not in locale_content:
                    raise SystemExit(f"missing generated source for {relative}")
                path.parent.mkdir(parents=True, exist_ok=True)
                text = render_generated_page(
                    source, locale, surface, locale_content[surface]
                )
            elif relative in preserved and path.is_file():
                current = path.read_bytes().decode("utf-8")
                text = augment_preserved_page(
                    source, locale, surface, relative, current
                )
            else:
                raise SystemExit(f"unclassified or missing route {relative}")
            path.write_bytes(text.encode("utf-8"))
            outputs.append(path)

    update_sitemap(source)
    records = {
        str(path.relative_to(ROOT)): file_sha(path)
        for path in sorted(outputs, key=lambda item: str(item.relative_to(ROOT)))
    }
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt = {
        "schema": "support-required-surfaces-build/v1",
        "site": source["site_key"],
        "officialLocaleCount": 50,
        "requiredSurfaceCount": 150,
        "preservedSurfaceCount": len(preserved),
        "generatedSurfaceCount": len(generated),
        "contentDigest": digest,
        "files": records,
    }
    BUILD_RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"PASS {source['site_key']} {digest} "
        f"preserved={len(preserved)} generated={len(generated)}"
    )


if __name__ == "__main__":
    main()
