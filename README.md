# PublicLens 🔍

AI-powered government meeting intelligence. Automatically transcribes, summarizes, and enables Q&A over public meeting recordings from Granicus.

## Quick Start

### 1. Setup

```bash
cd publiclens
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add your OpenAI API key

Edit `.env` and replace the placeholder:
```
OPENAI_API_KEY=sk-your-actual-key
```

### 3. Run the pipeline

```bash
# List available meetings
python pipeline/run_pipeline.py --list

# Process a specific meeting (scrape → download → transcribe → summarize → index)
python pipeline/run_pipeline.py --clip_id 16177

# If auto-extraction of the stream URL fails, provide it manually:
python pipeline/run_pipeline.py --clip_id 16177 --stream_url "https://archive-stream.granicus.com/..."
```

### 4. Start the chat server

```bash
python server/app.py --clip_id 16177
```

Then open http://localhost:5001

## Architecture

```
publiclens/
├── pipeline/              # Data pipeline
│   ├── scraper.py         # Scrape meeting metadata from Granicus
│   ├── downloader.py      # Download audio via ffmpeg
│   ├── transcriber.py     # Transcribe with OpenAI Whisper
│   ├── summarizer.py      # Summarize with GPT-4
│   ├── indexer.py         # Build FAISS vector index
│   └── run_pipeline.py    # CLI orchestrator
├── server/                # Chat server
│   ├── app.py             # Flask API
│   ├── rag.py             # RAG chat engine
│   └── static/            # Frontend
│       ├── index.html
│       ├── style.css
│       └── chat.js
├── data/                  # Generated data (gitignored)
│   ├── audio/
│   ├── transcripts/
│   ├── summaries/
│   └── index/
├── requirements.txt
├── .env                   # Your API key (gitignored)
└── README.md
```

## Prerequisites

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- OpenAI API key
