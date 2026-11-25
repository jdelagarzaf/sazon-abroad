"""One-name cold/warm/cache probe with local runtime metadata (not a percentile)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from adaptation import AdaptationRequest, AdaptationService
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="pepino")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / "startup-probe.json")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    try:
        client = OllamaClient(ModelSettings.from_env())
        def metadata(endpoint):
            with client.opener.open(client.settings.base_url + endpoint, timeout=10) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("Metadatos demasiado grandes.")
            return json.loads(raw)
        was_loaded = any(row["name"] == client.settings.model for row in metadata("/api/ps")["models"])
        catalog, index = get_catalog()
        context = AdaptationRequest.from_mapping({"query": args.query})
        timings = []
        for label in ("already_loaded" if was_loaded else "cold", "warm"):
            service = AdaptationService()
            started = time.perf_counter()
            response = service.adapt(context, catalog, index, client)
            timings.append({"label": label, "seconds": time.perf_counter() - started, "response": response})
        started = time.perf_counter()
        response = service.adapt(context, catalog, index, client)
        timings.append({"label": "application_cache", "seconds": time.perf_counter() - started, "response": response})
        result = {"timings": timings, "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "runtime": {"ollama": metadata("/api/version"),
                              "model": next(row for row in metadata("/api/tags")["models"] if row["name"] == client.settings.model),
                              "loaded": next(row for row in metadata("/api/ps")["models"] if row["name"] == client.settings.model)},
                  "timer": {"implementation": time.get_clock_info("perf_counter").implementation,
                            "resolution_seconds": time.get_clock_info("perf_counter").resolution},
                  "note": "One development-name probe, not a percentile. Unload the selected model first for a cold measurement."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        for row in timings:
            print(f"{row['label']}: {row['seconds']:.3f} s")
    except (ModelError, OSError, ValueError, KeyError, StopIteration) as error:
        print(str(error) if isinstance(error, ModelError) else "No se pudo medir Ollama. Comprueba el servicio y el modelo local.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
