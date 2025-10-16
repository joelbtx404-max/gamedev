import json
import os
from typing import Any, Dict, List, Tuple

import requests
from agents import function_tool

_POKEAPI_BASE = os.getenv("POKEAPI_BASE_URL", "https://pokeapi.co/api/v2")
_pokemon_cache: Dict[str, Dict[str, Any]] = {}
_type_weakness_cache: Dict[str, List[str]] = {}
_gender_cache: Dict[str, Dict[str, Any]] = {}
_ability_cache: Dict[str, Dict[str, Any]] = {}
_move_cache: Dict[str, Dict[str, Any]] = {}
_type_cache: Dict[str, Dict[str, Any]] = {}
_item_cache: Dict[str, Dict[str, Any]] = {}
_location_cache: Dict[str, Dict[str, Any]] = {}
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


@function_tool
def fetch_pokemon_gender(pokemon_name: str) -> str:
    """Fetch Pokémon gender ratio data from the PokéAPI species endpoint.

    Args:
        pokemon_name: Pokémon identifier (name or id).

    Returns:
        JSON string containing gender ratio information.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_gender({pokemon_name!r})", flush=True)

    key = _normalise_name(pokemon_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _gender_cache:
        cached = _gender_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    # First get the species data
    url = f"{_POKEAPI_BASE}/pokemon-species/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        gender_rate = data.get("gender_rate")
        if gender_rate == -1:
            gender_info = "genderless"
        else:
            # Gender rate is 0-8, where 0 = 100% male, 8 = 100% female
            female_percentage = (gender_rate / 8) * 100
            male_percentage = 100 - female_percentage
            gender_info = f"{male_percentage:.1f}% male, {female_percentage:.1f}% female"

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "gender_rate": gender_rate,
            "gender_info": gender_info,
            "is_genderless": gender_rate == -1,
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _gender_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)


@function_tool
def fetch_pokemon_abilities(ability_name: str) -> str:
    """Fetch detailed ability information from the PokéAPI ability endpoint.

    Args:
        ability_name: Ability identifier (name or id).

    Returns:
        JSON string containing detailed ability information.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_abilities({ability_name!r})", flush=True)

    key = _normalise_name(ability_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _ability_cache:
        cached = _ability_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/ability/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        # Get English description
        effect_entries = data.get("effect_entries", [])
        description = "No description available"
        for entry in effect_entries:
            if entry.get("language", {}).get("name") == "en":
                description = entry.get("effect", "No description available")
                break

        # Get short description
        short_effect = "No short description available"
        for entry in effect_entries:
            if entry.get("language", {}).get("name") == "en":
                short_effect = entry.get("short_effect", "No short description available")
                break

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": description,
            "short_effect": short_effect,
            "is_main_series": data.get("is_main_series", False),
            "generation": data.get("generation", {}).get("name", "unknown"),
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _ability_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)


@function_tool
def fetch_pokemon_moves(move_name: str) -> str:
    """Fetch detailed move information from the PokéAPI move endpoint.

    Args:
        move_name: Move identifier (name or id).

    Returns:
        JSON string containing detailed move information.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_moves({move_name!r})", flush=True)

    key = _normalise_name(move_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _move_cache:
        cached = _move_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/move/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        # Get English description
        effect_entries = data.get("effect_entries", [])
        description = "No description available"
        for entry in effect_entries:
            if entry.get("language", {}).get("name") == "en":
                description = entry.get("effect", "No description available")
                break

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": description,
            "type": data.get("type", {}).get("name", "unknown"),
            "power": data.get("power"),
            "accuracy": data.get("accuracy"),
            "pp": data.get("pp"),
            "priority": data.get("priority"),
            "damage_class": data.get("damage_class", {}).get("name", "unknown"),
            "generation": data.get("generation", {}).get("name", "unknown"),
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _move_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)


@function_tool
def fetch_pokemon_types(type_name: str) -> str:
    """Fetch detailed type information and effectiveness from the PokéAPI type endpoint.

    Args:
        type_name: Type identifier (name or id).

    Returns:
        JSON string containing type effectiveness and weaknesses.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_types({type_name!r})", flush=True)

    key = _normalise_name(type_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _type_cache:
        cached = _type_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/type/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        damage_relations = data.get("damage_relations", {})
        
        # Extract effectiveness data
        double_damage_to = [entry["name"] for entry in damage_relations.get("double_damage_to", [])]
        half_damage_to = [entry["name"] for entry in damage_relations.get("half_damage_to", [])]
        no_damage_to = [entry["name"] for entry in damage_relations.get("no_damage_to", [])]
        
        double_damage_from = [entry["name"] for entry in damage_relations.get("double_damage_from", [])]
        half_damage_from = [entry["name"] for entry in damage_relations.get("half_damage_from", [])]
        no_damage_from = [entry["name"] for entry in damage_relations.get("no_damage_from", [])]

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "generation": data.get("generation", {}).get("name", "unknown"),
            "effectiveness": {
                "double_damage_to": double_damage_to,
                "half_damage_to": half_damage_to,
                "no_damage_to": no_damage_to,
                "double_damage_from": double_damage_from,
                "half_damage_from": half_damage_from,
                "no_damage_from": no_damage_from,
            }
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _type_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)


@function_tool
def fetch_pokemon_items(item_name: str) -> str:
    """Fetch item information from the PokéAPI item endpoint.

    Args:
        item_name: Item identifier (name or id).

    Returns:
        JSON string containing item information.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_items({item_name!r})", flush=True)

    key = _normalise_name(item_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _item_cache:
        cached = _item_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/item/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        # Get English description
        effect_entries = data.get("effect_entries", [])
        description = "No description available"
        for entry in effect_entries:
            if entry.get("language", {}).get("name") == "en":
                description = entry.get("effect", "No description available")
                break

        # Get short description
        flavor_text_entries = data.get("flavor_text_entries", [])
        short_description = "No short description available"
        for entry in flavor_text_entries:
            if entry.get("language", {}).get("name") == "en":
                short_description = entry.get("text", "No short description available")
                break

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": description,
            "short_description": short_description,
            "cost": data.get("cost"),
            "category": data.get("category", {}).get("name", "unknown"),
            "generation": data.get("generation", {}).get("name", "unknown"),
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _item_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)


@function_tool
def fetch_pokemon_locations(location_name: str) -> str:
    """Fetch location information from the PokéAPI location endpoint.

    Args:
        location_name: Location identifier (name or id).

    Returns:
        JSON string containing location information.
    """
    if os.getenv("POKEAPI_TOOL_DEBUG") == "1":
        print(f"[POKEAPI_TOOL] fetch_pokemon_locations({location_name!r})", flush=True)

    key = _normalise_name(location_name)
    if not key:
        return json.dumps({"error": "empty name"})

    if key in _location_cache:
        cached = _location_cache[key]
        _record_call([key], cached)
        return json.dumps(cached)

    url = f"{_POKEAPI_BASE}/location/{key}/"
    data, err = _get_json(url)
    if err or not data:
        payload = {"error": err or "unknown_error"}
        _record_call([key], payload)
        return json.dumps(payload)

    try:
        # Get region information
        region = data.get("region", {})
        region_name = region.get("name", "unknown") if region else "unknown"

        # Get area names
        areas = []
        for area in data.get("areas", []):
            areas.append(area.get("name", "unknown"))

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "region": region_name,
            "areas": areas,
            "generation": data.get("generation", {}).get("name", "unknown"),
        }
    except Exception as exc:
        result = {"error": f"extract_error: {exc}"}

    _location_cache[key] = result
    _record_call([key], result)
    return json.dumps(result)
