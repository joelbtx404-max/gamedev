import json
import os
from typing import Dict, List, Tuple

import requests
from agents import function_tool


_POKEAPI_BASE = os.getenv("POKEAPI_BASE_URL", "https://pokeapi.co/api/v2")
_stats_cache: Dict[str, Dict[str, int]] = {}
_pokemon_cache: Dict[str, Dict] = {}
_move_cache: Dict[str, Dict] = {}
_type_cache: Dict[str, Dict] = {}
_ability_cache: Dict[str, Dict] = {}


def _fetch_single_pokemon_stats(name: str) -> Tuple[Dict[str, int] | None, str | None]:
    """Fetch base stats for a single Pokémon by name using PokeAPI.

    Returns (stats_dict, error). stats_dict maps stat name -> base_stat.
    """
    key = name.strip().lower()
    if not key:
        return None, "empty name"

    if key in _stats_cache:
        return _stats_cache[key], None

    url = f"{_POKEAPI_BASE}/pokemon/{key}/"
    try:
        resp = requests.get(url, timeout=10)
    except Exception as exc:
        return None, f"request_error: {exc}"

    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"

    try:
        data = resp.json()
        stats_list = data.get("stats", [])
        stats: Dict[str, int] = {}
        for s in stats_list:
            stat_info = s.get("stat") or {}
            stat_name = stat_info.get("name")
            base_val = s.get("base_stat")
            if isinstance(stat_name, str) and isinstance(base_val, int):
                stats[stat_name] = base_val
        if stats:
            _stats_cache[key] = stats
            return stats, None
        return None, "no_stats"
    except Exception as exc:  # JSON parsing or structure issues
        return None, f"parse_error: {exc}"


def fetch_pokemon_stats_sync(pokemon_names: List[str]) -> Dict[str, Dict[str, int] | Dict[str, str]]:
    """Batch fetch stats for provided Pokémon names.

    Returns mapping name -> stats dict, or {"error": reason} on failure.
    """
    result: Dict[str, Dict[str, int] | Dict[str, str]] = {}
    for raw in pokemon_names or []:
        name = (raw or "").strip()
        if not name:
            continue
        stats, err = _fetch_single_pokemon_stats(name)
        if stats is not None:
            result[name] = stats
        else:
            result[name] = {"error": err or "unknown_error"}
    return result


@function_tool
def fetch_pokemon_stats(pokemon_names: List[str]) -> str:
    """Fetch base stats for the given Pokémon names from PokéAPI.

    Args:
        pokemon_names: List of Pokémon names (e.g., ["tepig", "patrat"]).

    Returns:
        JSON string mapping name -> { stat_name: base_stat } or {"error": reason}.
    """
    data = fetch_pokemon_stats_sync(pokemon_names)
    return json.dumps(data)


def _get_json(url: str) -> Tuple[Dict | None, str | None]:
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


@function_tool
def fetch_pokemon_core(pokemon_name: str) -> str:
    """Fetch core Pokémon data: base stats, types, abilities, moves (names only).

    Args:
        pokemon_name: Pokémon name (e.g., "tepig").

    Returns:
        JSON string with: id, name, types, abilities, base_stats, moves (names, possibly truncated).
    """
    key = (pokemon_name or "").strip().lower()
    if not key:
        return json.dumps({"error": "empty name"})
    if key in _pokemon_cache:
        return json.dumps(_pokemon_cache[key])

    url = f"{_POKEAPI_BASE}/pokemon/{key}/"
    data, err = _get_json(url)
    if err or not data:
        return json.dumps({"error": err or "unknown_error"})

    try:
        # Types
        types = [t["type"]["name"] for t in data.get("types", []) if t.get("type")]
        # Abilities
        abilities = [a["ability"]["name"] for a in data.get("abilities", []) if a.get("ability")]
        # Base stats
        stats: Dict[str, int] = {}
        for s in data.get("stats", []) or []:
            stat_info = s.get("stat") or {}
            stat_name = stat_info.get("name")
            base_val = s.get("base_stat")
            if isinstance(stat_name, str) and isinstance(base_val, int):
                stats[stat_name] = base_val
        # Moves (names only, lightly truncated to keep payload small)
        all_moves = []
        for m in data.get("moves", []) or []:
            mv = m.get("move") or {}
            name = mv.get("name")
            if isinstance(name, str):
                all_moves.append(name)
        dedup_moves = list(dict.fromkeys(all_moves))
        limit = 40
        truncated = len(dedup_moves) > limit
        moves = dedup_moves[:limit]

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "types": types,
            "abilities": abilities,
            "base_stats": stats,
            "moves": moves,
        }
        if truncated:
            result["moves_truncated"] = True
            result["moves_total"] = len(dedup_moves)

        _pokemon_cache[key] = result
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": f"extract_error: {exc}"})


@function_tool
def fetch_move_details(move_name: str) -> str:
    """Fetch detailed move data: power, accuracy, pp, priority, type, damage_class, effects (EN).

    Args:
        move_name: Move name (e.g., "tackle").

    Returns:
        JSON string with core fields for the move.
    """
    key = (move_name or "").strip().lower()
    if not key:
        return json.dumps({"error": "empty name"})
    if key in _move_cache:
        return json.dumps(_move_cache[key])

    url = f"{_POKEAPI_BASE}/move/{key}/"
    data, err = _get_json(url)
    if err or not data:
        return json.dumps({"error": err or "unknown_error"})

    try:
        # Pick English effect entry if present
        eff = ""
        short_eff = ""
        for e in data.get("effect_entries", []) or []:
            lang = (e.get("language") or {}).get("name")
            if lang == "en":
                eff = e.get("effect") or eff
                short_eff = e.get("short_effect") or short_eff
                break

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": (data.get("type") or {}).get("name"),
            "damage_class": (data.get("damage_class") or {}).get("name"),
            "power": data.get("power"),
            "accuracy": data.get("accuracy"),
            "pp": data.get("pp"),
            "priority": data.get("priority"),
            "effect": eff,
            "short_effect": short_eff,
        }
        _move_cache[key] = result
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": f"extract_error: {exc}"})


@function_tool
def fetch_type_relations(type_name: str) -> str:
    """Fetch damage relations for a type (double/half/no damage to/from).

    Args:
        type_name: Type name (e.g., "fire").

    Returns:
        JSON string with damage_relations names only.
    """
    key = (type_name or "").strip().lower()
    if not key:
        return json.dumps({"error": "empty name"})
    if key in _type_cache:
        return json.dumps(_type_cache[key])

    url = f"{_POKEAPI_BASE}/type/{key}/"
    data, err = _get_json(url)
    if err or not data:
        return json.dumps({"error": err or "unknown_error"})

    try:
        dr = data.get("damage_relations") or {}
        def names(arr):
            return [x.get("name") for x in (arr or []) if isinstance(x.get("name"), str)]

        result = {
            "name": data.get("name"),
            "damage_relations": {
                "double_damage_to": names(dr.get("double_damage_to")),
                "double_damage_from": names(dr.get("double_damage_from")),
                "half_damage_to": names(dr.get("half_damage_to")),
                "half_damage_from": names(dr.get("half_damage_from")),
                "no_damage_to": names(dr.get("no_damage_to")),
                "no_damage_from": names(dr.get("no_damage_from")),
            },
        }
        _type_cache[key] = result
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": f"extract_error: {exc}"})


@function_tool
def fetch_ability_details(ability_name: str) -> str:
    """Fetch ability details and English effect text.

    Args:
        ability_name: Ability name (e.g., "blaze").

    Returns:
        JSON string with id, name, is_main_series, generation, effects (EN).
    """
    key = (ability_name or "").strip().lower()
    if not key:
        return json.dumps({"error": "empty name"})
    if key in _ability_cache:
        return json.dumps(_ability_cache[key])

    url = f"{_POKEAPI_BASE}/ability/{key}/"
    data, err = _get_json(url)
    if err or not data:
        return json.dumps({"error": err or "unknown_error"})

    try:
        eff = ""
        short_eff = ""
        for e in data.get("effect_entries", []) or []:
            lang = (e.get("language") or {}).get("name")
            if lang == "en":
                eff = e.get("effect") or eff
                short_eff = e.get("short_effect") or short_eff
                break

        result = {
            "id": data.get("id"),
            "name": data.get("name"),
            "is_main_series": data.get("is_main_series"),
            "generation": (data.get("generation") or {}).get("name"),
            "effect": eff,
            "short_effect": short_eff,
        }
        _ability_cache[key] = result
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": f"extract_error: {exc}"})
