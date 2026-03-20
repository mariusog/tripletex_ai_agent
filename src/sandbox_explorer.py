"""Sandbox exploration tool that discovers API field requirements.

Probes the Tripletex sandbox API to discover required/optional fields
for each competition-relevant endpoint. Outputs a structured manifest
that handlers use to build correct payloads on first try.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.api_client import TripletexApiError, TripletexClient

logger = logging.getLogger(__name__)

# Endpoints to explore with their expected list sub-paths
ENDPOINTS = [
    "/employee",
    "/customer",
    "/product",
    "/invoice",
    "/order",
    "/order/orderline",
    "/department",
    "/project",
    "/travelExpense",
    "/ledger/voucher",
    "/bank/reconciliation",
    "/activity",
    "/asset",
    "/ledger/account",
]


@dataclass
class FieldInfo:
    """Discovered metadata about a single API field."""

    name: str
    field_type: str = "unknown"
    required: bool = False
    validation_message: str = ""
    example_value: Any = None


@dataclass
class EndpointInfo:
    """Discovered metadata about an API endpoint."""

    endpoint: str
    get_fields: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    field_details: dict[str, FieldInfo] = field(default_factory=dict)
    validation_messages: list[dict[str, str]] = field(default_factory=list)
    get_error: str = ""
    post_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "endpoint": self.endpoint,
            "get_fields": self.get_fields,
            "required_fields": self.required_fields,
            "field_details": {
                k: {
                    "name": v.name,
                    "type": v.field_type,
                    "required": v.required,
                    "validation_message": v.validation_message,
                }
                for k, v in self.field_details.items()
            },
            "validation_messages": self.validation_messages,
            "get_error": self.get_error,
            "post_error": self.post_error,
        }


def _infer_type(value: Any) -> str:
    """Infer a field type string from a sample value."""
    if value is None:
        return "nullable"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        if len(value) == 10 and value.count("-") == 2:
            return "date"
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unknown"


class SandboxExplorer:
    """Discovers API field requirements by probing sandbox endpoints.

    For each endpoint, performs:
    1. GET with fields=* to discover available response fields and types
    2. POST with empty body to discover required fields via validation errors
    """

    def __init__(self, client: TripletexClient) -> None:
        self.client = client
        self.results: dict[str, EndpointInfo] = {}

    def explore_all(self) -> dict[str, EndpointInfo]:
        """Explore all configured endpoints and return results."""
        for endpoint in ENDPOINTS:
            logger.info("Exploring %s", endpoint)
            info = self._explore_endpoint(endpoint)
            self.results[endpoint] = info
        return self.results

    def _explore_endpoint(self, endpoint: str) -> EndpointInfo:
        """Explore a single endpoint with GET and POST probes."""
        info = EndpointInfo(endpoint=endpoint)
        self._probe_get(endpoint, info)
        self._probe_post(endpoint, info)
        return info

    def _probe_get(self, endpoint: str, info: EndpointInfo) -> None:
        """GET with fields=* to discover available fields and types."""
        try:
            response = self.client.get(endpoint, fields="*")
        except TripletexApiError as exc:
            info.get_error = str(exc)
            logger.warning("GET %s failed: %s", endpoint, exc)
            return

        entity = _extract_sample_entity(response)
        if entity is None:
            return

        for key, value in entity.items():
            info.get_fields.append(key)
            field_type = _infer_type(value)
            if key not in info.field_details:
                info.field_details[key] = FieldInfo(name=key)
            info.field_details[key].field_type = field_type
            info.field_details[key].example_value = value

    def _probe_post(self, endpoint: str, info: EndpointInfo) -> None:
        """POST empty body to discover required fields from validation."""
        try:
            self.client.post(endpoint, data={})
            # Unexpected success with empty body
            logger.info("POST %s succeeded with empty body", endpoint)
        except TripletexApiError as exc:
            error = exc.error
            info.post_error = error.message
            info.validation_messages = error.validation_messages
            for msg in error.validation_messages:
                field_name = msg.get("field", "")
                message_text = msg.get("message", "")
                if field_name:
                    info.required_fields.append(field_name)
                    if field_name not in info.field_details:
                        info.field_details[field_name] = FieldInfo(name=field_name)
                    info.field_details[field_name].required = True
                    info.field_details[field_name].validation_message = message_text
            logger.info(
                "POST %s revealed %d required fields",
                endpoint,
                len(info.required_fields),
            )


def _extract_sample_entity(response: Any) -> dict[str, Any] | None:
    """Extract a sample entity from a GET response."""
    if not isinstance(response, dict):
        return None
    # List response
    values = response.get("values")
    if isinstance(values, list) and len(values) > 0:
        entity = values[0]
        if isinstance(entity, dict):
            return entity
    # Single response
    value = response.get("value")
    if isinstance(value, dict) and value:
        return value
    return None


def generate_manifest_json(results: dict[str, EndpointInfo]) -> str:
    """Generate JSON manifest from exploration results."""
    manifest = {endpoint: info.to_dict() for endpoint, info in results.items()}
    return json.dumps(manifest, indent=2, default=str)


def generate_manifest_md(results: dict[str, EndpointInfo]) -> str:
    """Generate markdown summary with one table per endpoint."""
    lines: list[str] = ["# Tripletex API Field Manifest", ""]
    lines.append("Auto-generated by sandbox explorer. Shows required/optional fields per endpoint.")
    lines.append("")

    for endpoint, info in results.items():
        lines.append(f"## `{endpoint}`")
        lines.append("")

        if info.get_error:
            lines.append(f"**GET error:** {info.get_error}")
            lines.append("")

        if info.required_fields:
            lines.append(f"**Required fields:** {', '.join(info.required_fields)}")
            lines.append("")

        if info.field_details:
            lines.append("| Field | Type | Required | Validation |")
            lines.append("|-------|------|----------|------------|")
            for name, detail in sorted(info.field_details.items()):
                req = "yes" if detail.required else ""
                val_msg = detail.validation_message or ""
                lines.append(f"| {name} | {detail.field_type} | {req} | {val_msg} |")
            lines.append("")
        elif not info.get_error:
            lines.append("_No fields discovered._")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point for standalone sandbox exploration."""
    parser = argparse.ArgumentParser(
        description="Explore Tripletex sandbox API to discover field requirements"
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Tripletex API base URL (e.g. https://proxy.tripletex.dev/v2)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Session token for Tripletex API authentication",
    )
    parser.add_argument(
        "--output-dir",
        default="docs",
        help="Directory for output files (default: docs)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    client = TripletexClient(args.base_url, args.token)
    try:
        explorer = SandboxExplorer(client)
        results = explorer.explore_all()

        json_path = f"{args.output_dir}/field_manifest.json"
        md_path = f"{args.output_dir}/field_manifest.md"

        json_content = generate_manifest_json(results)
        with open(json_path, "w") as f:
            f.write(json_content)
        logger.info("Wrote %s", json_path)

        md_content = generate_manifest_md(results)
        with open(md_path, "w") as f:
            f.write(md_content)
        logger.info("Wrote %s", md_path)

        # Print summary
        total_fields = sum(len(i.get_fields) for i in results.values())
        total_required = sum(len(i.required_fields) for i in results.values())
        print(
            f"Explored {len(results)} endpoints: "
            f"{total_fields} fields discovered, "
            f"{total_required} required fields identified"
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
