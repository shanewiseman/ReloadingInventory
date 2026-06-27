#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import requests


def sample_batch():
    return {
        "company": "Wiseman Precision Cartridges",
        "generated_at": "2026-06-27T12:00:00+00:00",
        "urls": {
            "batch": "http://reload-ledger.local/batches/sample-batch",
            "recipe": "http://reload-ledger.local/recipes/sample-recipe",
        },
        "batch": {
            "id": "sample-batch",
            "slug": "sample-batch",
            "recipe_id": "sample-recipe",
            "state": "UNDER PRODUCTION",
            "iterations": 50,
            "characteristics": "Printer service smoke test.",
            "notes": "Generated outside Reload Ledger.",
            "recipe": {
                "id": "sample-recipe",
                "title": ".357 Magnum 158 JHP Test",
                "overall_length": 1.59,
                "components": [
                    {"role": "BULLET", "quantity": 1, "unit": "count", "item": {"manufacturer": "Test", "name": "158 JHP"}},
                    {"role": "POWDER", "quantity": 10.5, "unit": "grains", "item": {"manufacturer": "Test", "name": "Powder"}},
                    {"role": "PRIMER", "quantity": 1, "unit": "count", "item": {"manufacturer": "Test", "name": "Primer"}},
                    {"role": "CASE", "quantity": 1, "unit": "count", "item": {"manufacturer": "Test", "name": "Case"}},
                ],
            },
            "reservations": [
                {"role": "BULLET", "item": "158 JHP", "lot": "B-LOT", "quantity": 50, "unit": "count", "status": "RESERVED"},
                {"role": "POWDER", "item": "Powder", "lot": "P-LOT", "quantity": 525, "unit": "grains", "status": "RESERVED"},
                {"role": "PRIMER", "item": "Primer", "lot": "PR-LOT", "quantity": 50, "unit": "count", "status": "RESERVED"},
                {"role": "CASE", "item": "Case", "lot": "C-LOT", "quantity": 50, "unit": "count", "status": "RESERVED"},
            ],
            "consumptions": [
                {"role": "BULLET", "item": "158 JHP", "lot_id": "B-LOT", "quantity": 50, "unit": "count"},
                {"role": "POWDER", "item": "Powder", "lot_id": "P-LOT", "quantity": 525, "unit": "grains"},
            ],
            "qa": {
                "required_sample_count": 7,
                "completed_sample_count": 7,
                "is_satisfied": True,
                "average_completed_weight": 252.4,
                "average_overall_length": 1.5905,
            },
            "performance": {
                "recorded_on": "2026-06-27",
                "firearm": "Test firearm",
                "distance": 25,
                "group_size": 2.1,
                "velocity_average": 1210,
                "velocity_minimum": 1198,
                "velocity_maximum": 1224,
                "standard_deviation": 8.4,
                "extreme_spread": 26,
                "subjective_rating": 4,
            },
            "material_cost_status": "calculated",
            "cost_per_cartridge": 0.55,
            "material_cost": 27.50,
            "material_cost_basis": "consumed",
        },
    }


def post_json(service_url, path, payload):
    response = requests.post(service_url.rstrip("/") + path, json=payload, timeout=15)
    print(f"HTTP {response.status_code}")
    print(response.text)
    return 0 if response.ok else 1


def image_payload(path):
    content = Path(path).read_bytes()
    return {
        "base64": base64.b64encode(content).decode("ascii"),
        "content_type": "image/png",
        "filename": Path(path).name,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send direct test jobs to the Reload Ledger POS print service.")
    parser.add_argument("--service-url", default="http://localhost:8088", help="Printer service base URL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("text", help="Print literal text.")
    text_parser.add_argument("text")

    image_parser = subparsers.add_parser("image", help="Print a PNG image.")
    image_parser.add_argument("path")
    image_parser.add_argument("--text", default="Image print test")

    sample_parser = subparsers.add_parser("sample", help="Print a sample batch event.")
    sample_parser.add_argument("event", choices=("batch-created", "batch-produced"))
    sample_parser.add_argument("--logo", help="Optional PNG logo to include in the sample payload.")

    args = parser.parse_args(argv)
    if args.command == "text":
        return post_json(args.service_url, "/print/test", {"text": args.text})
    if args.command == "image":
        return post_json(args.service_url, "/print/test", {"text": args.text, "image": image_payload(args.path)})
    payload = sample_batch()
    if args.logo:
        payload["logo"] = image_payload(args.logo)
    if args.event == "batch-created":
        return post_json(args.service_url, "/print/batch-created", payload)
    payload["batch"]["state"] = "PRODUCED"
    return post_json(args.service_url, "/print/batch-produced", payload)


if __name__ == "__main__":
    raise SystemExit(main())
