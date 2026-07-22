from __future__ import annotations

import re

from harness.application.quality import (
    NormalizationOperation,
    NormalizationOperationKind,
    NormalizationProposal,
    QualityComponentConfiguration,
    QualityContext,
)

TABLE_DELIMITER = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


class SafeMarkdownNormalizer:
    name = "safe-markdown-representation"
    version = "1.0.0"
    configuration = QualityComponentConfiguration()

    def propose(self, context: QualityContext, content: str) -> NormalizationProposal:
        del context, content
        return NormalizationProposal(
            operations=tuple(
                NormalizationOperation(kind=kind)
                for kind in (
                    NormalizationOperationKind.NORMALIZE_LINE_ENDINGS,
                    NormalizationOperationKind.TRIM_TRAILING_WHITESPACE,
                    NormalizationOperationKind.ENSURE_FINAL_NEWLINE,
                    NormalizationOperationKind.NORMALIZE_MARKDOWN_TABLE_DELIMITER_SPACING,
                )
            )
        )


def apply_safe_normalization(content: str, proposal: NormalizationProposal) -> str:
    result = content
    for operation in proposal.operations:
        if operation.kind == NormalizationOperationKind.NORMALIZE_LINE_ENDINGS:
            result = result.replace("\r\n", "\n").replace("\r", "\n")
        elif operation.kind == NormalizationOperationKind.TRIM_TRAILING_WHITESPACE:
            result = "\n".join(line.rstrip() for line in result.split("\n"))
        elif operation.kind == NormalizationOperationKind.ENSURE_FINAL_NEWLINE:
            result = result.rstrip("\n") + "\n"
        elif operation.kind == (
            NormalizationOperationKind.NORMALIZE_MARKDOWN_TABLE_DELIMITER_SPACING
        ):
            lines = []
            for line in result.split("\n"):
                if TABLE_DELIMITER.fullmatch(line):
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    line = "| " + " | ".join(cells) + " |"
                lines.append(line)
            result = "\n".join(lines)
        else:  # pragma: no cover - Pydantic enum prevents this branch
            raise ValueError(f"unsupported normalization operation: {operation.kind}")
    if _semantic_projection(content) != _semantic_projection(result):
        raise ValueError("normalization changed semantic content")
    return result


def _semantic_projection(content: str) -> tuple[tuple[str, ...], ...]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    projection: list[tuple[str, ...]] = []
    for line in normalized.split("\n"):
        stripped = line.rstrip()
        if not stripped:
            continue
        if TABLE_DELIMITER.fullmatch(stripped):
            cells = stripped.strip().strip("|").split("|")
            projection.append(tuple(cell.strip() for cell in cells))
        else:
            projection.append((stripped,))
    return tuple(projection)
