# Full System Implementation

Complete source code for the LLM-based indoor environment control system described in the paper.
This implementation requires a physical smart home setup (Home Assistant, MQTT broker, hardware sensors).

## Directory Structure

```
full/
├── control_free.py              # Main control loop: MQTT sensor ingestion + HA device control
├── llm_client.py                # LLM goal-inference client (GPT-4o, function calling)
├── llm_client_sentinel.py       # Sentinel agent: proactive periodic monitoring
├── prompt_templates_free.py     # System prompt and function schema for the control agent
├── prompt_templates_sentinel.py # System prompt and function schema for the sentinel agent
├── graph_utils.py               # RDF knowledge graph query utilities
├── gui.py                       # Tkinter GUI with voice input (Whisper ASR)
├── test_llm.py                  # Evaluation harness (no hardware required)
├── test_cases.json              # Standardized test case suite (6,864 cases across 7 categories)
└── ontology/
    ├── all_in_one.ttl           # Merged runtime knowledge graph (loaded by graph_utils.py)
    ├── ontology.ttl             # Core OWL schema: classes and properties
    ├── device_param.ttl         # Device capability specifications
    ├── room_device.ttl          # Room–device topology instances
    ├── feedback_data.ttl        # Sample occupant feedback instances
    └── user_profile.ttl        # Anonymized occupant thermal preference profile
```

## Requirements

```
pip install -r requirements.txt
```

Dependencies: `openai`, `rdflib`, `paho-mqtt`, `numpy`, `scipy`, `sounddevice`, `openai-whisper`, `openpyxl`

## Configuration

### Environment variables

```bash
export OPENAI_API_KEY="sk-..."       # OpenAI API key
export HA_TOKEN="eyJ..."             # Home Assistant long-lived access token
```

### Hardware configuration

Edit the constants at the top of `control_free.py` to match your setup:

```python
MQTT_BROKER = "YOUR_MQTT_BROKER_HOST"   # MQTT broker IP or hostname
HA_URL       = "http://homeassistant.local:8123"
```

Device entity IDs are defined in `ontology/room_device.ttl` and referenced by Home Assistant.

## Running

**Full GUI (with voice input):**
```bash
cd full/
python gui.py
```

**Headless control loop:**
```bash
cd full/
python control_free.py
```

**Evaluation harness (no hardware required):**
```bash
cd full/
python test_llm.py --interactive          # enter a sentence manually
python test_llm.py --category sensor_missing  # run one category
python test_llm.py --list                 # show all categories
python test_llm.py                        # run all 6,864 cases (requires API calls)
```

## System Architecture

```
Occupant natural-language request
           ↓
    llm_client.py
    [prompt_templates_free.py]
    [graph_utils.py → ontology/all_in_one.ttl]
           ↓
    Structured device commands
    {ac_on, ac_temperature, fan_speed_pct, light.brightness, ...}
           ↓
    Home Assistant REST API → Physical devices

Parallel: llm_client_sentinel.py (runs hourly)
    → Proactive notification if anomaly detected
```

## Knowledge Graph

The ontology (`ontology/`) follows an OWL/RDF schema:

| File | Contents |
|---|---|
| `ontology.ttl` | Class and property definitions (Room, Device, User, FeedbackEvent) |
| `device_param.ttl` | Device capabilities: AC modes, fan speed range, lighting range, purifier levels |
| `room_device.ttl` | Room instances and device instances with Home Assistant entity IDs |
| `user_profile.ttl` | Occupant profile: anthropometric data, thermal preference offset (ΔTS) |
| `feedback_data.ttl` | Sample occupant feedback (TSV ratings with environmental context) |
| `all_in_one.ttl` | Merged graph used at runtime — regenerate with: `cat ontology/*.ttl user_profile.ttl > all_in_one.ttl` |

## Test Case Categories

| Category | Description |
|---|---|
| `responsiveness` | Direct device control requests |
| `sensor_missing` | Graceful handling of missing sensor data |
| `fault_tolerance` | Handling of out-of-range / anomalous sensor values |
| `device_failure` | Behaviour when a device is unavailable |
| `consistency` | Repeated identical inputs — output stability |
| `semantic_noise` | Paraphrased and distractor-injected inputs |
| `sentinel` | Proactive monitoring scenarios (no user request) |
