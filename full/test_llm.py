#!/usr/bin/env python3
"""
test_llm.py — Objective LLM control test harness

Usage:
  python test_llm.py                          # run all built-in + JSON scenarios
  python test_llm.py --category responsiveness  # run one category
  python test_llm.py --case <name>            # run one named case
  python test_llm.py --interactive            # enter sentence + state manually
  python test_llm.py --json <file.json>       # load test cases from JSON file
  python test_llm.py --list                   # list all available categories

No MQTT/HA connections are made. LLM is called with the injected state.
Device actions are simulated (printed only, nothing sent to hardware).

JSON test case formats supported:
  Standard:    {"category": "...", "name": "...", "sentence": "...", "state": {...}}
  Consistency: {..., "repeat": 5}               -> run same case N times
  Stepwise:    {..., "rounds": [{"sentence":"..","state":{..}}, ...]}  -> multi-round
  Sentinel:    {"category": "sentinel", "name": "...", "state": {...}}  -> sentinel_judge
"""

import argparse
import json
import sys
import os
import time

from llm_client import llm_goal
from llm_client_sentinel import sentinel_judge

# Inject a default test occupant into the knowledge graph's in-memory registry.
# graph_utils.CURRENT_USERS_IN_ROOM is normally populated by record_entry_event()
# at runtime; during testing we set it directly.
# Change TEST_USER to any name that exists in ontology/all_in_one.ttl.
import graph_utils as _gu
TEST_USER = "JunmengLyu"
_gu.CURRENT_USERS_IN_ROOM.setdefault("Office", set()).add(TEST_USER)

# ---------------------------------------------------------------------------
# Default state template
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "T_air": 26.5,
    "T_skin": 34.5,
    "lux": 350.0,
    "noise_db": 45.0,
    "humidity": 58.0,
    "CO2": 680.0,
    "PM25": 12.0,
    "TVOC": 90.0,
    "OUTTEMP": 28.0,
    "OUTHUMID": 65.0,
    "fan_on": False,
    "fan_pct": 0,
    "fan_swing_mode": False,
    "fan_available": True,
    "ac_on": False,
    "ac_mode": "off",
    "ac_set_temperature": None,
    "ac_available": True,
    "light_on": True,
    "light_brightness_pct": 80,
    "light_color_temperature_k": 4000,
    "light_available": True,
    "purifier_on": False,
    "purifier_level": 0,
    "purifier_available": True,
    "fan_power": 0.0,
    "light_power": 8.5,
    "purifier_power": 0.0,
    "ac_power": 0.0,
    "outdoor_wind": "10",
    "rain_1h": "0",
    "air_quality": "Good",
    "weather_desc": "Sunny",
    "recent_user_intent": "no active usercommand",
    "recent_device_goal": {},
    "v_air": 0.1,
}

# ---------------------------------------------------------------------------
# Dry-run device control
# ---------------------------------------------------------------------------
def simulate_device_control(goal: dict):
    constraints = goal.get("constraints", {})
    if not constraints:
        print("  [DRY-RUN] No device changes — LLM returned empty constraints")
        return

    print("  [DRY-RUN] Simulated device actions:")

    fan_on = constraints.get("fan_on")
    fan_pct = constraints.get("fan_speed_pct")
    fan_swing = constraints.get("fan.swing_mode")
    if fan_on is not None:
        if fan_on is False or fan_pct == 0:
            print(f"    FAN → OFF")
        else:
            print(f"    FAN → ON, speed={fan_pct if fan_pct is not None else '(current)'}%")
    if fan_swing is not None:
        print(f"    FAN swing → {fan_swing}")

    ac_on = constraints.get("ac_on")
    ac_temp = constraints.get("ac_temperature")
    ac_mode = constraints.get("ac_mode", "cool")
    if ac_on is True:
        print(f"    AC → ON, mode={ac_mode}, setpoint={ac_temp}°C")
    elif ac_on is False:
        print(f"    AC → OFF")

    light_on = constraints.get("light.on")
    brightness = constraints.get("light.brightness")
    kelvin = constraints.get("light.color_temperature")
    if light_on is not None:
        print(f"    LIGHT → {'ON' if light_on else 'OFF'}")
    if brightness is not None:
        print(f"    LIGHT brightness → {brightness}%")
    if kelvin is not None:
        print(f"    LIGHT color temp → {kelvin}K")

    schedule = goal.get("light_schedule")
    if schedule and isinstance(schedule, list):
        print(f"    LIGHT schedule → {len(schedule)} step(s):")
        for i, step in enumerate(schedule):
            print(f"      step {i+1}: params={step.get('params')}, duration={step.get('duration')}s")

    purifier_on = constraints.get("purifier_on")
    purifier_level = constraints.get("purifier_level")
    if purifier_on is True:
        print(f"    PURIFIER → ON, level={purifier_level}")
    elif purifier_on is False:
        print(f"    PURIFIER → OFF")

    buttons = goal.get("button_actions", [])
    if buttons:
        print(f"    BUTTON → {buttons}")

    window = goal.get("window_suggestion", "none")
    if window and window != "none":
        print(f"    WINDOW → {window}")


# ---------------------------------------------------------------------------
# Run one standard test case (single round)
# ---------------------------------------------------------------------------
def run_test(name: str, sentence: str, state_overrides: dict, category: str = "") -> dict:
    state = {**DEFAULT_STATE, **state_overrides}

    prefix = f"[{category}] " if category else ""
    print("=" * 70)
    print(f"{prefix}TEST: {name}")
    print(f"  Sentence : {sentence}")
    if state_overrides:
        print(f"  State overrides: {json.dumps(state_overrides, ensure_ascii=False)}")
    print("-" * 70)

    t0 = time.time()
    goal = llm_goal(sentence, state)
    latency = time.time() - t0

    print(f"  LLM latency : {latency:.2f}s")
    print(f"  Explanation : {goal.get('explanation', '(none)')}")
    print(f"  Constraints : {json.dumps(goal.get('constraints', {}), ensure_ascii=False, indent=4)}")
    simulate_device_control(goal)
    print()

    return {
        "name": name,
        "category": category,
        "sentence": sentence,
        "latency_s": round(latency, 3),
        "goal": goal,
    }


# ---------------------------------------------------------------------------
# Run stepwise (multi-round) test
# ---------------------------------------------------------------------------
def run_stepwise(name: str, rounds: list, category: str = "stepwise") -> dict:
    print("=" * 70)
    print(f"[{category}] STEPWISE TEST: {name}")
    print("-" * 70)

    results = []
    for i, rnd in enumerate(rounds):
        sentence = rnd["sentence"]
        state_overrides = rnd.get("state", {})
        state = {**DEFAULT_STATE, **state_overrides}
        print(f"  Round {i+1}: {sentence}")

        t0 = time.time()
        goal = llm_goal(sentence, state)
        latency = time.time() - t0

        print(f"    Latency: {latency:.2f}s")
        print(f"    Constraints: {json.dumps(goal.get('constraints', {}), ensure_ascii=False)}")
        results.append({"round": i+1, "sentence": sentence, "latency_s": round(latency, 3), "goal": goal})

    print()
    return {"name": name, "category": category, "rounds": results}


# ---------------------------------------------------------------------------
# Run sentinel test (no user sentence — proactive monitoring)
# ---------------------------------------------------------------------------
def run_sentinel(name: str, state_overrides: dict) -> dict:
    state = {**DEFAULT_STATE, **state_overrides}
    state["previous_state"] = {}

    print("=" * 70)
    print(f"[sentinel] TEST: {name}")
    print(f"  State overrides: {json.dumps(state_overrides, ensure_ascii=False)}")
    print("-" * 70)

    t0 = time.time()
    result = sentinel_judge(state)
    latency = time.time() - t0

    print(f"  LLM latency    : {latency:.2f}s")
    print(f"  Should notify  : {result.get('should_notify')}")
    if result.get("should_notify"):
        issues = result.get("issues", [])
        if isinstance(issues, list):
            for issue in issues:
                print(f"  Issue   : {issue.get('issue', '')}")
                print(f"  Suggest : {issue.get('suggestion', '')}")
        else:
            print(f"  Issue : {result.get('issue', '')}")
    else:
        print(f"  Debug : {result.get('debug_reason', 'No alert')}")
    print()

    return {
        "name": name,
        "category": "sentinel",
        "latency_s": round(latency, 3),
        "result": result,
    }


# ---------------------------------------------------------------------------
# Dispatch a single case dict
# ---------------------------------------------------------------------------
def dispatch_case(case: dict) -> dict:
    category = case.get("category", "")
    name = case.get("name", "unnamed")

    if category == "sentinel":
        return run_sentinel(name, case.get("state", {}))

    if "rounds" in case:
        return run_stepwise(name, case["rounds"], category)

    repeat = case.get("repeat", 1)
    sentence = case.get("sentence", "")
    state_overrides = case.get("state", {})

    if repeat > 1:
        sub_results = []
        for r in range(1, repeat + 1):
            print(f"  (Repetition {r}/{repeat})")
            res = run_test(f"{name}__rep{r}", sentence, state_overrides, category)
            sub_results.append(res)
        return {"name": name, "category": category, "repetitions": sub_results}

    return run_test(name, sentence, state_overrides, category)


# ---------------------------------------------------------------------------
# Built-in smoke-test cases (minimal set; full tests live in test_cases.json)
# ---------------------------------------------------------------------------
BUILTIN_SCENARIOS = [
    {"category": "responsiveness", "name": "builtin_fan_off",   "sentence": "Turn off the fan.", "state": {"fan_on": True, "fan_pct": 30}},
    {"category": "responsiveness", "name": "builtin_ac_26",     "sentence": "Set AC to 26°C cooling mode.", "state": {}},
    {"category": "sensor_missing", "name": "builtin_no_temp",   "sentence": "I feel hot and stuffy.", "state": {"T_air": None, "T_skin": None}},
    {"category": "fault_tolerance","name": "builtin_co2_9999",  "sentence": "How is the air quality?", "state": {"CO2": 9999.0}},
    {"category": "device_failure", "name": "builtin_no_fan",    "sentence": "Turn on the fan please.", "state": {"fan_available": False}},
    {"category": "sentinel",       "name": "builtin_hot_humid", "state": {"T_air": 32.0, "humidity": 85.0, "T_skin": 36.0}},
]

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="LLM control dry-run tester")
    parser.add_argument("--case",        help="Run one named case")
    parser.add_argument("--category",    help="Run all cases in a category")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--json",        help="Load test cases from a JSON file",
                        default=os.path.join(os.path.dirname(__file__), "test_cases.json"))
    parser.add_argument("--list",        action="store_true", help="List categories and case counts")
    args = parser.parse_args()

    all_cases = []
    if os.path.exists(args.json):
        with open(args.json, encoding="utf-8") as f:
            all_cases = json.load(f)
        print(f"Loaded {len(all_cases)} cases from {args.json}")
    else:
        print(f"No test_cases.json found — using built-in scenarios only.")
        all_cases = BUILTIN_SCENARIOS

    if args.list:
        from collections import Counter
        counts = Counter(c.get("category", "unknown") for c in all_cases)
        print("\nAvailable categories:")
        for cat, n in sorted(counts.items()):
            print(f"  {cat:<35} {n} cases")
        return

    if args.interactive:
        sentence = input("Enter user sentence (or press Enter for sentinel test): ").strip()
        raw = input("State overrides as JSON (or Enter for defaults): ").strip()
        state_overrides = json.loads(raw) if raw else {}
        if sentence:
            result = run_test("interactive", sentence, state_overrides, "interactive")
        else:
            result = run_sentinel("interactive_sentinel", state_overrides)
        results = [result]

    elif args.case:
        matched = [c for c in all_cases if c.get("name") == args.case]
        if not matched:
            print(f"Unknown case '{args.case}'")
            sys.exit(1)
        results = [dispatch_case(matched[0])]

    elif args.category:
        subset = [c for c in all_cases if c.get("category") == args.category]
        if not subset:
            print(f"No cases found for category '{args.category}'")
            sys.exit(1)
        print(f"Running {len(subset)} cases in category '{args.category}'")
        results = [dispatch_case(c) for c in subset]

    else:
        print(f"Running all {len(all_cases)} cases...")
        results = [dispatch_case(c) for c in all_cases]

    out_path = os.path.join(os.path.dirname(__file__), "test_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved → {out_path}")

    latencies = [r["latency_s"] for r in results if "latency_s" in r]
    if latencies:
        print(f"LLM latency — avg: {sum(latencies)/len(latencies):.2f}s  "
              f"min: {min(latencies):.2f}s  max: {max(latencies):.2f}s  n={len(latencies)}")


if __name__ == "__main__":
    main()
