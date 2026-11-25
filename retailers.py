"""Retailer configuration and conservative commercial-result relevance filters."""
from hashlib import sha256
import re
from urllib.parse import unquote, urlsplit

from search import normalize

RETAILERS = [
    {"id": "esselunga", "name": "Esselunga", "domains": ["esselunga.it"], "logo": "stores/esselunga.svg", "url": "https://www.esselunga.it/"},
    {"id": "penny", "name": "PENNY", "domains": ["penny.it"], "logo": "stores/penny.svg", "url": "https://www.penny.it/"},
    {"id": "lidl", "name": "Lidl", "domains": ["lidl.it"], "logo": "stores/lidl.svg", "url": "https://www.lidl.it/"},
    {"id": "conad", "name": "Conad", "domains": ["conad.it"], "logo": "stores/conad.svg", "url": "https://www.conad.it/"},
    {"id": "coop", "name": "Coop", "domains": ["coop.it", "coopshop.it"], "logo": "stores/coop.svg", "url": "https://www.coopshop.it/"},
]
DEFAULT_PREFERENCES = ["esselunga", "penny", "lidl"]
BLOCKED_DOMAINS = {"reddit.com", "redd.it", "instagram.com", "facebook.com", "fb.com", "tiktok.com",
                   "youtube.com", "youtu.be", "pinterest.com", "twitter.com", "x.com", "linkedin.com", "wikipedia.org"}
STOP_WORDS = {"di", "da", "de", "del", "della", "e", "a", "il", "lo", "la", "le", "i", "gli", "per", "in", "con", "un", "una"}
EXCLUDED_PATHS = re.compile(r"/(?:ricett\w*|recipes?|blog|news|magazine|faq|privacy|lavora\w*|carriere|negozi|punti-vendita|ricerca-negozio|aree-coperte|page)(?:/|[.\-]|$)")


def domain_matches(host, domain):
    return host == domain or host.endswith("." + domain)


def blocked_domain(host):
    return any(domain_matches(host, domain) for domain in BLOCKED_DOMAINS)


def retailer_options(country):
    return RETAILERS if normalize(country) in {"italia", "italy", "it"} else []


def custom_retailers(text):
    domains = [part.strip().lower().removeprefix("www.") for part in re.split(r"[,\s]+", text.strip()) if part.strip()]
    domains = list(dict.fromkeys(domains))
    if len(domains) > 3:
        raise ValueError("Añade como máximo tres dominios de comercios.")
    result = []
    for domain in domains:
        if (len(domain) > 120 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", domain)
                or blocked_domain(domain) or domain.endswith((".local", ".internal", ".localhost"))):
            raise ValueError("Usa dominios públicos de comercios, por ejemplo tienda.it, sin rutas ni redes sociales.")
        result.append({"id": "custom-" + sha256(domain.encode()).hexdigest()[:12], "name": domain,
                       "domains": [domain], "logo": None, "url": "https://" + domain})
    return result


def resolve_retailers(country, ids, custom_text=""):
    available = retailer_options(country)
    known = {row["id"]: row for row in available}
    ids = list(dict.fromkeys(ids))
    if any(value not in known for value in ids):
        raise ValueError("Revisa las tiendas seleccionadas para el país de destino.")
    selected = [known[value] for value in ids]
    custom = custom_retailers(custom_text)
    for row in custom:
        canonical = next((store for store in available if any(domain_matches(row["domains"][0], domain) for domain in store["domains"])), None)
        if canonical:
            if canonical["id"] not in {store["id"] for store in selected}:
                selected.append(canonical)
            continue
        if not any(domain_matches(row["domains"][0], domain) for store in selected for domain in store["domains"]):
            selected.append(row)
    if not selected:
        raise ValueError("Selecciona al menos una tienda o añade un dominio de comercio.")
    return selected


def commercial_result(hit, product, retailers):
    """Require a matching retailer AND a relevant product/catalog page, never stock."""
    from store_search import public_url
    if not isinstance(hit, dict) or not public_url(hit.get("url")):
        return None
    url = urlsplit(hit["url"])
    host = url.hostname.lower()
    if blocked_domain(host) or host.startswith(("ricette.", "corporate.", "lavoro.", "jobs.", "assistenza-")):
        return None
    retailer = next((store for store in retailers if any(domain_matches(host, domain) for domain in store["domains"])), None)
    path = unquote(url.path).lower()
    if not retailer or EXCLUDED_PATHS.search(path) or path.endswith((".pdf", ".jpg", ".png")):
        return None
    strong = bool(re.search(r"/(?:p|product|products|prodotto|pd)/", path) or re.search(r"(?:\d{8,}|/p\d{5,})", path)
                  or (retailer["id"] == "coop" and re.match(r"/il-prodotto-coop/[^/]+/[^/]+/[^/]+/[^/]+/[^/]+/?$", path)))
    catalog = bool(re.search(r"/(?:prodotti|catalogo|spesa-online)/.+", path))
    if not strong and not catalog:
        return None
    # Match terms in the title/URL rather than a generic snippet listing many foods.
    words = set(normalize(str(hit.get("title", "")) + " " + path).split())
    tokens = [word for word in normalize(product).split() if word not in STOP_WORDS]
    def match(token):
        return token in words or (len(token) >= 5 and any(len(word) >= 5 and token[:-1] == word[:-1] for word in words))
    if not tokens or not all(match(token) for token in tokens):
        return None
    title_words = normalize(str(hit.get("title", ""))).split()
    brand_words = set(normalize(retailer["name"]).split())
    while title_words and title_words[0] in brand_words:
        title_words.pop(0)
    main_title = bool(title_words and title_words[0] in tokens)
    # Brands can precede the ingredient (e.g. CAO Formaggi Pecorino Romano).
    # Do not accept a food merely containing it: "cioccolato al latte" or
    # "sofficini pomodoro e mozzarella" are different products.
    product_words = normalize(product).split()
    for start in range(1, min(4, len(title_words))):
        if (title_words[start:start + len(product_words)] == product_words
                and not set(title_words[:start]) & {"con", "al", "alla", "alle", "ai", "allo", "agli", "e", "ripieno", "ripiena"}):
            main_title = True
            break
    main_slug = any((parts := normalize(segment).split()) and parts[0] in tokens for segment in path.split("/"))
    if not main_title and not main_slug:
        return None
    return {**hit, "domain": host.removeprefix("www."), "retailer_id": retailer["id"],
            "retailer_name": retailer["name"], "evidence_type": "product_page" if strong else "catalog_listing",
            "evidence": "Ficha de producto" if strong else "Catálogo · producto por confirmar",
            "stock": "Desconocido", "location": "Sucursal o envío por comprobar"}
