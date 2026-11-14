"""Resolve catalog photos to Wikimedia Commons thumbnails and attribution."""

from html.parser import HTMLParser
import json
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from fetch_data import ROOT, write_json

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
DATA = ROOT / "data"
# The general Wikidata entries may show another variety or presentation.
PHOTO_OVERRIDES = {
    "chile_poblano": "Stacked Poblano Peppers - Flickr - joncutrer.jpg",
    "morron": "Green-Bell-Pepper.jpg",
    "jitomate": "Tomato scanned.jpg",
    "polenta": "Polenta uncooked.jpg",
    "fecula_maiz": "Corn Flour.jpg",
    "perejil": "Chopping parsley-01.jpg",
    "harina_trigo": "Wheat flour 01.jpg",
    "camote": None,
    "carne_cerdo": None,
}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def request_json(url, **params):
    query = urlencode({**params, "format": "json", "formatversion": 2})
    request = Request(
        f"{url}?{query}",
        headers={"User-Agent": "SazonAbroad/0.4 (https://github.com/jdelagarzaf/sazon-abroad)"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "error" in payload:
        raise ValueError(payload["error"].get("info", "Error de Wikimedia"))
    return payload


def photo_files(ingredients):
    qids = sorted({row["wikidata_id"] for row in ingredients if row["wikidata_id"]})
    filenames = {}
    for start in range(0, len(qids), 25):
        batch = qids[start:start + 25]
        payload = request_json(WIKIDATA_API, action="wbgetentities", ids="|".join(batch), props="claims")
        for qid, entity in payload["entities"].items():
            claims = entity.get("claims", {}).get("P18", [])
            ordered = sorted(claims, key=lambda claim: claim["rank"] != "preferred")
            for claim in ordered:
                filename = claim["mainsnak"].get("datavalue", {}).get("value")
                if claim["rank"] != "deprecated" and isinstance(filename, str):
                    filenames[qid] = filename
                    break
    return {
        row["id"]: PHOTO_OVERRIDES.get(row["id"], filenames.get(row["wikidata_id"]))
        for row in ingredients
    }


def normalize_filename(title):
    return title.replace("_", " ").strip()


def photo_metadata(info):
    metadata = info.get("extmetadata", {})
    license_name = metadata.get("LicenseShortName", {}).get("value", "")
    license_url = metadata.get("LicenseUrl", {}).get("value", "")
    license_path = urlsplit(license_url)
    if license_path.hostname != "creativecommons.org":
        license_url = None
    else:
        license_url = license_path._replace(scheme="https").geturl()

    is_public_domain = license_name == "Public domain"
    is_attribution_license = license_name.startswith(("CC BY ", "CC BY-SA "))
    if not (is_public_domain or license_name.startswith("CC0") or is_attribution_license):
        return None
    if metadata.get("Restrictions", {}).get("value") or info.get("mime") not in IMAGE_TYPES:
        return None

    parser = PlainText()
    parser.feed(metadata.get("Artist", {}).get("value", ""))
    author = " ".join("".join(parser.parts).split())
    if is_attribution_license and (not author or not license_url or author.lower() in {"unknown", "desconocido"}):
        return None
    thumbnail = urlsplit(info.get("thumburl", ""))
    source = urlsplit(info.get("descriptionurl", ""))
    if thumbnail.scheme != "https" or thumbnail.hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
        return None
    if source.scheme != "https" or source.hostname != "commons.wikimedia.org":
        return None
    return {
        "thumbnail": urlunsplit(thumbnail._replace(query="", fragment="")),
        "author": author,
        "license": "Dominio público" if is_public_domain else license_name,
        "license_url": license_url,
        "source": source.geturl(),
    }


def commons_photos(filenames):
    names = sorted({normalize_filename(name) for name in filenames if name})
    photos = {}
    # A reduced batch keeps URLs short and stays below the file metadata limit.
    for start in range(0, len(names), 20):
        batch = names[start:start + 20]
        payload = request_json(
            COMMONS_API, action="query", redirects=1,
            titles="|".join(f"File:{name}" for name in batch),
            prop="imageinfo", iiprop="url|extmetadata|mime", iiurlwidth=330,
            iiextmetadatafilter="Artist|LicenseShortName|LicenseUrl|Restrictions",
        )
        query = payload.get("query", {})
        for row in query.get("pages", []):
            entries = row.get("imageinfo")
            if entries:
                photos[row["title"]] = photo_metadata(entries[0])
        for change in reversed(query.get("normalized", []) + query.get("redirects", [])):
            photos[change["from"]] = photos.get(change["to"])
    return photos


def main():
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    files = photo_files(catalog["ingredients"])
    metadata = commons_photos(files.values())
    photos = {}
    for ingredient, filename in files.items():
        if filename:
            photo = metadata.get(f"File:{normalize_filename(filename)}")
            if photo:
                photos[ingredient] = photo
    write_json(DATA / "photos.json", photos)
    print(f"{len(photos)} de {len(files)} fichas con miniatura de Wikimedia Commons.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"No se pudieron actualizar las fotos: {error}") from error
