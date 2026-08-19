#!/bin/bash
# Batch pipeline run — processes all new board meetings
# Usage: source .venv/bin/activate && bash pipeline/batch_run.sh

set -e

# New boards — 1 meeting each
MEETINGS=(
    "2:9691"      # Stamford View — TCR Meeting
    "5:15697"     # OPEB — Tax Abate Cmte
    "6:15643"     # Health Commission
    "7:3802"      # Animal Control Task Force
    "9:16122"     # Parks & Recreation
    "10:16133"    # Harbor Management
    "11:14635"    # Traffic Advisory Committee
    "12:9145"     # Transit District
    "15:15742"    # WPCA
    "17:16125"    # Environmental Protection Board
    "18:16163"    # Historic Preservation
    "19:16131"    # Zoning Board of Appeals
    "21:15347"    # Camera Review
    "22:11876"    # Fire Commission
    "23:16137"    # Police Commission
    "24:15579"    # Social Services Commission
    # Second meetings for 3 boards
    "6:15637"     # Health Commission (2nd)
    "20:16134"    # Planning Board (2nd)
    "23:16095"    # Police Commission (2nd)
)

TOTAL=${#MEETINGS[@]}
COUNT=0

for entry in "${MEETINGS[@]}"; do
    IFS=':' read -r view_id clip_id <<< "$entry"
    COUNT=$((COUNT + 1))
    echo ""
    echo "========================================================================"
    echo "  [$COUNT/$TOTAL] Processing view_id=$view_id clip_id=$clip_id"
    echo "========================================================================"
    python pipeline/run_pipeline.py --clip_id "$clip_id" --view_id "$view_id" || {
        echo "  ⚠ Failed clip_id=$clip_id, continuing..."
    }
done

echo ""
echo "========================================================================"
echo "  Batch complete: $COUNT/$TOTAL meetings processed"
echo "========================================================================"
