"""
PublicLens Chat Server

Flask app that serves the chat UI and provides API endpoints
for meeting data and chat interactions. Supports multiple boards
and meetings.
"""

import json
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.rag import chat, load_meeting_data
from pipeline.indexer import search_across_meetings, format_timestamp
from pipeline.boards import BOARDS, get_board_by_view_id

app = Flask(__name__, static_folder="static")
CORS(app)

DATA_DIR = Path(__file__).parent.parent / "data"


@app.route("/")
def index():
    """Serve the chat UI."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/boards")
def get_boards():
    """Return list of boards with their processed meeting counts."""
    boards = []
    for name, info in BOARDS.items():
        # Count how many meetings from this board are processed
        processed = 0
        for meta_file in DATA_DIR.glob("meeting_*.json"):
            with open(meta_file) as f:
                m = json.load(f)
            if m.get("view_id") == info["view_id"]:
                clip_id = m.get("clip_id", "")
                if (DATA_DIR / "index" / f"{clip_id}.faiss").exists():
                    processed += 1

        if processed > 0:
            boards.append({
                "name": name,
                "short_name": info["short_name"],
                "view_id": info["view_id"],
                "color": info["color"],
                "processed_count": processed,
            })

    return jsonify(boards)


@app.route("/api/meeting")
def get_meeting():
    """Return meeting metadata and summary for a specific clip_id."""
    clip_id = request.args.get("clip_id")
    if not clip_id:
        return jsonify({"error": "No clip_id specified"}), 400

    data = load_meeting_data(clip_id)
    return jsonify(data)


@app.route("/api/meetings")
def list_meetings():
    """List all processed meetings, optionally filtered by view_id."""
    view_id_filter = request.args.get("view_id")
    meetings = []

    for meta_file in sorted(DATA_DIR.glob("meeting_*.json"), reverse=True):
        with open(meta_file) as f:
            meeting = json.load(f)

        # Filter by view_id if specified
        if view_id_filter and meeting.get("view_id") != view_id_filter:
            continue

        clip_id = meeting.get("clip_id", meta_file.stem.replace("meeting_", ""))

        # Check what data is available
        has_transcript = (DATA_DIR / "transcripts" / f"{clip_id}.json").exists()
        has_summary = (DATA_DIR / "summaries" / f"{clip_id}.json").exists()
        has_index = (DATA_DIR / "index" / f"{clip_id}.faiss").exists()

        ready = has_transcript and has_summary and has_index
        if not ready:
            continue

        # Get board info
        board_info = get_board_by_view_id(meeting.get("view_id", ""))

        meetings.append({
            **meeting,
            "has_transcript": has_transcript,
            "has_summary": has_summary,
            "has_index": has_index,
            "ready": ready,
            "board_name": board_info["name"] if board_info else "Unknown",
            "board_short_name": board_info["short_name"] if board_info else "?",
            "board_color": board_info["color"] if board_info else "#666",
        })

    # Sort by date_unix descending (newest first)
    meetings.sort(key=lambda m: m.get("date_unix") or 0, reverse=True)

    return jsonify(meetings)


@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    """Handle a chat message."""
    body = request.get_json()

    if not body or "message" not in body:
        return jsonify({"error": "Missing 'message' in request body"}), 400

    clip_id = body.get("clip_id")
    if not clip_id:
        return jsonify({"error": "No clip_id specified"}), 400

    question = body["message"]
    history = body.get("history", [])

    try:
        result = chat(
            question=question,
            clip_id=clip_id,
            conversation_history=history,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search", methods=["POST"])
def search_endpoint():
    """Search across multiple meetings with optional board and date filters."""
    body = request.get_json()

    if not body or "query" not in body:
        return jsonify({"error": "Missing 'query' in request body"}), 400

    query = body["query"].strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400

    view_ids = body.get("view_ids")  # list of strings, or None for all
    date_from = body.get("date_from")  # unix timestamp, or None
    date_to = body.get("date_to")  # unix timestamp, or None
    top_k = body.get("top_k", 10)

    try:
        data = search_across_meetings(
            query=query,
            view_ids=view_ids,
            date_from=date_from,
            date_to=date_to,
            top_k=top_k,
        )

        # Enrich results with board metadata and formatted timestamps
        for r in data["results"]:
            board_info = get_board_by_view_id(r.get("view_id", ""))
            r["board_name"] = board_info["name"] if board_info else "Unknown"
            r["board_short_name"] = board_info["short_name"] if board_info else "?"
            r["board_color"] = board_info["color"] if board_info else "#666"
            r["timestamp"] = format_timestamp(r.get("start_time"))
            r["timestamp_end"] = format_timestamp(r.get("end_time"))
            # Truncate text for response
            r["text"] = r["text"][:300] + ("..." if len(r["text"]) > 300 else "")

        data["query"] = query
        data["filters"] = {
            "view_ids": view_ids,
            "date_from": date_from,
            "date_to": date_to,
        }

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/headlines")
def headlines():
    """Aggregate top headlines from all processed meetings."""
    headlines = []

    for summary_file in sorted(DATA_DIR.glob("summaries/*.json")):
        try:
            with open(summary_file) as f:
                summary = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        clip_id = summary.get("clip_id", summary_file.stem)
        meeting_name = summary.get("meeting_name", f"Meeting {clip_id}")
        meeting_date = summary.get("meeting_date", "Unknown")

        # Load meeting metadata for board info and stream URL
        meta_path = DATA_DIR / f"meeting_{clip_id}.json"
        view_id = ""
        stream_url = ""
        date_unix = 0
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            view_id = meta.get("view_id", "")
            stream_url = meta.get("stream_url", "")
            date_unix = meta.get("date_unix") or 0

        board_info = get_board_by_view_id(view_id)
        board_name = board_info["name"] if board_info else "Unknown"
        board_short = board_info["short_name"] if board_info else "?"
        board_color = board_info["color"] if board_info else "#666"

        # Decisions & votes — highest value headlines
        for item in summary.get("decisions_and_votes", []):
            desc = item.get("description", "").lower()
            # Skip routine minute approvals — happens every meeting
            if "minutes" in desc and ("approv" in desc or "adopt" in desc):
                continue
            headlines.append({
                "type": "decision",
                "title": item.get("description", ""),
                "detail": f"{item.get('outcome', '')} ({item.get('vote_count', 'N/A')})",
                "clip_id": clip_id,
                "meeting_name": meeting_name,
                "meeting_date": meeting_date,
                "date_unix": date_unix,
                "board_name": board_name,
                "board_short": board_short,
                "board_color": board_color,
                "stream_url": stream_url,
                "timestamp_start": None,
            })

        # Key topics
        for item in summary.get("key_topics", []):
            topic = item.get("topic", "").lower()
            if "minutes" in topic and ("approv" in topic or "adopt" in topic):
                continue
            headlines.append({
                "type": "topic",
                "title": item.get("topic", ""),
                "detail": item.get("summary", ""),
                "clip_id": clip_id,
                "meeting_name": meeting_name,
                "meeting_date": meeting_date,
                "date_unix": date_unix,
                "board_name": board_name,
                "board_short": board_short,
                "board_color": board_color,
                "stream_url": stream_url,
                "timestamp_start": item.get("timestamp_start"),
            })

        # Notable quotes (select)
        for item in summary.get("notable_quotes", [])[:1]:
            headlines.append({
                "type": "quote",
                "title": f'"{item.get("quote", "")}"',
                "detail": f'— {item.get("speaker", "Unknown")}, {item.get("context", "")}',
                "clip_id": clip_id,
                "meeting_name": meeting_name,
                "meeting_date": meeting_date,
                "date_unix": date_unix,
                "board_name": board_name,
                "board_short": board_short,
                "board_color": board_color,
                "stream_url": stream_url,
                "timestamp_start": None,
            })

    # Sort by date (newest first)
    headlines.sort(key=lambda h: h.get("date_unix") or 0, reverse=True)

    return jsonify(headlines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PublicLens Chat Server")
    parser.add_argument("--port", type=int, default=5001, help="Server port (default: 5001)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    print(f"[server] Starting PublicLens on http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)
