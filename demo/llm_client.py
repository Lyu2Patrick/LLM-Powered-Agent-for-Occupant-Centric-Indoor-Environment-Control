# llm_client.py
# LLM goal-inference client for indoor environment control.
#
# The LLM receives the current sensor state and an occupant utterance,
# and outputs structured device control commands (AC, fan, light, purifier)
# grounded in the semantic knowledge graph.
#
# Usage:
#     from llm_client import llm_goal
#     goal = llm_goal(user_sentence, state)

from openai import OpenAI
import os, json, re
from graph_utils import room_exists, devices_in_room, users_in_room

# Set OPENAI_API_KEY as an environment variable before running.
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

MODEL = "gpt-4o-2024-11-20"
MAX_HISTORY = 5

_chat_history = []


def format_float(val, unit=""):
    if val is None:
        return f"Unknown{unit}"
    try:
        return f"{float(val):.2f}{unit}"
    except Exception:
        return f"Invalid{unit}"


def _build_prompt(user_sentence: str, state: dict, room: str) -> str:
    """Construct the user-turn prompt from current environment state."""
    device_info_list = devices_in_room(room)
    device_line = ", ".join(d["name"] for d in device_info_list) if device_info_list else "(no device records in knowledge graph)"

    power_lines = [
        f"- {d['name']} (ID: {d['device_id']}): Typical {format_float(d['typical'], 'W')}, "
        f"range {format_float(d['min'], 'W')} – {format_float(d['max'], 'W')}"
        for d in device_info_list
    ]
    power_info = "\n".join(power_lines)

    prompt = (
        f"Room: {room}\n"
        f"Controllable Devices: {device_line}\n"
        f"Current Environmental Conditions:\n"
        f"- Indoor Air Temperature: {format_float(state.get('T_air'), '°C')}\n"
        f"- Indoor Relative Humidity: {format_float(state.get('humidity'), '%')}\n"
        f"- Air Velocity: {format_float(state.get('v_air'), 'm/s')}\n"
        f"- CO₂ Concentration: {format_float(state.get('CO2'), 'ppm')}\n"
        f"- Skin Temperature (Cheek): {format_float(state.get('T_skin'), '°C')}\n"
        f"- Illuminance: {format_float(state.get('lux'), 'lux')}\n"
        f"- Noise Level: {format_float(state.get('noise_db'), 'dB')}\n"
        f"- PM2.5: {format_float(state.get('PM25'), 'μg/m³')}\n"
        f"- TVOC: {format_float(state.get('TVOC'), 'ppb')}\n"
        f"- Outdoor Air Temperature: {format_float(state.get('OUTTEMP'), '°C')}\n"
        f"- Outdoor Relative Humidity: {format_float(state.get('OUTHUMID'), '%')}\n"
        f"- AC Power: {format_float(state.get('ac_power'), 'W')}\n"
        f"- Desk Lamp Power: {format_float(state.get('light_power'), 'W')}\n"
        f"- Air Purifier Power: {format_float(state.get('purifier_power'), 'W')}\n"
        f"- Fan Power: {format_float(state.get('fan_power'), 'W')}\n"
        f"- Outdoor Wind Speed: {state.get('outdoor_wind')} km/h\n"
        f"- Rainfall (Last Hour): {state.get('rain_1h')} mm/h\n"
        f"- Outdoor Air Quality Index: {state.get('air_quality')}\n"
        f"- Weather: {state.get('weather_desc')}\n"
        f"\nCurrent Device Status:\n"
        f"- Fan Active (fan_on): {state.get('fan_on')}\n"
        f"- Fan Speed (fan_pct): {state.get('fan_pct')}\n"
        f"- Fan Swing Mode: {state.get('fan_swing_mode')}\n"
        f"- AC Active (ac_on): {state.get('ac_on')}\n"
        f"- AC Mode: {state.get('ac_mode')}\n"
        f"- AC Setpoint: {format_float(state.get('ac_set_temperature'), '°C')}\n"
        f"- AC Available: {state.get('ac_available')}\n"
        f"- Fan Available: {state.get('fan_available')}\n"
        f"- Light Available: {state.get('light_available')}\n"
        f"- Purifier Available: {state.get('purifier_available')}\n"
        f"- Light Active (light_on): {state.get('light_on')}\n"
        f"- Light Brightness: {state.get('light_brightness_pct')}%\n"
        f"- Light Color Temp: {state.get('light_color_temperature_k')}K\n"
        f"- Purifier Active (purifier_on): {state.get('purifier_on')}\n"
        f"- Purifier Level: {state.get('purifier_level')}\n"
        f"\nDevice Power Information:\n{power_info}\n"
        f"\nUser said: \"{user_sentence}\""
    )

    users = users_in_room(room)
    if users:
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
        prompt += "\nOccupants Present:\n" + "\n".join(user_lines) + "\n"
    else:
        prompt += "\nNo occupant presence detected.\n"

    return prompt


def _parse_args(msg, content):
    """Parse function call arguments from LLM response, with JSON fallback."""
    args = None
    if msg.tool_calls:
        args = json.loads(msg.tool_calls[0].function.arguments)
    elif msg.function_call and msg.function_call.arguments:
        args = json.loads(msg.function_call.arguments)

    if args is None:
        print("Warning: LLM did not call a function — attempting JSON fallback")
        try:
            args = json.loads(content)
        except json.JSONDecodeError:
            pass

        if isinstance(args, dict) and "arguments" in args:
            args = args["arguments"]

        if args is None or "constraints" not in args:
            for match in re.finditer(r"\{[\s\S]*?\}", content):
                try:
                    candidate = json.loads(match.group(0))
                    if "constraints" in candidate:
                        args = candidate
                        break
                    if "arguments" in candidate and "constraints" in candidate["arguments"]:
                        args = candidate["arguments"]
                        break
                except json.JSONDecodeError:
                    continue

        if args is None or "constraints" not in args:
            for block in re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", content):
                try:
                    candidate = json.loads(block)
                    if "constraints" in candidate:
                        args = candidate
                        break
                except json.JSONDecodeError:
                    continue

    return args


def llm_goal(user_sentence: str, state: dict, return_meta: bool = False) -> dict:
    """
    Call the LLM to infer environment control goals from a user utterance.

    Args:
        user_sentence: Natural language input from the occupant.
        state:         Current sensor readings and device states.
        return_meta:   If True, also return raw LLM response metadata.

    Returns:
        A dict with keys: room, constraints, explanation, window_suggestion,
        light_schedule, button_actions.
    """
    from prompt_templates_free import BASE_SYSTEM, SET_ENV_GOAL_FUNC

    room = "Office"
    if not room_exists(room):
        print(f"Warning: room '{room}' not found in knowledge graph")

    prompt_user = _build_prompt(user_sentence, state, room)
    new_turn = {"role": "user", "content": prompt_user}
    context = [{"role": "system", "content": BASE_SYSTEM}] + _chat_history[-MAX_HISTORY:] + [new_turn]

    raw_content = None
    raw_args = None
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=context,
            functions=[SET_ENV_GOAL_FUNC],
            function_call={"name": "set_env_goal"},
            temperature=0.2,
            timeout=120,
        )
        msg = resp.choices[0].message
        raw_content = msg.content
        args = _parse_args(msg, raw_content or "")
        raw_args = args

        # Update rolling conversation history
        _chat_history.append(new_turn)
        _chat_history.append({"role": "assistant", "content": raw_content or "[no text]"})
        if len(_chat_history) > MAX_HISTORY * 2:
            _chat_history.pop(0); _chat_history.pop(0)

        goal = {
            "room": room,
            "constraints": args.get("constraints", {}),
            "explanation": args.get("explanation", ""),
            "window_suggestion": args.get("window_suggestion", "none"),
            "light_schedule": args.get("light_schedule", None),
            "button_actions": args.get("button_actions", []),
        }

        # Correct fan button direction (hardware quirk)
        corrected = []
        for act in goal["button_actions"]:
            if act.endswith("turn_left"):
                corrected.append(act.replace("turn_left", "turn_right"))
            elif act.endswith("turn_right"):
                corrected.append(act.replace("turn_right", "turn_left"))
            else:
                corrected.append(act)
        goal["button_actions"] = corrected

        print("Final control goal:", goal)
        print(f"Window suggestion: {goal['window_suggestion']}")

        if return_meta:
            return {
                "goal": goal,
                "meta": {
                    "model": MODEL,
                    "raw_content": raw_content,
                    "raw_tool_arguments": str(raw_args),
                    "parsed_arguments": args,
                    "history_length_after_call": len(_chat_history),
                },
            }
        return goal

    except Exception as e:
        print(f"LLM error: {e}")
        error_goal = {
            "room": room,
            "constraints": {},
            "window_suggestion": "none",
            "explanation": f"Error — using defaults. ({e})",
            "light_schedule": None,
            "button_actions": [],
        }
        if return_meta:
            return {"goal": error_goal, "meta": {"error": str(e)}}
        return error_goal
