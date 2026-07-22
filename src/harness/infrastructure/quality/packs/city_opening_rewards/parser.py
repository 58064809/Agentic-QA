from __future__ import annotations

from harness.application.source import SourceBundle


def source_corpus(bundle: SourceBundle) -> str:
    """Compatibility projection for the pack's pure rule parser."""
    return bundle.corpus
