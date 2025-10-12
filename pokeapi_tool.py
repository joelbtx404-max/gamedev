import json
import os
from typing import Any, Dict, List, Tuple

import requests
from agents import function_tool

_POKEAPI_BASE = os.getenv("POKEAPI_BASE_URL", "https://pokeapi.co/api/v2")
_pokemon_cache: Dict[str, Dict[str, Any]] = {}
_type_weakness_cache: Dict[str, List[str]] = {}
_latest_pokemon_calls: List[Dict[str, Any]] = []


def _get_json(url: str) -> Tuple[Dict[str, Any] | None, str | None]:
    try:
        resp = requests.get(url, timeout=10)
    except Exception as exc:
        return None, f"request_error: {exc}"
    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"
    try:
        return resp.json(), None
    except Exception as exc:
        return None, f"parse_error: {exc}"


def _normalise_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _record_call(names: List[str], payload: Dict[str, Any]) -> None:
    _latest_pokemon_calls.append({
        "names": names,
        "data": payload,
    })


def _fetch_type_weaknesses(type_name: str) -> List[str]:
    key = _normalise_name(type_name)
    if not key:
        return []

    if key in _type_weakness_cache:
        return _type_weakness_cache[key]

    url = f"{_POKEAPI_BASE}/type/{key}/"
    data, err = _get_json(url)
    if err or not data:
        weaknesses: List[str] = []
    else:
        relations = data.get("damage_relations") or {}
        double_from = relations.get("double_damage_from") or []
        weaknesses = [
            _normalise_name((entry or {}).get("name"))
            for entry in double_from
            if isinstance((entry or {}).get("name"), str)
        ]
        weaknesses = [name for name in dict.fromkeys(weaknesses) if name]

    _type_weakness_cache[key] = weaknesses
    return weaknesses


def _collect_weaknesses(type_names: List[str]) -> List[str]:
    weaknesses: List[str] = []
    for type_name in type_names:
        weaknesses.extend(_fetch_type_weaknesses(type_name))

    ordered_unique = [name for name in dict.fromkeys(weaknesses) if name]
    return ordered_unique


def pull_latest_pokemon_calls() -> List[Dict[str, Any]]:
    """Return and clear the log of recent Pokémon endpoint calls."""
    global _latest_pokemon_calls
    calls = _latest_pokemon_calls
    _latest_pokemon_calls = []
    return calls


@function_tool
def fetch_pokemon_profile(pokemon_name: str) -> str:
    """Fetch Pokémon data (stats, types, abilities, moves) from the PokéAPI Pokémon endpoint.

    Args:
        pokemon_name: Pokémon identifier (name or id).

    Returns:
        JSON string containing the core Pokémon payload with lightweight trimming.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_profile({pokemon_name!r})", flush=True)

    key = _normalise_name(pokemon_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _pokemon_cache:
        cached = _pokemon_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/pokemon/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        types = [t["type"]["name"] for t in data.get("types", []) if t.get("type")]
        abilities = [a["ability"]["name"] for a in data.get("abilities", []) if a.get("ability")]
        stats = {
            (s.get("stat") or {}).get("name", "unknown"): s.get("base_stat")
            for s in data.get("stats", []) or []
            if isinstance(s.get("base_stat"), int)
        }
        height = data.get("height")
        weight = data.get("weight")
        weaknesses = _collect_weaknesses(types)
        moves = []
        for m in data.get("moves", []) or []:
            mv = m.get("move") or {}
            name = mv.get("name")
            if isinstance(name, str):
                moves.append(name)
        dedup_moves = list(dict.fromkeys(moves))
        limited_moves = dedup_moves[:40]

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "types": types,
            "abilities": abilities,
            "base_stats": stats,
            "moves": limited_moves,
            "moves_truncated": len(dedup_moves) > len(limited_moves),
            "height": height,
            "weight": weight,
            "weaknesses": weaknesses,
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _pokemon_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)
