"""Editable recipe drafts, exact quantities and a bounded local job queue.

Drafts are user documents, never additions to the food reference catalog.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import re
import sqlite3
from threading import BoundedSemaphore
from uuid import uuid4

from adaptation import AdaptationRequest
from search import normalize

ROOT = Path(__file__).resolve().parent
MAX_ROWS = 16
UNITS = {"g": ("g", 1), "gramos": ("g", 1), "kg": ("g", 1000),
         "ml": ("ml", 1), "l": ("ml", 1000), "litros": ("ml", 1000),
         "taza": ("taza", 1), "tazas": ("taza", 1),
         "cucharada": ("cda", 1), "cucharadas": ("cda", 1), "cda": ("cda", 1),
         "cucharadita": ("cdta", 1), "cucharaditas": ("cdta", 1), "cdta": ("cdta", 1),
         "pieza": ("pieza", 1), "piezas": ("pieza", 1)}
NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾])"
LINE = re.compile(rf"^({NUMBER})(?:\s+([^\s]+))?\s+(.+)$")


def split_line(line):
    """Only extract explicit leading amounts; ambiguous text remains editable."""
    line = re.sub(r"^\s*[-•*]\s*", "", line).strip()
    qualifier = re.fullmatch(r"(.+?)\s+(al gusto|cantidad necesaria)", line, flags=re.I)
    if qualifier:
        return {"name": qualifier[1], "amount": qualifier[2]}
    match = LINE.match(line)
    if not match:
        return {"name": line, "amount": ""}
    number, unit, rest = match.groups()
    if normalize(unit or "") in UNITS:
        return {"name": re.sub(r"^de\s+", "", rest, flags=re.I), "amount": f"{number} {unit}"}
    return {"name": f"{unit or ''} {rest}".strip(), "amount": number}


def extract_recipe(raw):
    """Parse a pasted ingredients block. No quantities or steps are generated."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 6000:
        raise ValueError("Pega una receta de entre 1 y 6000 caracteres.")
    ingredients, steps, mode, title = [], [], "ingredients", "Mi receta"
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    has_header = any(normalize(line.rstrip(":")) == "ingredientes" for line in lines)
    if has_header:
        mode = "title"
    for line in lines:
        heading = normalize(line.rstrip(":"))
        if heading == "ingredientes":
            mode = "ingredients"
        elif heading in {"preparacion", "instrucciones", "pasos", "elaboracion"}:
            mode = "steps"
        elif mode == "title":
            title = line[:120]
        elif mode == "steps":
            steps.append(line)
        else:
            ingredients.append({"id": uuid4().hex[:12], **split_line(line), "use": "", "preparation": ""})
    if not 1 <= len(ingredients) <= MAX_ROWS or any(len(row["name"]) > 160 for row in ingredients):
        raise ValueError("Usa una línea por ingrediente (máximo 16). Separa los pasos con el título Preparación.")
    return {"title": title, "raw": raw, "rows": ingredients, "steps": steps,
            "context": AdaptationRequest(query="", city="Milano").__dict__,
            "status": "editable", "progress": "", "error": None, "stores": None}


def quantity(amount):
    match = re.fullmatch(rf"({NUMBER})\s*([\w]+)?", amount.strip())
    if not match:
        return None
    number, unit = match.groups()
    try:
        number = {"½": "1/2", "¼": "1/4", "¾": "3/4"}.get(number, number)
        value = sum((Fraction(part.replace(",", ".")) for part in number.split()), Fraction())
        canonical, factor = UNITS.get(normalize(unit or ""), (None, None))
        # Unlabelled counts are not assumed to be compatible.
        if canonical is None or value <= 0:
            return None
        return value * factor, canonical
    except (ValueError, ZeroDivisionError):
        return None


def shopping_list(draft):
    groups = {}
    for position, row in enumerate(draft["rows"], 1):
        name = row.get("selected_name") or row.get("local_name")
        if not name:
            continue
        amount = row.get("selected_amount", "") if row.get("selected_name") else row["amount"]
        parsed = quantity(amount)
        key = (normalize(name), normalize(row.get("preparation", "")), parsed[1] if parsed else row["id"])
        if key not in groups:
            groups[key] = {"name": name, "amount": amount or "Por confirmar", "rows": [], "origins": [], "quantity": None,
                           "preparation": row.get("preparation", "")}
        item = groups[key]
        item["rows"].append(row["id"])
        item["origins"].append({"id": row["id"], "name": row["name"], "position": position, "amount": row["amount"]})
        if parsed:
            item["quantity"] = (item["quantity"] or Fraction()) + parsed[0]
            unit = parsed[1]
            if unit == "pieza" and item["quantity"] != 1:
                unit = "piezas"
            elif unit == "taza" and item["quantity"] > 1:
                unit = "tazas"
            item["amount"] = f"{item['quantity']} {unit}"
    return [{key: value for key, value in row.items() if key != "quantity"} for row in groups.values()]


class DraftStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / ".runtime" / "recipes.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, owner TEXT, revision INTEGER, data TEXT)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, owner, draft):
        draft = deepcopy(draft)
        draft.update(id=uuid4().hex, revision=0)
        with self.connect() as db:
            db.execute("INSERT INTO drafts VALUES (?,?,?,?)", (draft["id"], owner, 0, json.dumps(draft, ensure_ascii=False)))
        return draft

    def get(self, owner, draft_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM drafts WHERE id=? AND owner=?", (draft_id, owner)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM drafts WHERE owner=? ORDER BY rowid DESC LIMIT 30", (owner,)).fetchall()
        return [{"id": data["id"], "title": data["title"]} for (raw,) in rows if (data := json.loads(raw))]

    def save(self, owner, draft, revision):
        draft = deepcopy(draft)
        draft["revision"] = revision + 1
        with self.connect() as db:
            changed = db.execute("UPDATE drafts SET revision=?,data=? WHERE id=? AND owner=? AND revision=?",
                                 (revision + 1, json.dumps(draft, ensure_ascii=False), draft["id"], owner, revision)).rowcount
        if not changed:
            raise ValueError("La receta cambió en otra pestaña. Recarga para conservar la versión más reciente.")
        return draft


class LocalJobs:
    """One CPU inference job and at most two queued jobs per application process."""
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recipe-local")
        self.slots = BoundedSemaphore(3)
        self.instance = uuid4().hex

    def submit(self, function):
        if not self.slots.acquire(blocking=False):
            raise ValueError("Hay varias recetas en espera. Vuelve a intentar en unos minutos.")
        def run():
            try:
                function()
            finally:
                self.slots.release()
        try:
            self.pool.submit(run)
        except RuntimeError:
            self.slots.release()
            raise ValueError("El servicio se está cerrando. Reinicia e intenta otra vez.")


def translate_draft(draft, service, catalog, index, client, progress=lambda *_: None):
    """Translate original identities only. Substitution is a separate user action."""
    for number, row in enumerate(draft["rows"], 1):
        if row.get("local_name"):
            continue
        progress(f"Traduciendo {number} de {len(draft['rows'])}: {row['name']}")
        context = AdaptationRequest.from_mapping({**draft["context"], "query": row["name"],
                                                 "culinary_use": "", "preparation": row.get("preparation", "")})
        response = service.adapt(context, catalog, index, client)
        row.pop("manual", None)
        row["translation"] = response
        row["local_name"] = response["result"]["local_name"] or ""
    return draft
