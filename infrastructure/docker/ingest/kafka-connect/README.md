# Kafka Connect S3 Sink Connector

Automatically ingests Kafka topic to S3 with time-based partitioning.

## Configuration

### s3-sink-raw-events.json

Key settings:
- **Topic**: `raw_events`
- **Flush size**: 100 messages or 1 minute
- **Partitioning**: `year=YYYY/month=MM/day=dd/hour=HH`
- **Format/Compression**: JSON with gzip compression
- **Error handling**: All errors logged to connect-dlq

### S3 Structure

```
s3://wikiguard-lakehouse-dev/
└── bronze/
    └── raw_events/
        └── year=2026/month=02/day=04/hour=11/
            ├── raw_events+0+0000000000.json.gz
            └── raw_events+0+0000000100.json.gz
```

## Deployment
 
 ```bash
./deploy-connectors.sh
```

## Management

### Check Connector Status

```bash
# List all connectors
curl http://localhost:8083/connectors

# Check specific connector status
curl http://localhost:8083/connectors/s3-sink-raw-events/status | jq

# View tasks
curl http://localhost:8083/connectors/s3-sink-raw-events/tasks | jq
```


### Pause/Resume

```bash
# Pause
curl -X PUT http://localhost:8083/connectors/s3-sink-raw-events/pause

# Resume
curl -X PUT http://localhost:8083/connectors/s3-sink-raw-events/resume
```

### Delete Connector

```bash
curl -X DELETE http://localhost:8083/connectors/s3-sink-raw-events
```

## Monitoring

### Kafka UI (http://localhost:8080)
- View connector status
- Monitor throughput
- Check error logs

### Logs

```bash
# Kafka Connect logs
docker logs -f wikiguard-kafka-connect

# Filter for connector errors
docker logs wikiguard-kafka-connect 2>&1 | grep -i error
```


## Troubleshooting

### Connector fails to start

```bash
# Check connector config
curl http://localhost:8083/connectors/s3-sink-raw-events | jq

# Validate config before deploying
curl -X PUT http://localhost:8083/connector-plugins/io.confluent.connect.s3.S3SinkConnector/config/validate \
  -H "Content-Type: application/json" \
  -d @s3-sink-raw-events.json | jq
```

### No data in S3

```bash
# Check if messages are in Kafka
docker exec -it wikiguard-kafka kafka-console-consumer \
  --bootstrap-server broker:29092 \
  --topic raw_events \
  --from-beginning \
  --max-messages 10

# Check connector offset lag
curl http://localhost:8083/connectors/s3-sink-raw-events/status | jq '.tasks[0].id.connector_offset'
```

### AWS credentials issues

```bash
# Test AWS credentials
docker exec -it wikiguard-kafka-connect aws s3 ls s3://wikiguard-lakehouse-dev/

# Check environment variables
docker exec -it wikiguard-kafka-connect env | grep AWS
```
