#!/bin/bash
# Deploy S3 Sink Connector for raw_events to Kafka Connect

set -e

CONNECT_URL="http://localhost:8083"
CONNECTOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Deploying Kafka Connect S3 Sink Connector..."

# Wait for Kafka Connect to be ready
echo "Waiting for Kafka Connect..."
until curl -sf "$CONNECT_URL/" > /dev/null; do
  echo "  Kafka Connect not ready yet..."
  sleep 5
done
echo "Kafka Connect is ready!"

# Deploy raw_events connector
echo ""
echo "Deploying s3-sink-raw-events..."
curl -X POST "$CONNECT_URL/connectors" \
  -H "Content-Type: application/json" \
  -d @"$CONNECTOR_DIR/s3-sink-raw-events.json"
echo ""

# List all connectors
echo ""
echo "Installed connectors:"
curl -s "$CONNECT_URL/connectors" | jq '.'

echo ""
echo "Connector deployed successfully!"
echo ""
echo "Check status:"
echo "  Kafka Connect UI: http://localhost:8080 (via Kafka UI)"
echo "  Kafka Connect API: $CONNECT_URL/connectors"
