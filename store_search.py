"""Real Tavily search, bounded free-tier usage and conservative evidence labels."""
from datetime import datetime, timezone
from contextlib import contextmanager
from hashlib import sha256
from http.client import HTTPException
import ipaddress
import json
import os
from pathlib import Path
import socket
import sqlite3
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, ProxyHandler, build_opener

from local_model import NoRedirects
from retailers import BLOCKED_DOMAINS, RETAILERS, blocked_domain, domain_matches


class StoreSearchError(Exception):
    pass


class StoreSearchProvider(Protocol):
    def search(self, query: str, domains=None) -> list[dict]: ...


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        url = urlsplit(value)
        host = url.hostname
        if (url.scheme not in {"http", "https"} or not host or "." not in host or url.username
                or url.password or url.port not in {None, 80, 443} or any(c.isspace() or ord(c) < 32 for c in value)
                or host.endswith((".local", ".localhost", ".internal")) or host == "localhost"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class TavilySearch:
    def __init__(self, api_key=None, opener=None):
        self.api_key = os.environ.get("TAVILY_API_KEY", "").strip() if api_key is None else api_key.strip()
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirects())

    def search(self, query, domains=None):
        if not self.api_key or self.api_key == "PEGA_TU_CLAVE_AQUI":
            raise StoreSearchError("Falta TAVILY_API_KEY. Sigue docs/comercios.md y reinicia la aplicación.")
        payload = {"query": query, "topic": "general", "search_depth": "basic", "max_results": 8,
                   "auto_parameters": False, "include_answer": False, "include_raw_content": False,
                   "include_images": False}
        if domains:
            payload.update(include_domains=list(domains), include_domains_mode="restrict")
        else:
            payload["exclude_domains"] = sorted(BLOCKED_DOMAINS)
        request = Request("https://api.tavily.com/search", data=json.dumps(payload).encode(),
                          headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
                          method="POST")
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError()
            results, seen = [], set()
            for row in data["results"][:8]:
                if not isinstance(row, dict) or not public_url(row.get("url")):
                    continue
                url = row["url"]
                host = urlsplit(url).hostname.lower()
                if blocked_domain(host) or (domains and not any(domain_matches(host, domain) for domain in domains)):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                if not isinstance(row.get("title"), str) or not isinstance(row.get("content"), str):
                    continue
                results.append({"url": url, "domain": urlsplit(url).hostname.removeprefix("www."),
                                "title": row["title"][:250], "snippet": row["content"][:800],
                                "evidence": "Enlace candidato del buscador; producto por comprobar",
                                "stock": "Desconocido", "location": "Sucursal o envío por comprobar"})
            return results
        except HTTPError as error:
            message = ("La clave de Tavily no es válida." if error.code in {401, 403} else
                       "Tavily alcanzó una cuota o límite. No se activarán pagos automáticamente." if error.code in {429, 432, 433} else
                       "El proveedor de búsqueda no pudo completar la consulta.")
            raise StoreSearchError(message) from None
        except (TimeoutError, socket.timeout):
            raise StoreSearchError("La búsqueda agotó el tiempo de espera. Puedes volver a intentar.") from None
        except (URLError, OSError, HTTPException):
            raise StoreSearchError("No se pudo conectar con Tavily. Comprueba tu conexión.") from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise StoreSearchError("El buscador devolvió una respuesta no válida.") from None


class StoreSearchService:
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parent / ".runtime" / "stores.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, stamp REAL, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, count INTEGER)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def search(self, product, city, country, language="it", provider=None, domains=None):
        if not all(isinstance(value, str) and 0 < len(value.strip()) <= 160 for value in (product, city, country)):
            raise StoreSearchError("Indica producto, ciudad y país (máximo 160 caracteres cada uno).")
        verb = {"it": "comprare negozio", "es": "comprar tienda", "de": "kaufen Geschäft",
                "fr": "acheter magasin"}.get(language, "buy shop")
        query = f'{product.strip()} {verb} {city.strip()} {country.strip()}'
        domains = sorted(set(domains or []))
        if domains:
            # Product catalogs are national: requiring the city hides valid pages.
            # Retailer alternatives guide ranking; include_domains enforces scope.
            shops = list(dict.fromkeys(next((store["name"] for store in RETAILERS
                if any(domain_matches(domain, known) for known in store["domains"])), domain) for domain in domains))
            query = f'{json.dumps(product.strip(), ensure_ascii=False)} ({" OR ".join(shops)})'
        cache_scope = [query.casefold(), domains, city.strip().casefold(), country.strip().casefold(), language]
        key = sha256(("tavily-commercial-v4:" + json.dumps(cache_scope, ensure_ascii=False)).encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            row = db.execute("SELECT stamp,data FROM cache WHERE key=?", (key,)).fetchone()
        if row and now - row[0] < 86400:
            return {**json.loads(row[1]), "cached": True}
        provider = provider or TavilySearch()
        if isinstance(provider, TavilySearch) and (not provider.api_key or provider.api_key == "PEGA_TU_CLAVE_AQUI"):
            raise StoreSearchError("Falta TAVILY_API_KEY. Sigue docs/comercios.md y reinicia la aplicación.")
        try:
            limit = int(os.environ.get("SAZON_SEARCH_DAILY_LIMIT", "100"))
            if not 0 <= limit <= 100:
                raise ValueError()
        except ValueError:
            raise StoreSearchError("SAZON_SEARCH_DAILY_LIMIT debe ser un número entre 0 y 100.") from None
        day = datetime.now(timezone.utc).date().isoformat()
        # Reserve attempts atomically, including failures, to avoid unbounded retries.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO usage VALUES (?,0)", (day,))
            if db.execute("SELECT count FROM usage WHERE day=?", (day,)).fetchone()[0] >= limit:
                raise StoreSearchError("Se alcanzó el límite diario local de búsquedas nuevas. Se renueva a las 00:00 UTC; la caché sigue disponible.")
            db.execute("UPDATE usage SET count=count+1 WHERE day=?", (day,))
        results = provider.search(query, domains=domains) if domains else provider.search(query)
        data = {"product": product, "query": query, "queried_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "results": results, "cached": False}
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, now, json.dumps(data, ensure_ascii=False)))
        return data


def manual_search(product, city, country):
    return "https://www.google.com/search?" + urlencode({"q": f"{product} comprare {city} {country}"})


def group_stores(searches, total):
    """Candidate coverage is explicitly distinct from verified product coverage."""
    groups = {}
    for search in searches:
        for hit in search.get("results", []):
            group = groups.setdefault(hit["domain"], {"domain": hit["domain"], "products": [], "links": []})
            if search["product"] not in group["products"]:
                group["products"].append(search["product"])
            group["links"].append({**hit, "product": search["product"], "queried_at": search["queried_at"]})
    return sorted(groups.values(), key=lambda row: (-len(row["products"]), row["domain"]))
