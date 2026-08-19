"""
Scraper for Granicus meeting pages.

Extracts meeting metadata from ViewPublisher.php listing pages
and HLS stream URLs from MediaPlayer.php player pages.
"""

import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Meeting:
    """Structured meeting metadata."""
    clip_id: str
    name: str
    date: str
    date_unix: Optional[int]
    duration: str
    view_id: str
    video_url: str
    agenda_url: Optional[str] = None
    minutes_url: Optional[str] = None
    stream_url: Optional[str] = None

    def to_dict(self):
        return asdict(self)


BASE_URL = "https://cityofstamford.granicus.com"


def scrape_meeting_list(view_id: str = "4") -> list[Meeting]:
    """
    Scrape all meetings from a Granicus ViewPublisher page.
    
    Args:
        view_id: The Granicus view_id parameter (e.g. "4" for Board of Finance)
    
    Returns:
        List of Meeting objects with metadata
    """
    url = f"{BASE_URL}/ViewPublisher.php?view_id={view_id}"
    print(f"[scraper] Fetching meeting list from {url}")
    
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    meetings = []
    
    # Find all table rows in the archive table
    archive_table = soup.find("table", id="archive")
    if not archive_table:
        print("[scraper] No archive table found on page")
        return meetings
    
    rows = archive_table.find("tbody").find_all("tr")
    
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        
        # Extract meeting name
        name_cell = cells[0]
        name = name_cell.get_text(strip=True)
        # Remove "new!!" marker if present
        name = re.sub(r'^new!!', '', name).strip()
        
        # Extract date
        date_cell = cells[1]
        # Extract unix timestamp from hidden span (before removing it)
        unix_span = date_cell.find("span", style="display:none;")
        date_unix = int(unix_span.text) if unix_span else None
        # Remove the hidden span so it doesn't pollute the visible date text
        if unix_span:
            unix_span.decompose()
        date_text = date_cell.get_text(strip=True)
        
        # Extract duration
        duration = cells[2].get_text(strip=True).replace('\xa0', ' ')
        
        # Extract video link and clip_id
        video_cell = cells[5]
        video_link = video_cell.find("a")
        if not video_link:
            continue
        
        onclick = video_link.get("onclick", "")
        clip_match = re.search(r'clip_id=(\d+)', onclick)
        if not clip_match:
            continue
        
        clip_id = clip_match.group(1)
        video_url = f"{BASE_URL}/MediaPlayer.php?view_id={view_id}&clip_id={clip_id}"
        
        # Extract agenda/minutes links if available
        agenda_url = None
        minutes_url = None
        if len(cells) > 3:
            agenda_link = cells[3].find("a")
            if agenda_link:
                agenda_url = agenda_link.get("href", "")
                if agenda_url and not agenda_url.startswith("http"):
                    agenda_url = f"{BASE_URL}{agenda_url}"
        if len(cells) > 4:
            minutes_link = cells[4].find("a")
            if minutes_link:
                minutes_url = minutes_link.get("href", "")
                if minutes_url and not minutes_url.startswith("http"):
                    minutes_url = f"{BASE_URL}{minutes_url}"
        
        meeting = Meeting(
            clip_id=clip_id,
            name=name,
            date=date_text,
            date_unix=date_unix,
            duration=duration,
            view_id=view_id,
            video_url=video_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
        )
        meetings.append(meeting)
    
    print(f"[scraper] Found {len(meetings)} meetings")
    return meetings


def extract_stream_url(clip_id: str, view_id: str = "4") -> Optional[str]:
    """
    Extract the HLS stream URL from a Granicus MediaPlayer page.
    
    Fetches the player page and searches for the archive-stream.granicus.com URL
    that contains the actual video/audio stream.
    
    Args:
        clip_id: The Granicus clip ID
        view_id: The Granicus view ID
    
    Returns:
        The HLS playlist URL, or None if not found
    """
    url = f"{BASE_URL}/MediaPlayer.php?view_id={view_id}&clip_id={clip_id}"
    print(f"[scraper] Fetching stream URL from {url}")
    
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    
    # Search for the archive-stream URL in the page source
    # Pattern: //archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/cityofstamford/cityofstamford_XXXX.mp4/playlist.m3u8
    patterns = [
        r'(https?://archive-stream\.granicus\.com/[^"\'\s]+\.m3u8)',
        r'(//archive-stream\.granicus\.com/[^"\'\s]+\.m3u8)',
        r'(https?://archive-stream\.granicus\.com/[^"\'\s]+\.mp4)',
        # Also try the media URL pattern
        r'(https?://archive-media\.granicus\.com[^"\'\s]+\.mp4)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, resp.text)
        if match:
            stream_url = match.group(1)
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            print(f"[scraper] Found stream URL: {stream_url}")
            return stream_url
    
    # If we can't find the stream URL in the page source directly,
    # try to find it in JavaScript variables or JSON data
    # Look for any URL containing 'granicus' and '.mp4'
    mp4_pattern = r'["\']([^"\']*granicus[^"\']*\.mp4[^"\']*)["\']'
    match = re.search(mp4_pattern, resp.text)
    if match:
        stream_url = match.group(1)
        if stream_url.startswith("//"):
            stream_url = "https:" + stream_url
        print(f"[scraper] Found stream URL (fallback): {stream_url}")
        return stream_url
    
    print("[scraper] Could not find stream URL in page source")
    print("[scraper] The stream URL may be loaded dynamically via JavaScript.")
    print("[scraper] You may need to open the page in a browser and inspect network traffic.")
    return None


def get_meeting_by_clip_id(clip_id: str, view_id: str = "4") -> Optional[Meeting]:
    """Get a specific meeting by clip_id, including its stream URL."""
    meetings = scrape_meeting_list(view_id)
    
    for meeting in meetings:
        if meeting.clip_id == clip_id:
            # Try to extract the stream URL
            meeting.stream_url = extract_stream_url(clip_id, view_id)
            return meeting
    
    print(f"[scraper] Meeting with clip_id={clip_id} not found")
    return None


if __name__ == "__main__":
    # Quick test: list all meetings
    meetings = scrape_meeting_list("4")
    for m in meetings[:5]:
        print(f"  {m.date} | {m.name} | clip_id={m.clip_id} | {m.duration}")
    
    if meetings:
        # Try extracting stream URL for the most recent meeting
        print(f"\nExtracting stream URL for clip_id={meetings[0].clip_id}...")
        stream_url = extract_stream_url(meetings[0].clip_id, "4")
        if stream_url:
            print(f"Stream URL: {stream_url}")
