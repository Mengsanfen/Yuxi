from pathlib import Path

from yuxi.services.enterprise_service import AUTO_REFUND_LIMIT, REFUND_WINDOW_DAYS
from yuxi.services.enterprise_seed_service import PRODUCT_SEED


def test_demo_policy_matches_deterministic_refund_rules():
    policy_file = Path(__file__).resolve().parents[3] / "eval/enterprise/fixtures/dreamos_refund_policy.md"
    content = policy_file.read_text(encoding="utf-8")

    assert "演示资料" in content
    assert f"{REFUND_WINDOW_DAYS} 天" in content
    assert f"{int(AUTO_REFUND_LIMIT)} 元" in content
    assert "退款金额必须等于订单实付金额" in content
    assert "部分退款和超额退款均不支持" in content
    assert "待支付和已取消订单不可退款" in content
    assert "不承诺退款到账时效" in content


def test_demo_knowledge_documents_cover_products_and_after_sale_topics():
    fixtures = Path(__file__).resolve().parents[3] / "eval/enterprise/fixtures"
    catalog = (fixtures / "dreamos_product_catalog.md").read_text(encoding="utf-8")
    guide = (fixtures / "dreamos_after_sale_guide.md").read_text(encoding="utf-8")

    for sku, name, *_ in PRODUCT_SEED:
        assert f"{name}（{sku}）" in catalog
    for fact in ("USB-C 有线", "签收次日起 12 个月", "支持双显示器输出", "通透模式"):
        assert fact in catalog
    for section in ("换货政策", "物流说明", "质保规则", "售后 FAQ"):
        assert f"## {section}" in guide
    assert "Flow 无线鼠标" in guide and "其他商品未设定质保期限" in guide
