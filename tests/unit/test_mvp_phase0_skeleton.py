from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mvp_phase0_directories_exist():
    for relative_path in [
        "apps/cli",
        "rag/loaders",
        "rag/splitter",
        "rag/retriever",
        "rag/embedding",
        "rag/vector_store",
        "configs",
    ]:
        assert (REPO_ROOT / relative_path).is_dir(), relative_path


def test_mvp_phase0_example_configs_exist():
    for relative_path in [
        "configs/config.example.yaml",
        "configs/model.example.yaml",
        ".env.example",
    ]:
        assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_runtime_entry_wrappers_are_importable():
    import apps.cli.main

    assert callable(apps.cli.main.main)
