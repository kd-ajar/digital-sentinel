#!/usr/bin/env python3
"""
Simple local SSE consumer for testing Kafka integration
Connects to Wikimedia EventStreams and sends events to local Kafka
"""

import json
import os
import logging
from datetime import datetime
import sseclient
import requests
from kafka import KafkaProducer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleSSEConsumer:
    """Simple SSE Consumer for local development"""
    
    def __init__(self, kafka_bootstrap_servers="localhost:9092"):
        self.kafka_bootstrap_servers = kafka_bootstrap_servers
        self.sse_url = "https://stream.wikimedia.org/v2/stream/recentchange"
        self.user_agent = "WikiGuard/1.0 (local-dev)"
        
        # Kafka topics
        self.raw_topic = "raw_events"
        
        # Initialize Kafka producer
        self.producer = self._create_kafka_producer()
        
        # Metrics
        self.events_processed = 0
        self.events_sent = 0
    
    def _create_kafka_producer(self):
        """Create Kafka producer for local development"""
        try:
            producer = KafkaProducer(
                bootstrap_servers=[self.kafka_bootstrap_servers],
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                acks='all',
                retries=3
            )
            logger.info(f"Connected to Kafka: {self.kafka_bootstrap_servers}")
            return producer
        except Exception as e:
                logger.error(f"Failed to create Kafka producer: {e}")
        raise
    
    def consume_and_produce(self):
        """Consume events from SSE and produce to Kafka"""
        headers = {"User-Agent": self.user_agent}
        
        logger.info(f"Connecting to Wikimedia EventStreams...")
        logger.info(f"Events to be send to Kafka topic: {self.raw_topic}")
        
        try:
            response = requests.get(self.sse_url, stream=True, headers=headers)
            response.raise_for_status()
            
            client = sseclient.SSEClient(response)
            logger.info("SSE connection established, listening for events ...")
            
            for event in client.events():
                if event.data:
                    try:
                        # Parse event data
                        event_data = json.loads(event.data)
                        
                        # Add ingestion timestamp
                        event_data['_ingestion_timestamp'] = datetime.utcnow().isoformat()
                        
                        # Send to Kafka
                        self.producer.send(
                            self.raw_topic,
                            value=event_data,
                            key=str(event_data.get('id', '')).encode('utf-8')
                        )
                        
                        self.events_processed += 1
                        self.events_sent += 1
                        
                        if self.events_processed % 10 == 0:
                                logger.info(f"Processed {self.events_processed} events, sent {self.events_sent} to Kafka")

                    except json.JSONDecodeError:
                            logger.warning("Failed to parse event JSON")
                            continue
                    except Exception as e:
                            logger.error(f"Error processing event: {e}")
                            continue
        
        except KeyboardInterrupt:
                logger.info("Interrupted by user")
        except Exception as e:
                logger.error(f"Connection error: {e}")
        finally:
                logger.info(f"Final stats: {self.events_processed} processed, {self.events_sent} sent to Kafka")
                if self.producer:
                    self.producer.flush()
                    self.producer.close()


if __name__ == "__main__":
    # Get Kafka bootstrap servers from environment
    
    kafka_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    
    logger.info("Starting Simple SSE Consumer")
    logger.info(f"Kafka servers: {kafka_servers}")
    
    consumer = SimpleSSEConsumer(kafka_servers)
    consumer.consume_and_produce()