from __future__ import annotations

import json
from decimal import Decimal

from langchain_core.messages import AIMessage

from yuxi.services.chat_service import _message_to_json_dict


def test_message_json_dump_serializes_decimal_tool_arguments():
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "enterprise_request_refund",
                "args": {"amount": Decimal("899.00")},
                "id": "tool-call-1",
                "type": "tool_call",
            }
        ],
    )

    payload = _message_to_json_dict(message)

    assert payload["tool_calls"][0]["args"]["amount"] == "899.00"
    json.dumps(payload)
