"""Retrieve ingredients by their Spanish and Italian names and aliases."""

from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata

from rapidfuzz.distance import DamerauLevenshtein
from rank_bm25 import BM25Okapi

CONNECTORS = frozenset({"a", "d", "de", "del", "di", "da", "el", "la", "las", "los", "al", "il"})
METHODS = {
    "exact": "Exacta",
    "fuzzy": "Exacta + difusa",
    "bm25": "BM25 + contexto",
}
CONTEXT_PATTERN = re.compile(r"^(.+?) (?:para|per) (.+)$")


@dataclass(frozen=True)
class SearchResult:
    ingredient: dict
    match: str


@dataclass(frozen=True)
class QueryResults:
    hits: list[SearchResult]
    context: str | None = None
    use: str | None = None


def normalize(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", text))


def document_tokens(normalized):
    return set(normalized.split()) - CONNECTORS


class IngredientSearch:
    def __init__(self, ingredients, relations=(), uses=None):
        self.ingredients = sorted(ingredients, key=lambda row: (normalize(row["name_es"]), row["id"]))
        self.primary_names = []
        self.terms = []
        self.documents = []
        for ingredient in self.ingredients:
            names = (ingredient["name_es"], ingredient["name_it"], ingredient["reference_it"])
            primary = {normalize(name) for name in names if name} - {""}
            aliases = ingredient["aliases_es"] + ingredient["aliases_it"]
            terms = primary | ({normalize(alias) for alias in aliases} - {""})
            self.primary_names.append(primary)
            self.terms.append(terms)
            self.documents.append(document_tokens(" ".join(terms)))

        corpus = [sorted(document) for document in self.documents]
        self.bm25 = BM25Okapi(corpus) if any(corpus) else None
        self.uses = uses or {}
        self.relations_by_id = defaultdict(list)
        for relation in relations:
            self.relations_by_id[relation["from"]].append(relation)

    def search(self, query, limit=5, *, method="bm25"):
        return self.lookup(query, limit, method=method).hits

    def lookup(self, query, limit=5, *, method="bm25"):
        if method not in METHODS:
            raise ValueError(f"Método desconocido: {method}")
        query = normalize(query)
        if not query or limit <= 0:
            return QueryResults([])
        # Preserve complete names even when a term contains "para" or "per".
        results = self._rank(query, limit, method)
        if results and results[0].match == "exact":
            return QueryResults(results)
        contextual = CONTEXT_PATTERN.fullmatch(query)
        if method == "bm25" and contextual:
            ingredient, context = contextual.groups()
            use = self.resolve_use(context)
            return QueryResults(self._rank(ingredient, limit, method), context, use)
        return QueryResults(results)

    def resolve_use(self, context):
        context = normalize(context)
        candidates = []
        for use_id, definition in self.uses.items():
            for alias in definition["aliases"]:
                normalized = normalize(alias)
                if context == normalized:
                    candidates.append(use_id)
                    break
        matching_uses = set(candidates)
        return matching_uses.pop() if len(matching_uses) == 1 else None

    def relations_for(self, ingredient_id, use=None):
        eligible = [
            relation for relation in self.relations_by_id.get(ingredient_id, ())
            if (use is None or relation.get("use") == use)
            and relation.get("human_review") != "rejected"
        ]
        # Rank by evidence for this use; a name match alone says nothing about substitution.
        return sorted(eligible, key=lambda relation: (
            relation["type"] != "culinary_substitute",
            relation.get("human_review") != "accepted",
            relation.get("evidence") != "direct",
        ))

    def _rank(self, query, limit, method):
        exact = [index for index, terms in enumerate(self.terms) if query in terms]
        if exact:
            exact.sort(key=lambda index: query not in self.primary_names[index])
            return self._results(exact, "exact", limit)
        if method == "exact":
            return []

        tokens = document_tokens(query)
        if method == "bm25" and self.bm25 is not None and len(tokens) >= 2:
            # Require all content words so an extra qualifier cannot silently disappear.
            candidates = [
                index for index, document in enumerate(self.documents) if tokens <= document
            ]
            if candidates:
                scores = self.bm25.get_batch_scores(sorted(tokens), candidates)
                ranked = [index for index, _ in sorted(zip(candidates, scores), key=lambda row: -row[1])]
                return self._results(ranked, "bm25", limit)

        if len(query) >= 3:
            prefix = [
                index for index, terms in enumerate(self.terms)
                if any(term.startswith(query) for term in terms)
            ]
            if prefix:
                return self._results(prefix, "prefix", limit)

        if len(query) < 4:
            return []
        max_distance = 2 if len(query) >= 8 else 1
        distances = []
        for index, terms in enumerate(self.terms):
            distance = min(
                (DamerauLevenshtein.distance(query, term, score_cutoff=max_distance) for term in terms),
                default=max_distance + 1,
            )
            if distance <= max_distance:
                distances.append((distance, index))
        return self._results([index for _, index in sorted(distances)], "fuzzy", limit)

    def _results(self, indices, match, limit):
        return [SearchResult(self.ingredients[index], match) for index in indices[:limit]]


def search(query, ingredients, limit=5):
    return IngredientSearch(ingredients).search(query, limit)
