"""Markdown Splitter — 基于章节/段落的分块策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    """一个文本块。"""
    text: str
    source: str  # 源文件路径
    heading: str = ""  # 所属章节标题
    chunk_index: int = 0  # 在该文件中的块序号


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def split_markdown_by_headings(
    text: str,
    source: str,
    *,
    min_chars: int = 50,
    max_chars: int = 500,
) -> list[Chunk]:
    """按 Markdown 标题切分，保持结构完整性。

    策略：
    - 用 H1/H2 标题作为主要切分点
    - 如果一个章节超过 max_chars，用 H3+ 子标题继续切分
    - 如果一个子章节仍超长，按段落切分
    """
    if not text.strip():
        return []

    # 找所有标题位置
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        # 没有标题 → 按段落/固定长度切
        return _split_paragraphs(text, source, max_chars=max_chars, min_chars=min_chars)

    chunks: list[Chunk] = []
    # 按 H1/H2 组织主章节
    main_sections = _group_by_main_headings(text, headings)

    for section_heading, section_level, section_text in main_sections:
        # 如果主章节不长，直接作为一个 chunk
        if len(section_text) <= max_chars:
            if len(section_text.strip()) >= min_chars:
                chunks.append(Chunk(
                    text=section_text.strip(),
                    source=source,
                    heading=section_heading,
                    chunk_index=len(chunks),
                ))
            continue

        # 超长 → 用子标题再分
        sub_chunks = _split_long_section(
            section_text, source, section_heading,
            section_level=section_level,
            max_chars=max_chars, min_chars=min_chars,
        )
        chunks.extend(sub_chunks)

    return chunks


def _group_by_main_headings(
    text: str, headings: list[re.Match],
) -> list[tuple[str, int, str]]:
    """按 H1/H2 标题分组。返回 [(标题, 级别, 章节文本)]。"""
    sections: list[tuple[str, int, int, str]] = []  # (heading, level, start_pos, text)
    last_heading = ""
    last_level = 1
    last_pos = -1  # -1 表示尚未遇到第一个标题

    for match in headings:
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        pos = match.start()

        if last_pos >= 0:
            section_text = text[last_pos:pos]
            sections.append((last_heading, last_level, section_text))

        if level <= 2:
            last_heading = heading_text
            last_level = level
            last_pos = pos
    # 忽略 H3+ 作为主分组

    # 最后一段
    if last_pos >= 0:
        section_text = text[last_pos:]
        sections.append((last_heading, last_level, section_text))
    elif headings:
        # 文档以标题开头
        sections.append((last_heading, last_level, text))

    return [(h, lvl, t) for h, lvl, t in sections if t.strip()]



def _split_long_section(
    text: str,
    source: str,
    parent_heading: str,
    *,
    section_level: int,
    max_chars: int,
    min_chars: int,
) -> list[Chunk]:
    """把超长章节按子标题或段落拆分。"""
    # 找当前章节内的子标题 (Level > 当前级别)
    sub_headings = list(HEADING_RE.finditer(text))
    if len(sub_headings) <= 1:
        # 没有子标题 → 按段落切
        return _split_paragraphs(text, source, max_chars=max_chars, min_chars=min_chars,
                                 parent_heading=parent_heading)

    chunks: list[Chunk] = []
    # 用所有 H2+ 级别的子标题切
    last_pos = 0
    current_sub = parent_heading

    for match in sub_headings:
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        pos = match.start()

        if level > section_level and last_pos > 0:
            section_text = text[last_pos:pos]
            if len(section_text.strip()) >= min_chars:
                chunks.append(Chunk(
                    text=section_text.strip(),
                    source=source,
                    heading=f"{parent_heading} > {current_sub}",
                    chunk_index=len(chunks),
                ))

        if level > section_level:
            current_sub = heading_text
            last_pos = pos

    # 最后一部分
    if last_pos > 0:
        section_text = text[last_pos:]
        if len(section_text.strip()) >= min_chars:
            chunks.append(Chunk(
                text=section_text.strip(),
                source=source,
                heading=f"{parent_heading} > {current_sub}",
                chunk_index=len(chunks),
            ))

    if not chunks:
        return _split_paragraphs(text, source, max_chars=max_chars, min_chars=min_chars,
                                 parent_heading=parent_heading)
    return chunks


def _split_paragraphs(
    text: str,
    source: str,
    *,
    max_chars: int,
    min_chars: int,
    parent_heading: str = "",
) -> list[Chunk]:
    """按段落或固定长度拆分无标题或超长文本。"""
    text = text.strip()
    if not text:
        return []

    # 尝试按空行切段落
    paragraphs = re.split(r"\n\s*\n", text)
    combined: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current and len(current) >= min_chars:
                combined.append(current)
            current = para

    if current and len(current) >= min_chars:
        combined.append(current)

    # 如果段落合并不理想，按固定窗口切
    if not combined:
        return _split_fixed_window(text, source, max_chars=max_chars, min_chars=min_chars,
                                   parent_heading=parent_heading)

    return [
        Chunk(
            text=para,
            source=source,
            heading=parent_heading,
            chunk_index=i,
        )
        for i, para in enumerate(combined)
    ]


def _split_fixed_window(
    text: str,
    source: str,
    *,
    max_chars: int,
    min_chars: int,
    parent_heading: str = "",
) -> list[Chunk]:
    """按固定字符窗口切分（最后 fallback）。"""
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk_text = text[start:end].strip()
        if len(chunk_text) >= min_chars:
            chunks.append(Chunk(
                text=chunk_text,
                source=source,
                heading=parent_heading,
                chunk_index=len(chunks),
            ))
        start = end
    return chunks


def chunk_markdown_files(
    files: dict[str, str],
    *,
    max_chars: int = 500,
    min_chars: int = 50,
) -> list[Chunk]:
    """将多个 Markdown 文件批量切分为 Chunk 列表。"""
    all_chunks: list[Chunk] = []
    for source, content in files.items():
        chunks = split_markdown_by_headings(
            content, source,
            min_chars=min_chars, max_chars=max_chars,
        )
        all_chunks.extend(chunks)
    return all_chunks
