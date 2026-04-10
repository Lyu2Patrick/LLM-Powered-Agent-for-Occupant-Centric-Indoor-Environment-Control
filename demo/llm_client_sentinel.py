# llm_client_sentinel.py
# Sentinel LLM agent for proactive environmental monitoring.
#
# Runs on a periodic schedule (default: every hour) and independently
# assesses whether any environmental condition warrants notifying the
# occupant, without waiting for user input.

from openai import OpenAI
import os, json, time
from prompt_templates_sentinel import SENTINEL_SYSTEM, SENTINEL_NOTIFY_FUNC
from graph_utils import get_room_power_summary, users_in_room

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

MODEL = "gpt-4o-2024-11-20"


def _format_memory(memory: list) -> str:
    """Format the last 5 sentinel records as a readable text block."""
    if not memory:
        return "No historical memory available."
    lines = []
    for i, item in enumerate(memory[-5:], 1):
        ts = time.strftime("%H:%M:%S", time.localtime(item["timestamp"]))
        issues = item.get("result", {}).get("issues")
        if isinstance(issues, list) and issues:
            summary = " | ".join(iss["issue"] for iss in issues)
        else:
            summary = item.get("result", {}).get("issue", "No alert triggered")
        lines.append(f"{i}. [{ts}] {summary}")
    return "\n".join(lines)


def sentinel_judge(state: dict, memory: list = None) -> dict:
    """
    Assess the current environment and decide whether to notify the user.

    Args:
        state:  Full environment state dict (same schema as control loop).
                Should include a 'previous_state' key with the last snapshot.
        memory: Optional list of past sentinel result records for trend analysis.

    Returns:
        {
            "should_notify": bool,
            "issues": [{"issue": str, "suggestion": str, "analysis": str}, ...],
            "debug_reason": str   # present when should_notify is False
        }
    """
    room = state.get("room", "Office")
    power_summary = get_room_power_summary(room)

    users = users_in_room(room)
    user_lines = []
    for u in users:
        info = f"- {u['name']}"
        extras = []
        if u.get("gender"): extras.append(u["gender"])
        if u.get("age"): extras.append(f"{u['age']}yrs")
        if u.get("height"): extras.append(f"{u['height']}cm")
        if u.get("weight"): extras.append(f"{u['weight']}kg")
        if u.get("prefersTS") is not None: extras.append(f"Thermal Preference ΔTS={u['prefersTS']:+.1f}")
        if u.get("conditions"): extras.append(f"Health conditions: {', '.join(u['conditions'])}")
        if extras:
            info += " (" + ", ".join(extras) + ")"
        user_lines.append(info)
    user_block = "\nOccupants Present:\n" + "\n".join(user_lines) if user_lines else "\nNo occupant presence detected."

    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    user_message = (
        f"Current Time: {current_time}\n\n"
        f"Room: {room}\n"
        f"Device Power Consumption:\n{power_summary}\n\n"
        f"Current environment state (includes recent_user_intent and previous_state):\n"
        f"{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"
        f"Last 5 sentinel records:\n{_format_memory(memory)}\n\n"
        f"Based on the above, determine whether any environmental condition warrants notifying the user. "
        f"If recent user intent conflicts with current conditions, flag it."
        f"{user_block}\n"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SENTINEL_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            tools=[{"type": "function", "function": SENTINEL_NOTIFY_FUNC}],
            tool_choice="auto",
        )

        tool_calls = response.choices[0].message.tool_calls
        if tool_calls:
            arguments = json.loads(tool_calls[0].function.arguments)
            if not arguments.get("should_notify", False):
                arguments.setdefault("debug_reason", "No significant anomaly detected")
            elif not arguments.get("issues"):
                arguments["debug_reason"] = "should_notify=True but no specific issue reported"
            return arguments
        else:
            text = response.choices[0].message.content or "(none)"
            return {"should_notify": False, "debug_reason": f"No tool call — model response: {text}"}

    except Exception as e:
        print(f"Sentinel LLM error: {e}")
        return {"should_notify": False, "debug_reason": f"Exception: {e}"}
