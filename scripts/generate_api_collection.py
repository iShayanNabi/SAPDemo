"""Generate a Postman collection and an OpenAPI snapshot from the live app.

Run with::

    python scripts/generate_api_collection.py

Writes two files into ``docs/``:

``docs/openapi.json``
    A snapshot of the generated OpenAPI document. Useful for generating a
    TypeScript client without starting the server, and it makes an API change
    visible as a diff in code review rather than as a surprise in a front end.

``docs/postman_collection.json``
    A Postman v2.1 collection with one folder per module, every endpoint, its
    path and query parameters, and a request body pre-filled from the schema's
    own example where one exists.

The collection is *generated*, never hand-maintained. A hand-written one drifts
from the API within a week, and the version somebody imports is always the stale
one. Regenerate it whenever a route changes; the tests check that it is current.

Both files import into Postman, Insomnia, Bruno, Hoppscotch or anything else
that reads the two formats.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "docs"
OPENAPI_PATH = OUTPUT_DIR / "openapi.json"
COLLECTION_PATH = OUTPUT_DIR / "postman_collection.json"

#: Postman variables, so a reader can point the whole collection somewhere else
#: (a container, a colleague's machine) by editing one field.
COLLECTION_VARIABLES = [
    {"key": "baseUrl", "value": "http://127.0.0.1:8000", "type": "string"},
    {
        "key": "authToken",
        "value": "",
        "type": "string",
        "description": (
            "Unused today - no endpoint requires a credential. Present so the "
            "Authorization header is already wired when authentication is added."
        ),
    },
]


def _example_body(operation: dict[str, Any], schemas: dict[str, Any]) -> str | None:
    """Return a JSON body to pre-fill, taken from the schema's own example."""
    content = (operation.get("requestBody") or {}).get("content", {})
    json_body = content.get("application/json")
    if not json_body:
        return None

    schema = json_body.get("schema", {})
    reference = schema.get("$ref", "")
    resolved = schemas.get(reference.split("/")[-1], {}) if reference else schema

    examples = resolved.get("examples") or schema.get("examples")
    if examples:
        return json.dumps(examples[0], indent=2)

    # No example declared: build a skeleton from the required fields so the
    # request is at least the right shape to edit.
    required = resolved.get("required") or []
    if not required:
        return "{}"
    properties = resolved.get("properties", {})
    skeleton = {name: _placeholder(properties.get(name, {})) for name in required}
    return json.dumps(skeleton, indent=2)


def _placeholder(field: dict[str, Any]) -> Any:
    """A stand-in value of roughly the right type."""
    kind = field.get("type")
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return "<replace me>"


def _multipart_body(operation: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the form fields for an upload endpoint."""
    content = (operation.get("requestBody") or {}).get("content", {})
    form = content.get("multipart/form-data")
    if not form:
        return None
    properties = form.get("schema", {}).get("properties", {})
    fields: list[dict[str, Any]] = []
    for name, field in properties.items():
        if field.get("format") == "binary":
            fields.append({"key": name, "type": "file", "src": [], "description": "Pick a file"})
        else:
            fields.append(
                {
                    "key": name,
                    "type": "text",
                    "value": str(field.get("default", "")),
                    "description": field.get("description", ""),
                }
            )
    return fields


def _request(path: str, method: str, operation: dict[str, Any], schemas: dict[str, Any]) -> dict:
    """Build one Postman request item."""
    query = []
    variables = []
    for parameter in operation.get("parameters", []):
        schema = parameter.get("schema", {})
        entry = {
            "key": parameter["name"],
            "value": str(schema.get("default", "")),
            "description": parameter.get("description", ""),
            "disabled": not parameter.get("required", False)
            and schema.get("default") is None,
        }
        if parameter.get("in") == "query":
            query.append(entry)
        elif parameter.get("in") == "path":
            variables.append({"key": parameter["name"], "value": f"<{parameter['name']}>"})

    body: dict[str, Any] | None = None
    form_fields = _multipart_body(operation)
    if form_fields is not None:
        body = {"mode": "formdata", "formdata": form_fields}
    else:
        raw = _example_body(operation, schemas)
        if raw is not None:
            body = {
                "mode": "raw",
                "raw": raw,
                "options": {"raw": {"language": "json"}},
            }

    # Postman path segments: /api/v1/po-risk/analyses/{analysis_id} ->
    # ["api", "v1", "po-risk", "analyses", ":analysis_id"]
    segments = [
        f":{segment[1:-1]}" if segment.startswith("{") else segment
        for segment in path.strip("/").split("/")
        if segment
    ]

    request: dict[str, Any] = {
        "method": method.upper(),
        "header": [
            {
                "key": "Authorization",
                "value": "Bearer {{authToken}}",
                "disabled": True,
                "description": "Not required today. See docs/API_AUTHENTICATION_PLAN.md.",
            }
        ],
        "url": {
            "raw": "{{baseUrl}}" + path,
            "host": ["{{baseUrl}}"],
            "path": segments,
            "query": query,
            "variable": variables,
        },
        "description": operation.get("description") or operation.get("summary", ""),
    }
    if body is not None:
        request["body"] = body
        if body["mode"] == "raw":
            request["header"].append({"key": "Content-Type", "value": "application/json"})

    return {
        "name": operation.get("summary") or f"{method.upper()} {path}",
        "request": request,
        "response": [],
    }


def build_collection(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn an OpenAPI document into a Postman v2.1 collection."""
    schemas = spec.get("components", {}).get("schemas", {})
    tag_order = [tag["name"] for tag in spec.get("tags", [])]
    tag_descriptions = {tag["name"]: tag.get("description", "") for tag in spec.get("tags", [])}

    folders: dict[str, list[dict[str, Any]]] = {name: [] for name in tag_order}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            tag = (operation.get("tags") or ["Other"])[0]
            folders.setdefault(tag, []).append(_request(path, method, operation, schemas))

    items = [
        {
            "name": name,
            "description": tag_descriptions.get(name, ""),
            "item": requests,
        }
        for name, requests in folders.items()
        if requests
    ]

    return {
        "info": {
            "name": f"{spec['info']['title']} (v{spec['info']['version']})",
            "description": (
                "Generated by scripts/generate_api_collection.py - do not edit by hand.\n\n"
                "Set the `baseUrl` variable to point at your API (default "
                "http://127.0.0.1:8000). Every response uses the shared envelope "
                "{success, data, error, meta}; downloads return the file itself.\n\n"
                "Demo application: not connected to any SAP system, and no output has been "
                "validated in a live SAP environment."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": COLLECTION_VARIABLES,
        "item": items,
    }


def main() -> int:
    """Write the OpenAPI snapshot and the Postman collection."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed files are out of date.",
    )
    args = parser.parse_args()

    from app.main import app

    spec = app.openapi()
    collection = build_collection(spec)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payloads = {
        OPENAPI_PATH: json.dumps(spec, indent=2, sort_keys=True) + "\n",
        COLLECTION_PATH: json.dumps(collection, indent=2) + "\n",
    }

    if args.check:
        stale = [
            path.name
            for path, payload in payloads.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != payload
        ]
        if stale:
            print(f"Out of date: {', '.join(stale)}")
            print("Run: python scripts/generate_api_collection.py")
            return 1
        print("The committed OpenAPI snapshot and Postman collection are current.")
        return 0

    for path, payload in payloads.items():
        path.write_text(payload, encoding="utf-8")

    endpoints = sum(
        1
        for operations in spec["paths"].values()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    )
    print(f"Wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {COLLECTION_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  {endpoints} endpoints across {len(collection['item'])} module folders.")
    print("\nImport the collection into Postman/Insomnia/Bruno, or generate a client:")
    print("  npx openapi-typescript docs/openapi.json -o examples/typescript-client/src/schema.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
