"""测试 chat_service 中的 interrupt 相关函数"""

import sys
import os

sys.path.insert(0, os.getcwd())

from yuxi.services.chat_service import (
    _build_runtime_identity_context,
    _normalize_interrupt_options,
    _normalize_interrupt_questions,
    _build_ask_user_question_payload,
    _coerce_interrupt_payload,
)
from yuxi.storage.postgres.models_business import User


class TestNormalizeInterruptOptions:
    """测试 _normalize_interrupt_options 函数"""

    def test_empty_input(self):
        assert _normalize_interrupt_options(None) == []
        assert _normalize_interrupt_options([]) == []

    def test_dict_options(self):
        raw = [
            {"label": "选项1", "value": "option1"},
            {"label": "选项2", "value": "option2"},
        ]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 2
        assert result[0] == {"label": "选项1", "value": "option1"}
        assert result[1] == {"label": "选项2", "value": "option2"}

    def test_string_options(self):
        raw = ["选项1", "选项2", "选项3"]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 3
        assert result[0] == {"label": "选项1", "value": "选项1"}

    def test_mixed_options(self):
        raw = [{"label": "选项1", "value": "option1"}, "选项2"]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 2
        assert result[0] == {"label": "选项1", "value": "option1"}
        assert result[1] == {"label": "选项2", "value": "选项2"}

    def test_invalid_options(self):
        raw = [{"label": "只有label"}, {}, "  "]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 1  # 只有有效的选项
        assert result[0] == {"label": "只有label", "value": "只有label"}

    def test_value_only(self):
        raw = [{"value": "only_value"}]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 1
        assert result[0] == {"label": "only_value", "value": "only_value"}


class TestBuildAskUserQuestionPayload:
    """测试 _build_ask_user_question_payload 函数"""

    def test_basic_questions(self):
        info = {
            "questions": [
                {
                    "question": "请确认是否继续？",
                    "options": [
                        {"label": "确认", "value": "yes"},
                        {"label": "取消", "value": "no"},
                    ],
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-123")

        assert len(result["questions"]) == 1
        assert result["questions"][0]["question"] == "请确认是否继续？"
        assert len(result["questions"][0]["options"]) == 2
        assert result["questions"][0]["options"][0] == {"label": "确认", "value": "yes"}
        assert result["questions"][0]["options"][1] == {"label": "取消", "value": "no"}
        assert result["source"] == "interrupt"
        assert result["thread_id"] == "thread-123"

    def test_questions_with_source(self):
        info = {
            "questions": [{"question": "选择一个选项", "options": ["A", "B", "C"]}],
            "source": "ask_user_question",
        }
        result = _build_ask_user_question_payload(info, "thread-456")

        assert result["source"] == "ask_user_question"
        assert len(result["questions"][0]["options"]) == 3

    def test_multi_select(self):
        info = {
            "questions": [
                {
                    "question": "选择多个",
                    "options": ["A", "B", "C"],
                    "multi_select": True,
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-789")

        assert result["questions"][0]["multi_select"] is True

    def test_disable_allow_other(self):
        info = {
            "questions": [{"question": "只能选择", "options": ["A", "B"], "allow_other": False}],
        }
        result = _build_ask_user_question_payload(info, "thread-000")

        assert result["questions"][0]["allow_other"] is False

    def test_with_operation(self):
        info = {
            "questions": [
                {
                    "question": "是否执行操作？",
                    "operation": "删除文件",
                    "options": [
                        {"label": "批准", "value": "approve"},
                        {"label": "拒绝", "value": "reject"},
                    ],
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-op")

        assert result["questions"][0]["operation"] == "删除文件"

    def test_default_question_when_questions_missing(self):
        info = {}
        result = _build_ask_user_question_payload(info, "thread-no-opt")

        assert len(result["questions"]) == 1
        assert result["questions"][0]["question"] == "请选择一个选项"
        assert result["questions"][0]["options"] == []
        assert result["source"] == "interrupt"

    def test_legacy_single_question_payload(self):
        info = {
            "question": "旧协议问题",
            "question_id": "legacy-qid",
            "options": ["A", "B"],
            "multi_select": True,
            "allow_other": False,
            "operation": "旧操作",
        }
        result = _build_ask_user_question_payload(info, "thread-legacy")

        assert len(result["questions"]) == 1
        assert result["questions"][0]["question"] == "旧协议问题"
        assert result["questions"][0]["question_id"] == "legacy-qid"
        assert result["questions"][0]["options"] == [
            {"label": "A", "value": "A"},
            {"label": "B", "value": "B"},
        ]
        assert result["questions"][0]["multi_select"] is True
        assert result["questions"][0]["allow_other"] is False
        assert result["questions"][0]["operation"] == "旧操作"

    def test_question_id_generation(self):
        """测试 question_id 自动生成"""
        info = {"questions": [{"question": "测试？"}]}
        result = _build_ask_user_question_payload(info, "thread-id")

        assert result["questions"][0]["question_id"] != ""
        assert len(result["questions"][0]["question_id"]) > 0

    def test_enterprise_approval_metadata_is_preserved(self):
        info = {
            "source": "enterprise_refund_approval",
            "approval_task_id": 12,
            "business_type": "refund",
            "business_id": 15,
            "risk_level": "high",
            "amount": "299.00",
            "questions": [{"question": "等待管理员审批", "allow_other": False}],
        }

        result = _build_ask_user_question_payload(info, "thread-approval")

        assert result["source"] == "enterprise_refund_approval"
        assert result["approval_task_id"] == 12
        assert result["business_id"] == 15
        assert result["risk_level"] == "high"
        assert result["amount"] == "299.00"


def test_runtime_identity_context_contains_tenant_role_and_agent_config():
    current_user = User(id=8, department_id=3, role="admin", user_id="admin-user")

    result = _build_runtime_identity_context(
        current_user=current_user,
        agent_id="EnterpriseServiceAgent",
        agent_config_id=21,
        thread_id="thread-runtime",
    )

    assert result == {
        "user_id": "8",
        "account_user_id": "admin-user",
        "tenant_id": 3,
        "user_role": "admin",
        "agent_id": "EnterpriseServiceAgent",
        "agent_config_id": 21,
        "thread_id": "thread-runtime",
    }


class TestNormalizeInterruptQuestions:
    """测试 _normalize_interrupt_questions 函数"""

    def test_empty_input(self):
        assert _normalize_interrupt_questions(None) == []
        assert _normalize_interrupt_questions([]) == []

    def test_normalize_basic_question(self):
        raw = [{"question": "Q1", "options": ["A", "B"]}]
        result = _normalize_interrupt_questions(raw)

        assert len(result) == 1
        assert result[0]["question"] == "Q1"
        assert result[0]["options"][0] == {"label": "A", "value": "A"}
        assert result[0]["multi_select"] is False
        assert result[0]["allow_other"] is True

    def test_invalid_question_filtered(self):
        raw = [{"question": "  "}, "Q2", {"question": "有效问题"}]
        result = _normalize_interrupt_questions(raw)

        assert len(result) == 1
        assert result[0]["question"] == "有效问题"


class TestCoerceInterruptPayload:
    """测试 _coerce_interrupt_payload 函数"""

    def test_dict_input(self):
        info = {"question": "test?", "options": ["a", "b"]}
        result = _coerce_interrupt_payload(info)
        assert result == info

    def test_string_input(self):
        info = "just a string"
        result = _coerce_interrupt_payload(info)
        assert isinstance(result, dict)

    def test_none_input(self):
        result = _coerce_interrupt_payload(None)
        assert isinstance(result, dict)
