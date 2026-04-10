#!/usr/bin/env python3
"""
demo.py — Interactive demo for LLM-based indoor environment control.

Identical to the full system in all logic, prompts, and knowledge graph usage.
The only difference: sensor state is defined manually here instead of coming
from live MQTT sensors and Home Assistant.

Requirements: OpenAI API key only. No hardware needed.

Usage:
    export OPENAI_API_KEY="sk-..."
    python demo.py                              # interactive mode
    python demo.py --sentence "I feel warm."   # single request
    python demo.py --state '{"T_air": 30, "fan_available": false}'  # with state overrides
    python demo.py --sentinel                  # test proactive sentinel agent
"""

import argparse
import json
import os
import time

from llm_client import llm_goal
from llm_client_sentinel import sentinel_judge
import graph_utils as _gu

# Register a demo occupant so the knowledge graph returns user profile data.
# This name must exist in ontology/all_in_one.ttl.
DEMO_USER = "JunmengLyu"
_gu.CURRENT_USERS_IN_ROOM.setdefault("Office", set()).add(DEMO_USER)

# ---------------------------------------------------------------------------
# Default sensor state — representative indoor office environment.
# Override any field via --state '{"key": value}' or edit directly below.
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    # Indoor thermal environment
    "T_air": 26.5,          # Air temperature (°C)
    "T_skin": 34.5,         # Cheek skin temperature (°C)
    "humidity": 58.0,       # Relative humidity (%)
    "v_air": 0.1,           # Air velocity (m/s)
    # Air quality
    "CO2": 680.0,           # CO₂ concentration (ppm)
    "PM25": 12.0,           # PM2.5 (μg/m³)
    "TVOC": 90.0,           # TVOC (ppb)
    # Lighting & acoustics
    "lux": 350.0,           # Illuminance (lux)
    "noise_db": 45.0,       # Noise level (dB)
    # Outdoor conditions
    "OUTTEMP": 28.0,        # Outdoor temperature (°C)
    "OUTHUMID": 65.0,       # Outdoor humidity (%)
    "outdoor_wind": "10",   # Wind speed (km/h)
    "rain_1h": "0",         # Rainfall last hour (mm/h)
    "air_quality": "Good",  # Outdoor AQI description
    "weather_desc": "Sunny",
    # Device status
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
    # Power readings (W)
    "fan_power": 0.0,
    "light_power": 8.5,
    "purifier_power": 0.0,
    "ac_power": 0.0,
    # Context fields
    "recent_user_intent": "no active usercommand",
    "recent_device_goal": {},
}


def print_goal(goal: dict):
    print(f"\n  Explanation : {goal.get('explanation', '(none)')}")
    constraints = goal.get("constraints", {})
    if constraints:
        print(f"  Commands    :")
        for k, v in constraints.items():
            print(f"    {k}: {v}")
    else:
        print(f"  Commands    : (no device changes)")
    window = goal.get("window_suggestion", "none")
    if window and window != "none":
        print(f"  Window      : {window}")
    schedule = goal.get("light_schedule")
    if schedule:
        print(f"  Light sched : {len(schedule)} step(s)")
    print()


def run_interactive(state: dict):
    print("\nInteractive mode — type any request, or 'quit' to exit.\n")
    while True:
        try:
            sentence = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not sentence or sentence.lower() in ("quit", "exit", "q"):
            break
        print("─" * 60)
        t0 = time.time()
        goal = llm_goal(sentence, state)
        print(f"  Latency     : {time.time() - t0:.2f}s")
        print_goal(goal)


def run_single(sentence: str, state: dict):
    print(f'\nRequest: "{sentence}"')
    print("─" * 60)
    t0 = time.time()
    goal = llm_goal(sentence, state)
    print(f"  Latency     : {time.time() - t0:.2f}s")
    print_goal(goal)


def run_sentinel(state: dict):
    state = {**state, "previous_state": {}}
    print("\nRunning sentinel agent (proactive monitoring)...")
    print("─" * 60)
    t0 = time.time()
    result = sentinel_judge(state)
    print(f"  Latency       : {time.time() - t0:.2f}s")
    print(f"  Should notify : {result.get('should_notify')}")
    if result.get("should_notify"):
        issues = result.get("issues", [])
        if isinstance(issues, list):
            for issue in issues:
                print(f"  Issue         : {issue.get('issue', '')}")
                print(f"  Suggestion    : {issue.get('suggestion', '')}")
        else:
            print(f"  Issue         : {result.get('issue', '')}")
    else:
        print(f"  Debug         : {result.get('debug_reason', 'No alert triggered.')}")
    print()


def main():
    parser = argparse.ArgumentParser(description="LLM indoor environment control — demo")
    parser.add_argument("--sentence",  help="Single natural-language request")
    parser.add_argument("--state",     help='JSON state overrides, e.g. \'{"T_air": 30}\'')
    parser.add_argument("--sentinel",  action="store_true", help="Run the sentinel monitoring agent")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set.\n  export OPENAI_API_KEY='sk-...'")
        raise SystemExit(1)

    state_overrides = json.loads(args.state) if args.state else {}
    state = {**DEFAULT_STATE, **state_overrides}

    if args.sentinel:
        run_sentinel(state)
    elif args.sentence:
        run_single(args.sentence, state)
    else:
        run_interactive(state)


if __name__ == "__main__":
    main()
