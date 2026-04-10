#!/usr/bin/env python3
"""
control_free.py -- Free-mode control loop.

The LLM directly outputs device control commands (AC setpoint, fan speed,
light, purifier) based on occupant utterances and real-time sensor data.
No thermal model is involved.

Set the following environment variables before running:
    OPENAI_API_KEY   -- OpenAI API key
    HA_TOKEN         -- Home Assistant long-lived access token
"""
import paho.mqtt.client as mqtt
import json, time, requests, numpy as np, csv, os, threading
from llm_client_sentinel import sentinel_judge
from llm_client import llm_goal
from collections import deque


def poll_sentence(path="latest_sentence.txt"):
    """Check for a queued user sentence written to a text file."""
    if os.path.exists(path) and os.path.getsize(path):
        with open(path) as f:
            txt = f.read().strip()
        open(path, "w").close()
        return txt
    return None


# MQTT configuration
MQTT_BROKER = "YOUR_MQTT_BROKER_HOST"
MQTT_PORT = 1883
TOPIC_ENV_TEMP      = "home/temperature/dht11"
TOPIC_SKIN_TEMP     = "/as6221/temperature"
TOPIC_LIGHT_NOISE   = "home/light/lux"
TOPIC_NOISE_LEVEL   = "home/noise/level"
TOPIC_HUMIDITY      = "home/humidity/dht11"
TOPIC_CO2           = "home/air/eco2"
TOPIC_PM25          = "home/air/pm25"
TOPIC_TVOC          = "home/air/tvoc"
TOPIC_OUTTEMP       = "home/outdoor/temperature"
TOPIC_OUTHUMID      = "home/outdoor/humidity"
TOPIC_FAN_POWER     = "home/fan/power"
TOPIC_LIGHT_POWER   = "home/light/power"
TOPIC_PURIFIER_POWER = "home/purifier/power"
TOPIC_AC_POWER      = "home/ac/realtime_power"

latest_env_temp      = None
latest_skin_temp     = None
latest_lux           = None
latest_noise         = None
latest_CO2           = None
latest_humidity      = None
latest_PM25          = None
latest_TVOC          = None
latest_OUTTEMP       = None
latest_OUTHUMID      = None
last_env_snapshot    = None
latest_fan_power     = None
latest_fan_swing_mode = None
latest_light_power   = None
latest_purifier_power = None
latest_ac_power      = None

ac_on                   = False
fan_current_pct         = 0
purifier_on             = False
purifier_level_current  = 0
last_status_time        = 0
last_user_intent        = "no active usercommand"
last_intent_time        = 0
USER_GOAL               = {}

# Home Assistant configuration
HA_URL  = "http://YOUR_HA_HOST:8123"
HA_TOKEN = os.environ.get("HA_TOKEN", "YOUR_HOME_ASSISTANT_TOKEN_HERE")

FAN_ENTITY_ID           = "fan.dmaker_cn_747042567_p5c_s_2_fan"
FAN_SWING_ENTITY_ID     = "switch.dmaker_p5c_a6a0_horizontal_swing"
FAN_SPEED_LEVEL_ENTITY  = "number.dmaker_cn_747042567_p5c_speed_level_p_8_1"
AC_ENTITY_ID            = "climate.211106243774073_climate"
LIGHT_ENTITY_ID         = "light.yeelink_cn_876865954_lamp22_s_2"
PURIFIER_ONOFF_ENTITY_ID = "fan.zhimi_cn_94016577_ma2_s_2_air_purifier"
PURIFIER_LEVEL_ID       = "number.zhimi_cn_94016577_ma2_favorite_fan_level_p_8_1"

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


# Fan control
def set_fan_speed(percentage):
    percentage = int(percentage)
    try:
        if percentage <= 0:
            requests.post(
                f"{HA_URL}/api/services/fan/turn_off",
                headers=headers,
                json={"entity_id": FAN_ENTITY_ID}
            )
        else:
            requests.post(
                f"{HA_URL}/api/services/fan/turn_on",
                headers=headers,
                json={"entity_id": FAN_ENTITY_ID}
            )
            time.sleep(0.3)
            requests.post(
                f"{HA_URL}/api/services/number/set_value",
                headers=headers,
                json={"entity_id": FAN_SPEED_LEVEL_ENTITY, "value": percentage}
            )
    except Exception as e:
        print(f"Fan control error: {e}")


def set_fan_swing(on: bool):
    try:
        requests.post(
            f"{HA_URL}/api/services/fan/oscillate",
            headers=headers,
            json={"entity_id": FAN_ENTITY_ID, "oscillating": on}
        )
    except Exception as e:
        print(f"Fan swing control error: {e}")


def press_button(entity_id):
    try:
        requests.post(
            f"{HA_URL}/api/services/button/press",
            headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
            json={"entity_id": entity_id},
            timeout=5
        )
    except Exception:
        pass


# Air purifier control
def set_purifier_power(on: bool):
    global purifier_on
    service = "turn_on" if on else "turn_off"
    try:
        requests.post(
            f"{HA_URL}/api/services/fan/{service}",
            headers=headers,
            json={"entity_id": PURIFIER_ONOFF_ENTITY_ID}
        )
        purifier_on = on
    except Exception as e:
        print(f"Purifier power control error: {e}")


def set_purifier_speed(level):
    global purifier_level_current
    try:
        requests.post(
            f"{HA_URL}/api/services/number/set_value",
            headers=headers,
            json={"entity_id": PURIFIER_LEVEL_ID, "value": int(level)}
        )
        purifier_level_current = level
    except Exception as e:
        print(f"Purifier speed control error: {e}")


# AC control
def turn_off_ac():
    hvac_mode, _ = get_current_ac_state()
    if hvac_mode == "off":
        return
    try:
        requests.post(
            f"{HA_URL}/api/services/climate/turn_off",
            headers=headers,
            json={"entity_id": AC_ENTITY_ID}
        )
    except Exception as e:
        print(f"AC control error: {e}")


def control_ac_setpoint(target_temp, mode="cool"):
    try:
        if mode not in ["cool", "dry"]:
            mode = "cool"
        requests.post(
            f"{HA_URL}/api/services/climate/set_hvac_mode",
            headers=headers,
            json={"entity_id": AC_ENTITY_ID, "hvac_mode": mode}
        )
        time.sleep(2)
        requests.post(
            f"{HA_URL}/api/services/climate/set_temperature",
            headers=headers,
            json={"entity_id": AC_ENTITY_ID, "temperature": target_temp}
        )
    except Exception as e:
        print(f"AC setpoint control error: {e}")


def set_ac_mode(mode: str):
    try:
        requests.post(
            f"{HA_URL}/api/services/climate/set_hvac_mode",
            headers=headers,
            json={"entity_id": AC_ENTITY_ID, "hvac_mode": mode}
        )
        time.sleep(1)
    except Exception as e:
        print(f"AC mode control error: {e}")


def get_current_ac_state():
    try:
        resp = requests.get(f"{HA_URL}/api/states/{AC_ENTITY_ID}", headers=headers).json()
        hvac_mode = resp["state"]
        current_temp = resp["attributes"].get("temperature")
        return hvac_mode, current_temp
    except Exception as e:
        print(f"Failed to retrieve AC state: {e}")
        return "unavailable", None


def should_update_ac(hvac_mode, current_temp, target_temp):
    if hvac_mode != "cool":
        return True
    if current_temp is None:
        return True
    return round(current_temp, 1) != round(target_temp, 1)


# Lighting control
light_schedule_thread = None


def execute_light_schedule(schedule):
    global light_schedule_thread

    def run_schedule():
        print(f"Starting rhythmic lighting sequence ({len(schedule)} steps)")
        for step in schedule:
            set_light_params(step.get("params", {}))
            time.sleep(step.get("duration", 10))
        print("Rhythmic lighting sequence completed")

    if light_schedule_thread is None or not light_schedule_thread.is_alive():
        light_schedule_thread = threading.Thread(target=run_schedule, daemon=True)
        light_schedule_thread.start()
    else:
        print("Previous lighting sequence still running — skipping")


def set_light_params(params: dict):
    brightness = None
    kelvin = None

    for key, value in params.items():
        if key == "light.on":
            url = (f"{HA_URL}/api/services/light/turn_on" if value
                   else f"{HA_URL}/api/services/light/turn_off")
            requests.post(url, headers=headers, json={"entity_id": LIGHT_ENTITY_ID})

        elif key == "light.brightness":
            brightness = int(value)

        elif key == "light.color_temperature":
            kelvin = int(value)

        elif key.startswith("yl_light."):
            param = key.replace("yl_light.", "")
            ent = f"number.yeelink_lamp22_4997__{param}"
            requests.post(
                f"{HA_URL}/api/services/number/set_value",
                headers=headers,
                json={"entity_id": ent, "value": float(value)}
            )
        else:
            print(f"Unsupported lighting control field: {key}")

    if brightness == 0:
        requests.post(
            f"{HA_URL}/api/services/light/turn_off",
            headers=headers,
            json={"entity_id": LIGHT_ENTITY_ID}
        )
    elif brightness is not None or kelvin is not None:
        data = {"entity_id": LIGHT_ENTITY_ID, "transition": 1}
        if brightness is not None:
            data["brightness_pct"] = brightness
        if kelvin is not None:
            mired = max(153, min(int(1000000 / kelvin), 500))
            data["color_temp"] = mired
        requests.post(f"{HA_URL}/api/services/light/turn_on", headers=headers, json=data)


def handle_user_input(sentence):
    global USER_GOAL, last_user_intent, last_intent_time
    if not sentence:
        return
    try:
        last_user_intent = sentence
        last_intent_time = time.time()
        state = get_current_state()
        USER_GOAL = llm_goal(sentence, state)
        USER_GOAL["response_ts"] = time.time()
        print(USER_GOAL.get("explanation", ""))

        apply_constraints(USER_GOAL)

        if isinstance(USER_GOAL.get("light_schedule"), list):
            print("Timed lighting sequence triggered")
            execute_light_schedule(USER_GOAL["light_schedule"])

        apply_device_control(USER_GOAL)
        return USER_GOAL

    except Exception as e:
        print(f"LLM call failed: {e}")


# State readers
def get_current_light_state():
    try:
        resp = requests.get(f"{HA_URL}/api/states/{LIGHT_ENTITY_ID}", headers=headers).json()
        is_on = resp["state"] == "on"
        attrs = resp.get("attributes", {})
        brightness = attrs.get("brightness")          # 0-255
        color_temp = attrs.get("color_temp")          # mired
        kelvin = int(1000000 / color_temp) if color_temp else None
        brightness_pct = int(brightness / 255 * 100) if brightness is not None else None
        return {
            "light_on": is_on,
            "light_brightness_pct": brightness_pct,
            "light_color_temperature_k": kelvin
        }
    except Exception as e:
        print(f"Failed to get light state: {e}")
        return {"light_on": None, "light_brightness_pct": None, "light_color_temperature_k": None}


def get_current_fan_state():
    try:
        fan_resp   = requests.get(f"{HA_URL}/api/states/{FAN_ENTITY_ID}", headers=headers).json()
        speed_resp = requests.get(f"{HA_URL}/api/states/{FAN_SPEED_LEVEL_ENTITY}", headers=headers).json()
        swing_resp = requests.get(f"{HA_URL}/api/states/{FAN_SWING_ENTITY_ID}", headers=headers).json()
        return {
            "fan_on":        fan_resp.get("state") == "on",
            "fan_pct":       int(float(speed_resp.get("state", 0))),
            "fan_swing_mode": swing_resp.get("state") == "on"
        }
    except Exception as e:
        print(f"Failed to get fan state: {e}")
        return {"fan_on": None, "fan_pct": None, "fan_swing_mode": None}


def get_current_purifier_state():
    try:
        resp       = requests.get(f"{HA_URL}/api/states/{PURIFIER_ONOFF_ENTITY_ID}", headers=headers).json()
        level_resp = requests.get(f"{HA_URL}/api/states/{PURIFIER_LEVEL_ID}", headers=headers).json()
        return {
            "purifier_on":    resp["state"] == "on",
            "purifier_level": int(float(level_resp["state"]))
        }
    except Exception as e:
        print(f"Failed to get purifier state: {e}")
        return {"purifier_on": None, "purifier_level": None}


def apply_constraints(USER_GOAL):
    if "constraints" not in USER_GOAL:
        return
    light_related = {
        k: v for k, v in USER_GOAL["constraints"].items()
        if k.startswith("light.") or k.startswith("yl_light.")
    }
    if USER_GOAL.get("light_schedule"):
        pass  # one-time set skipped; schedule takes over
    elif light_related:
        set_light_params(light_related)


# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected")
        for topic in [
            TOPIC_ENV_TEMP, TOPIC_SKIN_TEMP, TOPIC_LIGHT_NOISE, TOPIC_NOISE_LEVEL,
            TOPIC_CO2, TOPIC_HUMIDITY, TOPIC_PM25, TOPIC_TVOC, TOPIC_OUTTEMP,
            TOPIC_OUTHUMID, TOPIC_AC_POWER, TOPIC_FAN_POWER, TOPIC_LIGHT_POWER,
            TOPIC_PURIFIER_POWER,
        ]:
            client.subscribe(topic)
    else:
        print(f"MQTT connection failed: rc={rc}")


def on_message(client, userdata, msg):
    global (latest_env_temp, latest_skin_temp, latest_lux, latest_noise,
            latest_humidity, latest_CO2, latest_PM25, latest_TVOC,
            latest_OUTHUMID, latest_OUTTEMP, latest_ac_power, latest_fan_power,
            latest_light_power, latest_purifier_power)
    try:
        value = float(msg.payload.decode())
        topic_map = {
            TOPIC_ENV_TEMP:       "latest_env_temp",
            TOPIC_SKIN_TEMP:      "latest_skin_temp",
            TOPIC_LIGHT_NOISE:    "latest_lux",
            TOPIC_NOISE_LEVEL:    "latest_noise",
            TOPIC_HUMIDITY:       "latest_humidity",
            TOPIC_CO2:            "latest_CO2",
            TOPIC_PM25:           "latest_PM25",
            TOPIC_TVOC:           "latest_TVOC",
            TOPIC_OUTHUMID:       "latest_OUTHUMID",
            TOPIC_OUTTEMP:        "latest_OUTTEMP",
            TOPIC_FAN_POWER:      "latest_fan_power",
            TOPIC_LIGHT_POWER:    "latest_light_power",
            TOPIC_PURIFIER_POWER: "latest_purifier_power",
            TOPIC_AC_POWER:       "latest_ac_power",
        }
        var = topic_map.get(msg.topic)
        if var:
            globals()[var] = value
    except Exception as e:
        print(f"Message parsing error: {e}")


mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()


def get_state_value(entity_id):
    try:
        resp = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=headers).json()
        return resp.get("state", None)
    except Exception:
        return None


def get_current_state():
    hvac_mode, ac_set_temp = get_current_ac_state()
    light_state    = get_current_light_state()
    fan_state      = get_current_fan_state()
    purifier_state = get_current_purifier_state()
    return {
        "T_air":              latest_env_temp,
        "T_skin":             latest_skin_temp,
        "lux":                latest_lux,
        "noise_db":           latest_noise,
        "humidity":           latest_humidity,
        "CO2":                latest_CO2,
        "PM25":               latest_PM25,
        "TVOC":               latest_TVOC,
        "OUTHUMID":           latest_OUTHUMID,
        "OUTTEMP":            latest_OUTTEMP,
        "fan_on":             fan_state["fan_on"],
        "fan_pct":            fan_state["fan_pct"],
        "fan_swing_mode":     fan_state.get("fan_swing_mode"),
        "fan_available":      get_state_value(FAN_ENTITY_ID) is not None,
        "ac_on":              hvac_mode != "off",
        "ac_mode":            hvac_mode,
        "ac_set_temperature": ac_set_temp,
        "ac_available":       hvac_mode != "unavailable",
        "light_on":           light_state["light_on"],
        "light_brightness_pct":      light_state["light_brightness_pct"],
        "light_color_temperature_k": light_state["light_color_temperature_k"],
        "light_available":    get_state_value(LIGHT_ENTITY_ID) is not None,
        "purifier_on":        purifier_state["purifier_on"],
        "purifier_level":     purifier_state["purifier_level"],
        "purifier_available": get_state_value(PURIFIER_ONOFF_ENTITY_ID) is not None,
        "fan_power":          latest_fan_power,
        "light_power":        latest_light_power,
        "purifier_power":     latest_purifier_power,
        "ac_power":           latest_ac_power,
        "recent_user_intent": last_user_intent if time.time() - last_intent_time < 60 else "None",
        "recent_device_goal": USER_GOAL.get("constraints", {}),
        "outdoor_wind":       get_state_value("sensor.feng_su"),
        "rain_1h":            get_state_value("sensor.xiao_shi_jiang_shui_liang"),
        "air_quality":        get_state_value("sensor.zong_he_kong_qi_zhi_liang"),
        "weather_desc":       get_state_value("sensor.tian_qi_miao_shu"),
    }


def apply_device_control(USER_GOAL):
    global ac_on, fan_current_pct, purifier_on, purifier_level_current

    constraints = USER_GOAL.get("constraints", {})

    fan_on_field = constraints.get("fan_on", None)
    fan_pct = (constraints["fan_speed_pct"] if "fan_speed_pct" in constraints
               else (fan_current_pct if fan_on_field is True and fan_current_pct > 0 else 0))

    ac_on_field       = constraints.get("ac_on", None)
    ac_temp           = constraints.get("ac_temperature", None)
    purifier_on_field = constraints.get("purifier_on", None)
    purifier_level    = constraints.get("purifier_level", -1)

    DEFAULT_AC_TEMP = 27.0
    hvac_mode, current_temp = get_current_ac_state()
    ac_on = False

    if ac_on_field is True:
        effective_temp = ac_temp if isinstance(ac_temp, (int, float)) else DEFAULT_AC_TEMP
        ac_mode_str = constraints.get("ac_mode", "cool")
        if should_update_ac(hvac_mode, current_temp, effective_temp):
            control_ac_setpoint(effective_temp, mode=ac_mode_str)
        ac_on = True
    elif ac_on_field is False:
        turn_off_ac()

    if "fan_on" in constraints or "fan_speed_pct" in constraints:
        if fan_on_field is False or fan_pct == 0:
            set_fan_speed(0)
            fan_current_pct = 0
        elif fan_on_field is True or fan_pct > 0:
            set_fan_speed(fan_pct)
            fan_current_pct = fan_pct

    if "fan.swing_mode" in constraints:
        fan_swing = constraints.get("fan.swing_mode")
        if isinstance(fan_swing, str):
            if fan_swing.lower() in ("false", "off", "0"):
                fan_swing = False
            elif fan_swing.lower() in ("true", "on", "1", "horizontal", "vertical", "both"):
                fan_swing = True
            else:
                print(f"Unrecognized fan.swing_mode value: {fan_swing}")
                fan_swing = None
        if isinstance(fan_swing, bool):
            set_fan_swing(fan_swing)

    for btn_id in USER_GOAL.get("button_actions", []):
        press_button(btn_id)

    if "purifier_on" in constraints or "purifier_level" in constraints:
        if purifier_on_field is False or purifier_level == 0:
            set_purifier_power(False)
            purifier_on = False
        else:
            if not purifier_on:
                set_purifier_power(True)
            actual_level = get_current_purifier_state().get("purifier_level")
            if purifier_level > 0 and purifier_level != actual_level:
                set_purifier_speed(purifier_level)
                purifier_level_current = purifier_level
            purifier_on = True

    controlled_keys = list(constraints.keys())
    print(f"[{time.strftime('%H:%M:%S')}] Control fields applied: "
          f"{controlled_keys if controlled_keys else 'none'}")

    state = get_current_state()
    fan_s   = "on"  if state.get("fan_on")      else "off"
    ac_s    = "on"  if state.get("ac_on")        else "off"
    pur_s   = "on"  if state.get("purifier_on")  else "off"
    light_s = "on"  if state.get("light_on")     else "off"
    t_set   = (f"{state.get('ac_set_temperature')}C" if ac_s == "on" and
               state.get("ac_set_temperature") is not None else "--")
    print(
        f"  fan={fan_s} {state.get('fan_pct', '--')}%  "
        f"ac={ac_s} T_set={t_set}  "
        f"purifier={pur_s} level={state.get('purifier_level', '--')}  "
        f"light={light_s} {state.get('light_brightness_pct', '--')}% "
        f"{state.get('light_color_temperature_k', '--')}K"
    )


sentinel_gui_callback = None


def sentinel_loop():
    def run():
        global last_env_snapshot
        print("Sentinel activated — checking every hour")
        while True:
            try:
                current_state = get_current_state()
                extended_state = {**current_state, "previous_state": last_env_snapshot or {}}
                result = sentinel_judge(extended_state)
                last_env_snapshot = current_state.copy()

                if sentinel_gui_callback:
                    sentinel_gui_callback(result)
                else:
                    if result.get("should_notify"):
                        issues = result.get("issues", [])
                        if isinstance(issues, list) and issues:
                            for i in issues:
                                print(f"  [{i['issue']}] -> {i['suggestion']}")
                        else:
                            print(f"  {result.get('issue', 'Issue unspecified')}")
                    else:
                        print(f"Sentinel: no alert — {result.get('debug_reason', '')}")

            except Exception as e:
                print(f"Sentinel thread error: {e}")

            print("Sentinel check complete")
            time.sleep(3600)

    threading.Thread(target=run, daemon=True).start()


def is_env_ready():
    return latest_env_temp is not None


def wait_for_env_ready(timeout=15):
    print("Waiting for environment data...")
    start = time.time()
    while time.time() - start < timeout:
        if is_env_ready():
            print("Environment data ready")
            return True
        time.sleep(1)
    print("Timeout: no environment data received")
    return False


thermal_loop_should_stop = False
thermal_loop_thread = None


def start_control_loop():
    global thermal_loop_should_stop, thermal_loop_thread
    mqtt_client.loop_start()
    wait_for_env_ready()

    if thermal_loop_thread is not None and thermal_loop_thread.is_alive():
        thermal_loop_should_stop = True
        thermal_loop_thread.join(timeout=2)

    thermal_loop_should_stop = False
    sentinel_loop()
    print("Control loop started")

    global USER_GOAL, ac_on, fan_current_pct, purifier_on, purifier_level_current, last_status_time
    USER_GOAL = {}
    ac_on = False
    fan_current_pct = 0
    purifier_on = False
    purifier_level_current = 0
    last_status_time = 0

    def loop():
        global last_status_time, thermal_loop_should_stop
        while not thermal_loop_should_stop:
            now = time.time()
            if now - last_status_time >= 15 and latest_env_temp and latest_skin_temp:
                last_status_time = now
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"T_air={latest_env_temp:.1f}C  T_skin={latest_skin_temp:.1f}C  "
                    f"RH={latest_humidity:.1f}%  CO2={latest_CO2}ppm  "
                    f"lux={latest_lux}  noise={latest_noise}dB  "
                    f"PM2.5={latest_PM25}  TVOC={latest_TVOC}  "
                    f"T_out={latest_OUTTEMP}C  RH_out={latest_OUTHUMID}%  "
                    f"P_ac={latest_ac_power}W  P_fan={latest_fan_power}W  "
                    f"P_light={latest_light_power}W  P_purifier={latest_purifier_power}W"
                )
            sentence = poll_sentence()
            if sentence and latest_env_temp is not None:
                handle_user_input(sentence)
            time.sleep(15)

    thermal_loop_thread = threading.Thread(target=loop, daemon=True)
    thermal_loop_thread.start()


def stop_control_loop():
    global thermal_loop_should_stop
    thermal_loop_should_stop = True
