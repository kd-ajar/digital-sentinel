# WikiGuard Data Sample
This directory contains a sample data collection and processing pipeline for Wikimedia EventStreams data. 

## Contents

- `main.py` - Main script to connect to Wikimedia EventStreams SSE and collect sample data
- `profiling.py` - Script to generate data profiling reports for analysis
- `event_example.json` - Sample event structure from Wikimedia EventStreams
- `pyproject.toml` - Python project configuration and dependencies

## Data Directories

- `bronze/` - Raw ingested data files (parquet format) - contains unprocessed event data as received from Wikimedia
- `silver/` - Cleaned and processed data (parquet format) - data validated, standardized, and ready for analysis  
- `gold/` - Aggregated and analytics-ready data (parquet format) - business metrics and KPIs derived from silver data

**Note**: Sample parquet files are included in each layer to demonstrate the expected data structure and schema evolution through the pipeline.

## Setup

1. Install dependencies using uv:
   ```bash
   uv sync
   ```

2. Run the main data collection script:
   ```bash
   uv run main.py [max_events] [output_file]
   ```

## Example Usage

```bash
# Collect 10 events and save to JSON file
uv run main.py 10 wikimedia_events.json

# Run data profiling
uv run profiling.py
```
