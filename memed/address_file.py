"""
Save / Load address table entries to/from a JSON file (.memed).

File format:
{
  "version": 1,
  "process": "game.exe",          // informational only
  "entries": [
    {
      "address": "0x1234ABCD",
      "description": "Health",
      "vtype": "Int32",
      "frozen": false,
      "freeze_value": null         // last frozen value, null if not frozen
    },
    ...
  ]
}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


FILE_EXT    = ".memed"
FILE_FILTER = [("MemEd Address List", "*.memed"), ("All Files", "*.*")]
FORMAT_VER  = 1


@dataclass
class SavedEntry:
    address: int
    description: str
    vtype: str
    frozen: bool
    freeze_value: object   # None if not frozen


def save(path: str, entries: list[SavedEntry], process_name: str = "") -> None:
    data = {
        "version": FORMAT_VER,
        "process": process_name,
        "entries": [
            {
                "address":     hex(e.address),
                "description": e.description,
                "vtype":       e.vtype,
                "frozen":      e.frozen,
                "freeze_value": e.freeze_value,
            }
            for e in entries
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load(path: str) -> tuple[list[SavedEntry], str]:
    """Returns (entries, process_name). Raises ValueError on bad format."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or data.get("version") != FORMAT_VER:
        raise ValueError("Unsupported or invalid .memed file format.")

    entries = []
    for item in data.get("entries", []):
        try:
            addr = int(item["address"], 16)
        except (ValueError, KeyError):
            continue
        entries.append(SavedEntry(
            address=addr,
            description=item.get("description", ""),
            vtype=item.get("vtype", "Int32"),
            frozen=bool(item.get("frozen", False)),
            freeze_value=item.get("freeze_value"),
        ))
    return entries, data.get("process", "")
