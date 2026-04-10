# LLM-Based Personalized Indoor Environment Control

Source code and supplementary material for:

> **"LLM-Powered Agent for Occupant-Centric Indoor Environment Control: Design, Implementation, and Evaluation"**

---

## Repository Structure

```
llm-env-control/
│
├── full/          Complete system implementation (requires hardware)
└── demo/          Standalone demo (OpenAI API key only, no hardware)
```

---

## Quick Start — No Hardware Required

```bash
cd demo/
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
python demo.py
```

See [demo/README.md](demo/README.md) for details and usage examples.

---

## Full System

The `full/` directory contains the complete implementation used in the paper:

| File | Description |
|---|---|
| `control_free.py` | Main control loop — MQTT sensor ingestion + Home Assistant device commands |
| `llm_client.py` | LLM goal-inference client (GPT-4o with function calling) |
| `llm_client_sentinel.py` | Sentinel agent — proactive hourly monitoring |
| `prompt_templates_free.py` | System prompt and function schema for the control agent |
| `prompt_templates_sentinel.py` | System prompt and function schema for the sentinel agent |
| `graph_utils.py` | RDF knowledge graph query utilities |
| `gui.py` | Tkinter GUI with voice input (Whisper ASR) |
| `test_llm.py` | Evaluation harness — runs test cases without hardware |
| `test_cases.json` | 6,864 standardized test cases across 7 evaluation categories |
| `ontology/` | OWL/RDF knowledge graph (schema, device specs, room topology, user profile) |

See [full/README.md](full/README.md) for setup, configuration, and running instructions.

---

## System Overview

```
Occupant natural-language request
           ↓
    LLM client (GPT-4o)
    + Knowledge Graph (OWL/RDF ontology)
    + Real-time sensor state
           ↓
    Structured device commands
    {ac_on, ac_temperature, fan_speed_pct, light.brightness, ...}
           ↓
    Home Assistant REST API → Physical devices

Parallel — Sentinel Agent (hourly):
    Proactive notification if comfort/air quality anomaly detected
```

---

## Citation

```
J. Lyu, D. Lai, H. Zhang, Z. Lian, LLM-Powered Agent for Occupant-Centric Indoor Environment Control: Design, Implementation, and Evaluation, Energy and Built Environment (2026). https://doi.org/10.1016/j.enbenv.2026.04.001.
```

---

## License

MIT License.
