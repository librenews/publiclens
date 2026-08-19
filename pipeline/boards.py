"""
Board registry — maps board names to Granicus view_ids.
"""

BOARDS = {
    "Board of Finance": {
        "view_id": "4",
        "short_name": "BOF",
        "color": "#6366f1",  # indigo
    },
    "Board of Representatives": {
        "view_id": "14",
        "short_name": "BOR",
        "color": "#f59e0b",  # amber
    },
    "Board of Education": {
        "view_id": "3",
        "short_name": "BOE",
        "color": "#10b981",  # emerald
    },
    "Zoning Board": {
        "view_id": "8",
        "short_name": "ZB",
        "color": "#ef4444",  # red
    },
    "Planning Board": {
        "view_id": "20",
        "short_name": "PB",
        "color": "#8b5cf6",  # violet
    },
}


def get_board_by_view_id(view_id: str) -> dict | None:
    """Look up a board by its Granicus view_id."""
    for name, info in BOARDS.items():
        if info["view_id"] == view_id:
            return {"name": name, **info}
    return None


def get_board_by_short_name(short_name: str) -> dict | None:
    """Look up a board by its short name (BOF, BOR, etc.)."""
    for name, info in BOARDS.items():
        if info["short_name"].upper() == short_name.upper():
            return {"name": name, **info}
    return None
