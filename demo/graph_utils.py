# graph_utils.py
import os
from rdflib import Graph
from rdflib import URIRef, Literal
from rdflib.namespace import RDF, XSD
import datetime, time

KG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontology", "all_in_one.ttl")
NS      = "http://example.com/kg#"

_g = Graph()
_g.parse(KG_PATH, format="turtle")

CURRENT_USERS_IN_ROOM = {"Office": set()}

def room_exists(room_name: str) -> bool:
    q = f"""PREFIX : <{NS}>
            ASK {{ ?r a :Room ; :hasName "{room_name}" . }}"""
    return bool(_g.query(q))

def devices_in_room(room_name: str) -> list[dict]:
    q = f"""
    PREFIX : <{NS}>
    SELECT ?device ?name ?typical ?min ?max WHERE {{
        ?r a :Room ; :hasName "{room_name}" ; :hasDevice ?device .
        ?device :hasName ?name .
        OPTIONAL {{ ?device :typicalPower ?typical . }}
        OPTIONAL {{ ?device :minPower ?min . }}
        OPTIONAL {{ ?device :maxPower ?max . }}
    }}
    """
    result = []
    for row in _g.query(q):
        result.append({
            "device_id": str(row.device).split("#")[-1],
            "name": str(row.name),
            "typical": float(row.typical) if row.typical else None,
            "min": float(row.min) if row.min else None,
            "max": float(row.max) if row.max else None
        })
    return result

def get_user_pref_ts(user_name: str) -> float | None:
    q = f"""
    PREFIX : <{NS}>
    SELECT ?ts WHERE {{
        ?u a :User ; :hasName "{user_name}" ; :prefersTS ?ts .
    }} LIMIT 1
    """
    rows = list(_g.query(q))
    return float(rows[0].ts) if rows else None

def get_room_power_summary(room_name: str) -> str:
    q = f"""
    PREFIX : <{NS}>
    SELECT ?dname ?min ?max ?typ WHERE {{
      ?room a :Room ; :hasName "{room_name}" ; :hasDevice ?dev .
      OPTIONAL {{ ?dev :hasName ?dname . }}
      OPTIONAL {{ ?dev :minPower ?min . }}
      OPTIONAL {{ ?dev :maxPower ?max . }}
      OPTIONAL {{ ?dev :typicalPower ?typ . }}
    }}
    """
    result = []
    for row in _g.query(q):
        dname = str(row.dname) if row.dname else "Unknown Device"
        typ = f"{float(row.typ):.0f}" if row.typ else "Unknown"
        min_p = f"{float(row.min):.0f}" if row.min else "?"
        max_p = f"{float(row.max):.0f}" if row.max else "?"
        line = f"- {dname}: Typical Power {typ}W, Range {min_p}–{max_p}W"
        result.append(line)
    return "\n".join(result)


def users_in_room(room_name: str) -> list[dict]:
    names = CURRENT_USERS_IN_ROOM.get(room_name, set())
    if not names:
        return []

    results = []
    for name in names:
        q = f"""
        PREFIX : <{NS}>
        SELECT ?user ?name ?gender ?age ?ts ?conditions ?height ?weight WHERE {{
            ?user a :User ; :hasName ?name .
            OPTIONAL {{ ?user :gender ?gender . }}
            OPTIONAL {{ ?user :age ?age . }}
            OPTIONAL {{ ?user :prefersTS ?ts . }}
            OPTIONAL {{ ?user :hasConditionText ?conditions . }}
            OPTIONAL {{ ?user :heightCm ?height . }}
            OPTIONAL {{ ?user :weightKg ?weight . }}
            FILTER(?name = "{name}")
        }}
        """
        for row in _g.query(q):
            results.append({
                "name": str(row.name),
                "gender": str(row.gender) if row.gender else None,
                "age": int(row.age) if row.age else None,
                "prefersTS": float(row.ts) if row.ts else None,
                "height": int(row.height) if row.height else None,
                "weight": int(row.weight) if row.weight else None,
                "conditions": str(row.conditions).split(",") if row.conditions else []
            })
    return results

def record_entry_event(user_name: str, room_name: str = "Office"):
    user_uri = None
    room_uri = None
    q_user = f"""PREFIX : <{NS}> SELECT ?u WHERE {{ ?u a :User ; :hasName "{user_name}" . }}"""
    q_room = f"""PREFIX : <{NS}> SELECT ?r WHERE {{ ?r a :Room ; :hasName "{room_name}" . }}"""
    for r in _g.query(q_user): user_uri = r[0]
    for r in _g.query(q_room): room_uri = r[0]
    if not user_uri or not room_uri:
        print(f"User or room not found in knowledge graph: {user_name}, {room_name}")
        return

    now = datetime.datetime.now().isoformat()
    eid = f"Entry_{int(time.time())}"
    event_uri = URIRef(NS + eid)
    _g.add((event_uri, RDF.type, URIRef(NS + "EntryEvent")))
    _g.add((event_uri, URIRef(NS + "atTime"), Literal(now, datatype=XSD.dateTime)))
    _g.add((event_uri, URIRef(NS + "triggeredBy"), user_uri))
    _g.add((event_uri, URIRef(NS + "enteredRoom"), room_uri))
    print(f"EntryEvent recorded: {user_name} entered {room_name} at {now}")

    with open("entry_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{now} | {user_name} entered {room_name}\n")
    CURRENT_USERS_IN_ROOM.setdefault(room_name, set()).add(user_name)

def record_exit_event(user_name: str, room_name: str = "Office"):
    user_uri = None
    room_uri = None
    q_user = f"""PREFIX : <{NS}> SELECT ?u WHERE {{ ?u a :User ; :hasName "{user_name}" . }}"""
    q_room = f"""PREFIX : <{NS}> SELECT ?r WHERE {{ ?r a :Room ; :hasName "{room_name}" . }}"""
    for r in _g.query(q_user): user_uri = r[0]
    for r in _g.query(q_room): room_uri = r[0]
    if not user_uri or not room_uri:
        print(f"User or room not found in knowledge graph: {user_name}, {room_name}")
        return

    now = datetime.datetime.now().isoformat()
    eid = f"Exit_{int(time.time())}"
    event_uri = URIRef(NS + eid)
    _g.add((event_uri, RDF.type, URIRef(NS + "ExitEvent")))
    _g.add((event_uri, URIRef(NS + "atTime"), Literal(now, datatype=XSD.dateTime)))
    _g.add((event_uri, URIRef(NS + "triggeredBy"), user_uri))
    _g.add((event_uri, URIRef(NS + "leftRoom"), room_uri))
    print(f"ExitEvent recorded: {user_name} left {room_name} at {now}")

    with open("entry_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{now} | {user_name} left {room_name}\n")
    CURRENT_USERS_IN_ROOM.setdefault(room_name, set()).discard(user_name)
