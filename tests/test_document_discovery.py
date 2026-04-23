from pathlib import Path

from runtime.document_discovery import discover_requirement_context


def test_discover_requirement_docs_and_prototypes(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    design_dir = tmp_path / "prototype"
    docs_dir.mkdir()
    design_dir.mkdir()

    (docs_dir / "payment_prd.md").write_text(
        "# 支付 PRD\n\n- 用户提交订单后必须生成支付单\n- 支付失败后需要提示用户稍后重试\n",
        encoding="utf-8",
    )
    (docs_dir / "README.md").write_text("# Requirements\n\n说明文件，不应该当 PRD。", encoding="utf-8")
    (design_dir / "payment_flow.html").write_text("<html><body>payment flow</body></html>", encoding="utf-8")

    context = discover_requirement_context(tmp_path, "帮我分析支付需求，看看 PRD 和原型图")

    assert context["selected_requirement_docs"]
    assert context["selected_requirement_docs"][0]["path"].endswith("payment_prd.md")
    assert all(not doc["path"].endswith("README.md") for doc in context["selected_requirement_docs"])
    assert context["selected_prototypes"]
    assert context["selected_prototypes"][0]["path"].endswith("payment_flow.html")


def test_discover_requirement_package_and_output_root(tmp_path: Path) -> None:
    package = tmp_path / "requirements" / "deposit-management"
    docs_dir = package / "docs"
    design_dir = package / "prototype"
    docs_dir.mkdir(parents=True)
    design_dir.mkdir()

    (docs_dir / "deposit_prd.md").write_text(
        "# 保证金 PRD\n\n- 商家缴纳保证金后必须更新余额\n",
        encoding="utf-8",
    )
    (design_dir / "merchant-settlement-deposit.html").write_text("<html>deposit</html>", encoding="utf-8")

    context = discover_requirement_context(tmp_path, "帮我分析保证金需求")

    assert context["requirement_package"]["name"] == "deposit-management"
    assert context["requirement_package"]["matched_by"] == "single_package_default"
    assert context["output_root"] == str(package)
    doc_path = context["selected_requirement_docs"][0]["path"].replace("\\", "/")
    prototype_path = context["selected_prototypes"][0]["path"].replace("\\", "/")
    assert doc_path.endswith("requirements/deposit-management/docs/deposit_prd.md")
    assert prototype_path.endswith("requirements/deposit-management/prototype/merchant-settlement-deposit.html")
