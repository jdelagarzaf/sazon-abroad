"""Evaluation page."""

from evaluation_view import show_evaluation
from ingredient_views import get_catalog

catalog, _ = get_catalog()
show_evaluation(catalog)
