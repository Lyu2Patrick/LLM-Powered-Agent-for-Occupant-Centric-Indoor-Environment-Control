# Demo — Try the LLM Environment Control Agent

A self-contained demo that lets you interact with the full LLM control system
**without any smart home hardware**. Only an OpenAI API key is required.

All prompts, knowledge graph queries, and LLM logic are **identical to the full system**.
The only difference: sensor state is manually defined in `demo.py` instead of
being read from live MQTT sensors.

## Setup

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
```

## Usage

**Interactive mode** — type any natural-language request:
```bash
python demo.py
```

**Single request:**
```bash
python demo.py --sentence "I feel a bit warm, can you cool things down?"
```

**With custom sensor state overrides:**
```bash
python demo.py --sentence "The air is stuffy." --state '{"CO2": 1200, "humidity": 80}'
```

**Test the proactive sentinel agent:**
```bash
python demo.py --sentinel --state '{"T_air": 32, "humidity": 88, "CO2": 1500}'
```

**Run the full evaluation harness (same as full/):**
```bash
python test_llm.py --interactive
python test_llm.py --category sensor_missing
python test_llm.py --list
```

## Directory Structure

```
demo/
├── demo.py                      # Entry point: interactive / single-request / sentinel
├── llm_client.py                # Identical to full/
├── llm_client_sentinel.py       # Identical to full/
├── graph_utils.py               # Identical to full/
├── prompt_templates_free.py     # Identical to full/
├── prompt_templates_sentinel.py # Identical to full/
├── test_llm.py                  # Identical to full/
├── test_cases.json              # Identical to full/
├── requirements.txt             # Minimal: openai + rdflib only
└── ontology/
    └── all_in_one.ttl           # Runtime knowledge graph (same as full/)
```

## What differs from the full system

| | Demo | Full system |
|---|---|---|
| Sensor data | Hard-coded defaults in `demo.py` (overridable via `--state`) | Live MQTT sensors |
| Device control | Printed only (no hardware commands) | Home Assistant REST API |
| Voice input | Not included | Whisper ASR in `gui.py` |
| LLM prompts | Identical | Identical |
| Knowledge graph | Identical | Identical |
| Evaluation harness | Identical (`test_llm.py`) | Identical |

## Modifying the default sensor state

Edit `DEFAULT_STATE` in `demo.py` to simulate different environments:

```python
DEFAULT_STATE = {
    "T_air": 26.5,       # Indoor air temperature (°C)
    "humidity": 58.0,    # Relative humidity (%)
    "CO2": 680.0,        # CO₂ concentration (ppm)
    "fan_available": True,
    "ac_available": True,
    # ... (see demo.py for all fields)
}
```
