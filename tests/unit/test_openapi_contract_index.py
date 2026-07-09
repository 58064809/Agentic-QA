from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.nodes.api_test_generation import (  # noqa: E402
    _api_cases_yaml_errors,
    render_api_test_cases_yaml,
)
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.tools.openapi_contract_index import (  # noqa: E402
    build_openapi_operation_chunks,
    retrieve_openapi_chunks_for_prd,
)


def product_openapi_payload() -> dict:
    return {
        "openapi": "3.0.1",
        "info": {"title": "Product Service API", "version": "1.0.0"},
        "paths": {
            "/product/shop/store/getCommodityDetail": {
                "get": {
                    "summary": "查询商品详情",
                    "tags": ["shop"],
                    "security": [{"apikey-header-accesstoken": []}],
                    "parameters": [
                        {
                            "name": "commodityId",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "shopId",
                            "in": "header",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/CommodityResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/product/mobile/inventory/list": {
                "post": {
                    "summary": "库存列表查询",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/InventoryQuery"}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PageResponse"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "InventoryQuery": {
                    "type": "object",
                    "required": ["warehouseId"],
                    "properties": {
                        "warehouseId": {"type": "integer", "description": "仓库 ID"},
                        "keyword": {"type": "string", "description": "关键词"},
                    },
                },
                "CommodityResponse": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "integer"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/Commodity"},
                    },
                },
                "Commodity": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                },
                "PageResponse": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "integer"},
                        "data": {"type": "object"},
                    },
                },
            }
        },
    }


def write_product_openapi(repo_root: Path) -> None:
    target = repo_root / "knowledge/api/product/openapi.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(product_openapi_payload(), ensure_ascii=False), encoding="utf-8")


def write_prd(repo_root: Path, api_scope: str) -> None:
    input_dir = repo_root / "prd/demo-requirement/input"
    input_dir.mkdir(parents=True)
    (input_dir / "requirement.md").write_text("需要查询商品详情和库存列表。", encoding="utf-8")
    (input_dir / "api-scope.md").write_text(api_scope, encoding="utf-8")


def test_product_openapi_api_scope_path_retrieves_operation(tmp_path):
    write_product_openapi(tmp_path)
    write_prd(
        tmp_path,
        "service: product\npaths:\n- GET /product/shop/store/getCommodityDetail\n",
    )

    chunks, warnings = retrieve_openapi_chunks_for_prd(tmp_path, "prd/demo-requirement")

    assert warnings == []
    assert len(chunks) == 1
    assert chunks[0].chunk_id.startswith("openapi.product.GET.")
    assert chunks[0].path == "/product/shop/store/getCommodityDetail"
    assert chunks[0].source_path == "knowledge/api/product/openapi.json"


def test_openapi_index_resolves_request_body_ref():
    chunks = build_openapi_operation_chunks(
        product_openapi_payload(),
        service="product",
        source_path="knowledge/api/product/openapi.json",
    )
    chunk = next(item for item in chunks if item.path == "/product/mobile/inventory/list")

    assert chunk.request_schema["properties"]["warehouseId"]["type"] == "integer"
    assert chunk.request_schema["required"] == ["warehouseId"]


def test_openapi_index_resolves_response_ref():
    chunks = build_openapi_operation_chunks(
        product_openapi_payload(),
        service="product",
        source_path="knowledge/api/product/openapi.json",
    )
    chunk = next(item for item in chunks if item.path == "/product/shop/store/getCommodityDetail")

    assert chunk.response_schema["properties"]["data"]["properties"]["id"]["type"] == "integer"
    assert chunk.response_status_codes == ["200"]


def test_openapi_index_uses_path_prefix_domain_when_tags_empty():
    chunks = build_openapi_operation_chunks(
        product_openapi_payload(),
        service="product",
        source_path="knowledge/api/product/openapi.json",
    )
    chunk = next(item for item in chunks if item.path == "/product/mobile/inventory/list")

    assert chunk.tags == ["inventory"]


def test_api_scope_missing_path_does_not_invent_interface(tmp_path):
    write_product_openapi(tmp_path)
    write_prd(
        tmp_path,
        "service: product\npaths:\n- GET /product/missing/notInApifox\n",
    )
    state = QAWorkflowState(
        prd_path="prd/demo-requirement",
        task_type="api_test_draft",
        run_id="run-openapi-missing",
        loaded_files={
            "prd/demo-requirement/input/requirement.md": "需要查询商品详情。",
            "prd/demo-requirement/input/api-scope.md": (
                "service: product\npaths:\n- GET /product/missing/notInApifox\n"
            ),
        },
    )

    payload = yaml.safe_load(render_api_test_cases_yaml(state, tmp_path))
    content = yaml.safe_dump(payload, allow_unicode=True)
    case = payload["cases"][0]

    assert "method: GET" not in content
    assert case["contract_status"] == "missing"
    assert "method" not in case
    assert "path" not in case
    assert case["request"] == {}
    assert any("未在服务级 OpenAPI 中命中" in item for item in case["review_questions"])
    assert _api_cases_yaml_errors(yaml.safe_dump(payload, allow_unicode=True)) == []


def test_api_scope_openapi_hit_generates_confirmed_yaml(tmp_path):
    write_product_openapi(tmp_path)
    write_prd(
        tmp_path,
        "service: product\npaths:\n- GET /product/shop/store/getCommodityDetail\n",
    )
    state = QAWorkflowState(
        prd_path="prd/demo-requirement",
        task_type="api_test_draft",
        run_id="run-openapi-hit",
        loaded_files={
            "prd/demo-requirement/input/requirement.md": "需要查询商品详情。",
            "prd/demo-requirement/input/api-scope.md": (
                "service: product\npaths:\n- GET /product/shop/store/getCommodityDetail\n"
            ),
        },
    )

    payload = yaml.safe_load(render_api_test_cases_yaml(state, tmp_path))
    case = payload["cases"][0]

    assert case["contract_status"] == "confirmed"
    assert case["method"] == "GET"
    assert case["path"] == "/product/shop/store/getCommodityDetail"
    assert case["source_refs"][0]["source_type"] == "openapi"
    assert case["source_refs"][0]["source_path"] == "knowledge/api/product/openapi.json"
    assert case["source_refs"][0]["confidence"] == "high"
    assert case["request"]["query"][0]["name"] == "commodityId"
    assert case["expected"]["status_code"] == [200]
    assert "json_contains_keys" in case["expected"]
    assert _api_cases_yaml_errors(yaml.safe_dump(payload, allow_unicode=True)) == []
