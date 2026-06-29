from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from runtime.tools.api_doc_loader import (
    import_api_document_to_workspace,
    load_api_document,
    normalize_workspace_api_docs,
)


def sample_openapi() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Demo API", "version": "1"},
        "paths": {
            "/api/demo": {
                "post": {
                    "summary": "创建 Demo",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}, "400": {"description": "bad"}},
                }
            }
        },
    }


def make_workspace(root: Path) -> Path:
    workspace = root / "prd/demo"
    (workspace / "input").mkdir(parents=True)
    (workspace / "metadata.yml").write_text("requirement_id: demo\n", encoding="utf-8")
    return workspace


def test_openapi_json_file_loads(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(sample_openapi()), encoding="utf-8")

    result = load_api_document(path)

    assert result.document.endpoints[0].path == "/api/demo"
    assert "## POST /api/demo" in result.markdown


def test_openapi_yaml_file_loads(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text(yaml.safe_dump(sample_openapi(), allow_unicode=True), encoding="utf-8")

    result = load_api_document(path)

    assert result.document.spec_type == "openapi-3.0.3"
    assert "name" in result.markdown


def test_invalid_json_reports_parse_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ValueError, match="无法解析"):
        load_api_document(path)


def test_external_openapi_import_copies_source_and_writes_api_markdown(tmp_path):
    repo_root = tmp_path
    make_workspace(repo_root)
    external = tmp_path / "activity-openapi.json"
    external.write_text(json.dumps(sample_openapi()), encoding="utf-8")

    result = import_api_document_to_workspace(repo_root, "prd/demo", external)

    assert result.copied_path == repo_root / "prd/demo/input/api.openapi.json"
    assert result.copied_path.is_file()
    assert (repo_root / "prd/demo/input/api.md").is_file()
    assert "## POST /api/demo" in (repo_root / "prd/demo/input/api.md").read_text(encoding="utf-8")


def test_workspace_openapi_file_normalizes_to_api_markdown(tmp_path):
    repo_root = tmp_path
    workspace = make_workspace(repo_root)
    source = workspace / "input/api.apifox.json"
    source.write_text(json.dumps(sample_openapi()), encoding="utf-8")

    result = normalize_workspace_api_docs(repo_root, "prd/demo")

    assert result is not None
    assert result.markdown_path == workspace / "input/api.md"
    assert "## POST /api/demo" in result.markdown_path.read_text(encoding="utf-8")
