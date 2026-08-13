from harness.testing.retrieval_eval import run_retrieval_golden, score_retrieval_golden


def test_retrieval_golden_metrics_and_leakage_gate() -> None:
    metrics = score_retrieval_golden(
        [
            {
                "workspace_id": "demo",
                "expected_chunk_ids": ["CHUNK-1"],
                "expected_sources": ["sources/rules.md"],
                "results": [
                    {
                        "chunk_id": "CHUNK-1",
                        "source_identity": "sources/rules.md",
                        "workspace_id": "demo",
                        "freshness": "current",
                    }
                ],
            }
        ]
    )
    assert metrics.passed
    assert metrics.recall_at_10 == metrics.mrr == 1.0


def test_retrieval_golden_rejects_cross_workspace_and_superseded_results() -> None:
    metrics = score_retrieval_golden(
        [
            {
                "workspace_id": "demo",
                "expected_chunk_ids": ["CHUNK-1"],
                "expected_sources": ["sources/rules.md"],
                "results": [
                    {
                        "chunk_id": "CHUNK-1",
                        "source_identity": "sources/rules.md",
                        "workspace_id": "other",
                        "freshness": "superseded",
                    }
                ],
            }
        ]
    )
    assert not metrics.passed
    assert metrics.cross_workspace_leakage == 1
    assert metrics.superseded_leakage == 1


def test_repository_retrieval_golden_passes() -> None:
    result = run_retrieval_golden()
    assert result["passed"]
    assert result["recall_at_10"] >= 0.90
