#!/usr/bin/env python3
"""
Simple test script to verify Wikimedia EventStreams SSE connection.
Connects to the recentchange stream and prints events in real-time.
"""

import json
import sys
from datetime import datetime
import sseclient
import requests


# Wikimedia EventStreams endpoint
WIKIMEDIA_SSE_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

# User-Agent header (required by Wikimedia)
HEADERS = {
    "User-Agent": "WikiGuard/1.0 (https://github.com/yourproject/wikiguard; your-email@example.com) Python/SSEClient"
}


def wikimedia_stream(max_events=10, output_file=None):
    """
    Connect to Wikimedia EventStreams and print recent change events.
    
    Args:
        max_events: Number of events to display before stopping (default: 10)
        output_file: Path to file to save events (optional, if provided saves JSON lines)
    """
    print(f"--- Connecting to Wikimedia EventStreams...")
    print(f"--- URL: {WIKIMEDIA_SSE_URL}")
    print(f"--- Started at: {datetime.utcnow().isoformat()}")
    if output_file:
        print(f"--- Saving events to: {output_file}")
    print("-" * 100)
    
    # Open output file if specified
    outfile = None
    if output_file:
        try:
            outfile = open(output_file, 'w', encoding='utf-8')
            print(f"Opened output file: {output_file}")
        except IOError as e:
            print(f"Failed to open output file: {e}")
            sys.exit(1)
    
    try:
        # Create SSE client with streaming enabled
        response = requests.get(WIKIMEDIA_SSE_URL, stream=True, timeout=60, headers=HEADERS)
        response.raise_for_status()
        
        client = sseclient.SSEClient(response)
        
        print("Connected successfully! Listening for events...\n")
        
        event_count = 0
        
        for event in client.events():
            if event.data:
                try:
                    # Parse JSON event
                    data = json.loads(event.data)

                    # Save to file if specified
                    if outfile:
                        json.dump(data, outfile, ensure_ascii=False)
                        outfile.write('\n')
                        outfile.flush()  # Ensure data is written immediately

                    # Display event
                    event_count += 1
                    print(f"Event #{event_count}")
                    
                    # Display Full Event Schema
                    print("Full Event Schema:")
                    print(json.dumps(data, indent=2, ensure_ascii=False))

                    print("-" * 100)

                    # Stop after max_events
                    if event_count >= max_events:
                        print(f"\nSuccessfully received {event_count} events!")
                        print("Wikimedia EventStreams SSE is working correctly!")
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"Failed to parse JSON: {e}")
                    continue
                    
    except requests.exceptions.RequestException as e:
        print(f"\nConnection error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\nStopped by user after {event_count} events")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
    finally:
        # Close output file if opened
        if outfile:
            outfile.close()
            print(f"Closed output file: {output_file}")


if __name__ == "__main__":
    
    max_events = 2
    output_file = None
    
    if len(sys.argv) > 1:
        try:
            max_events = int(sys.argv[1])
        except ValueError:
            print("Usage: python main.py [max_events] [output_file]") # uv run main.py 3 wikimedia_events.json
            sys.exit(1)
    
    if len(sys.argv) > 2:
        output_file = sys.argv[2]

    print("\n" + "=" * 100)
    print("  Wikimedia EventStreams SSE Connection Test")
    print("=" * 100 + "\n")
    
    wikimedia_stream(max_events, output_file)
    