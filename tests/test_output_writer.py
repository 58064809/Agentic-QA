from pathlib import Path

from runtime.output_writer import save_assistant_output


def test_save_assistant_output_writes_markdown(tmp_path: Path) -> None:
    result = save_assistant_output(
        tmp_path,
        "requirement_analysis",
        "# 需求分析结论\n\n内容",
        {"task": "requirement_analysis"},
    )

    saved_file = Path(result["files"][0]["path"])
    assert saved_file.exists()
    assert saved_file.parent == tmp_path / "outputs"
    assert saved_file.name.endswith("_requirement_analysis.md")
    assert saved_file.read_text(encoding="utf-8").startswith("# 需求分析结论")


def test_save_script_generation_writes_markdown_and_python(tmp_path: Path) -> None:
    result = save_assistant_output(
        tmp_path,
        "script_generation",
        "# pytest 脚本草稿",
        {
            "recommended_file_name": "test_generated_from_requirement.py",
            "script_content": "def test_demo():\n    assert True\n",
        },
    )

    paths = [Path(item["path"]) for item in result["files"]]
    assert len(paths) == 2
    assert any(path.suffix == ".md" for path in paths)
    script_path = next(path for path in paths if path.suffix == ".py")
    assert script_path.name == "test_generated_from_requirement.py"
    assert "def test_demo" in script_path.read_text(encoding="utf-8")
