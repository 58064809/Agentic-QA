from actions.requirement_parser import extract_requirement_items
from actions.requirement_parser import extract_requirement_items_from_text


def test_extract_requirement_items_skips_metadata_and_keeps_rules() -> None:
    text = """
# 保证金管理系统产品需求文档（PRD）

## 文档信息

| 项目 | 内容 |
|------|------|
| 文档名称 | 保证金管理系统产品需求文档 |
| 文档版本 | V2.4 |

## 功能模块设计

#### 4.1.1 缴纳保证金

- 商家缴纳或补缴保证金，仅支持网银转账方式。
- 若保证金未缴纳，提现功能受限，点击提现时提示去缴纳。
- 应缴总金额按照基础保证金和风险保证金两者金额就高原则计算。
- 是否支持第三方支付？
"""

    items = extract_requirement_items_from_text(text)

    assert "文档名称" not in items
    assert "文档版本" not in items
    assert "商家缴纳或补缴保证金，仅支持网银转账方式" in items
    assert "若保证金未缴纳，提现功能受限，点击提现时提示去缴纳" in items
    assert "应缴总金额按照基础保证金和风险保证金两者金额就高原则计算" in items
    assert "是否支持第三方支付" in items


def test_extract_requirement_items_focuses_matched_section() -> None:
    context = {
        "selected_requirement_docs": [
            {
                "path": "docs/deposit.md",
                "content": """
# 保证金 PRD

#### 4.1.0 账户管理
- 账户余额：展示待结算金额、冻结金额、可提现余额。

#### 4.1.1 缴纳保证金
- 商家缴纳或补缴保证金，仅支持网银转账方式。
- 缴存金额：必填，最小金额¥1.00，不能超过应缴金额的2倍。

#### 4.1.2 违规管理
- 待审核罚单支持申诉。
""",
            }
        ],
        "selected_prototypes": [],
    }

    items = extract_requirement_items("帮我分析缴纳保证金需求", context)

    assert "商家缴纳或补缴保证金，仅支持网银转账方式" in items
    assert "缴存金额：必填，最小金额¥1.00，不能超过应缴金额的2倍" in items
    assert all("账户余额" not in item for item in items)
    assert all("罚单" not in item for item in items)


def test_extract_requirement_items_cleans_markdown_bold_labels() -> None:
    items = extract_requirement_items_from_text("**功能描述：** 商家缴纳或补缴保证金，仅支持网银转账方式。")

    assert items == ["商家缴纳或补缴保证金，仅支持网银转账方式"]
