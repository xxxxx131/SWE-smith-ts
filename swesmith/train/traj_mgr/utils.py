"""
Utility functions for transforming SWE-agent trajectories to fine-tuning format.
"""

import json
import os
import yaml

from pathlib import Path
from swesmith import REPO_DIR

XML_STR_REPLACES = ["old_str", "new_str", "file_text"]


def _load_system_prompt() -> str:
    """Load system prompt used to rewrite trajectory system messages.

    By default, this keeps backward-compatible behavior and reads from:
      agent/swesmith_infer.yaml

    To align SFT conversion with a different generation config (e.g. TypeScript),
    set:
      SWESMITH_SYSTEM_PROMPT_CONFIG=agent/<your_config>.yaml
    """

    config_path_raw = os.getenv("SWESMITH_SYSTEM_PROMPT_CONFIG", "agent/swesmith_infer.yaml")
    config_path = Path(config_path_raw)
    if not config_path.is_absolute():
        config_path = REPO_DIR / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"System prompt config not found: {config_path}")
    return yaml.safe_load(config_path.read_text())["agent"]["templates"]["system_template"]


SYSTEM_PROMPT = _load_system_prompt()


def _is_valid_message(message: object) -> bool:
    return isinstance(message, dict) and "role" in message and "content" in message


def _sanitize_messages(messages: list[object]) -> list[dict]:
    return [m for m in messages if _is_valid_message(m)]  # type: ignore[return-value]


def get_messages(traj: dict) -> list[dict]:
    """Extract messages from a swe-agent trajectory.

    We assume that the messages of the last step correspond to the
    full message history.
    This is a bit of an approximation (e.g., requeries after blocked actions
    aren't fully captured)
    """
    last_step = traj["trajectory"][-1]
    # There was a change in output formats in swe-agent 1.1.0:
    # https://swe-agent.com/latest/usage/trajectories/
    # For < 1.1.0, we had the 'messages' field that included messages
    # _after_ the message was performed (and then we remove the last message because
    # it contains the submit/patch)
    # For >= 1.1.0, we have the 'query' field that includes messages that were the
    # direct input to the agent at that step (so do not need to exclude the last message)
    if "messages" in last_step:
        candidate = last_step["messages"][:-1]
    else:
        if last_step["response"] in [
            "Exit due to cost limit",
            "Exit due to context window",
        ]:
            if len(traj["trajectory"]) >= 2:
                candidate = traj["trajectory"][-2].get("query", [])[:]
            else:
                candidate = []
        else:
            candidate = last_step.get("query", [])[:]

    sanitized = _sanitize_messages(candidate)
    if sanitized:
        return sanitized

    # Some failed trajectories (e.g., model/provider config errors) can leave
    # `query` as `[{}]`. Fall back to `history` to avoid hard failures.
    fallback = _sanitize_messages(traj.get("history", []))
    if fallback:
        return fallback

    raise ValueError("No valid messages found in trajectory")


def transform_traj_backticks(traj: dict) -> dict:
    """Transform a swe-agent trajectory to backticks format, i.e.,
    for use with the `thought-action` parser of swe-agent where actions
    are extracted from triple-backticks blocks.
    """
    new_traj = []
    for message in get_messages(traj):
        role = message["role"] if message["role"] != "tool" else "user"
        if message["role"] == "assistant":
            content = f"{message['thought']}\n\n```\n{message['action']}\n```"
        elif message["role"] == "system":
            content = message["content"]
        else:
            if isinstance(message["content"], list):
                assert len(message["content"]) == 1
                content = message["content"][0]["text"]
            elif isinstance(message["content"], str):
                content = message["content"]
            else:
                raise ValueError(f"Message type not recognized: {type(message)}")
        new_traj.append({"role": role, "content": content})
    return {"messages": new_traj}


def tool_call_to_action(tool_calls: None | list[dict]) -> list[str]:
    actions = []
    if tool_calls is None:
        return []
    for tool_call in tool_calls:
        action = [f"<function={tool_call['function']['name']}>"]
        arguments_raw = tool_call["function"].get("arguments", {})
        if isinstance(arguments_raw, str):
            arguments = json.loads(arguments_raw) if arguments_raw else {}
        elif isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            raise ValueError(f"Tool call arguments must be str/dict, got: {type(arguments_raw)}")
        for k, v in arguments.items():
            a = f"<parameter={k}>{v}</parameter>"
            if k in XML_STR_REPLACES:
                a = f"<parameter={k}>\n{v}\n</parameter>"
            action.append(a)
        action.append("</function>")
        actions.append("\n".join(action))
    return actions


def _assistant_content_to_xml(message: dict) -> str:
    """Normalize assistant messages to XML function-calling text.

    Supports both:
    1) function_calling trajectories where tool calls are in `tool_calls`
    2) xml_function_calling trajectories where XML action is embedded in `content`
    """

    if message["content"] == "Exit due to cost limit":
        return (
            "Since we have successfully fixed the issue and verified it works, "
            + "let's submit the changes:\n\n"
            + "<function=submit>\n</function>"
        )

    tool_calls = message.get("tool_calls")
    if tool_calls:
        thought = message.get("thought", message["content"])
        action = "\n".join(tool_call_to_action(tool_calls))
        return f"{thought}\n\n{action}".strip()

    content = message.get("content")
    if isinstance(content, str) and "<function=" in content:
        # xml_function_calling parser stores the raw model text in `content`.
        return content.strip()

    return str(message.get("thought", content)).strip()


def transform_traj_xml(traj: dict) -> dict:
    new_traj = []
    for message in get_messages(traj):
        role = message["role"] if message["role"] != "tool" else "user"
        if message["role"] == "assistant":
            content = _assistant_content_to_xml(message)
        elif message["role"] == "system":
            # We replace the system prompt that was used for generating the training trajectories
            # with the system prompt that SWE-agent-LM will use for inference.
            content = SYSTEM_PROMPT
        else:
            if isinstance(message["content"], list):
                assert len(message["content"]) == 1
                content = message["content"][0]["text"]
            elif isinstance(message["content"], str):
                content = message["content"]
            else:
                raise ValueError(f"Message type not recognized: {type(message)}")
        new_traj.append({"role": role, "content": content})
    return {"messages": new_traj}


def transform_traj_toolcalls(traj: dict) -> dict:
    return {"messages": get_messages(traj)}


MAP_STYLE_TO_FUNC = {
    "ticks": transform_traj_backticks,
    "tool": transform_traj_toolcalls,
    "xml": transform_traj_xml,
}
