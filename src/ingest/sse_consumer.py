#!/usr/bin/env python3
"""
SSE Consumer for Wikimedia EventStreams
Filters events by entity allowlist and produces to Kafka topics

"""

import json
import os
import logging
from typing import Dict, Set, Optional
from datetime import datetime

import yaml
import sseclient
import requests
from kafka import KafkaProducer
from kafka.errors import KafkaError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EntityFilter:
    """Manages entity allowlist filtering"""
    
    def __init__(self, allowlist_path: str):
        self.allowlist_path = allowlist_path
        self.entities: Set[str] = set()
        self.aliases: Dict[str, str] = {}
        self.load_allowlist()
    
    def load_allowlist(self):
        """Load entity allowlist from YAML config"""
        try:
            with open(self.allowlist_path, 'r') as f:
                config = yaml.safe_load(f)
            
            for entity in config.get('entities', []):
                title = entity['title']
                wiki = entity.get('wiki', 'enwiki')
                
                self.entities.add(f"{wiki}:{title}")
                
                for alias in entity.get('aliases', []):
                    self.aliases[f"{wiki}:{alias}"] = f"{wiki}:{title}"
            
            logger.info(f"Loaded {len(self.entities)} entities with {len(self.aliases)} aliases")
            
        except Exception as e:
            logger.error(f"Failed to load allowlist: {e}")
            raise
    
    def _normalize(self, s: str) -> str:
        """Normalize string for flexible matching: lower, replace underscores/spaces, strip"""
        return s.lower().replace('_', ' ').replace('  ', ' ').strip()

    def is_monitored(self, wiki: str, title: str) -> bool:
        """Flexible allowlist: match on title or aliases, case-insensitive, partial, normalized"""
        title_norm = self._normalize(title)

        # Check direct entities
        for entity_key in self.entities:
            if entity_key.startswith(f"{wiki}:"):
                entity_title = self._normalize(entity_key.split(':', 1)[1])
                if entity_title in title_norm or title_norm in entity_title:
                    return True

        # Check aliases
        for alias_key in self.aliases.keys():
            if alias_key.startswith(f"{wiki}:"):
                alias_title = self._normalize(alias_key.split(':', 1)[1])
                if alias_title in title_norm or title_norm in alias_title:
                    return True

        return False
    
    def get_canonical_entity(self, wiki: str, title: str) -> Optional[str]:
        """Get canonical entity name (resolve aliases, flexible match)"""
        key = f"{wiki}:{title}"
        norm_title = self._normalize(title)

        # Direct match
        if key in self.entities:
            return key

        # Alias direct match
        if key in self.aliases:
            return self.aliases[key]

        # Flexible match for entities
        for entity_key in self.entities:
            if entity_key.startswith(f"{wiki}:"):
                entity_title = self._normalize(entity_key.split(':', 1)[1])
                if entity_title in norm_title or norm_title in entity_title:
                    return entity_key

        # Flexible match for aliases
        for alias_key, canonical in self.aliases.items():
            if alias_key.startswith(f"{wiki}:"):
                alias_title = self._normalize(alias_key.split(':', 1)[1])
                if alias_title in norm_title or norm_title in alias_title:
                    return canonical

        return None


class SSEConsumer:
    """Consumes Wikimedia EventStreams and produces to Kafka"""
    
    def __init__(
        self,
        kafka_bootstrap_servers: str,
        allowlist_path: str,
        user_agent: str = "WikiGuard/1.0 (https://github.com/wikiguard; contact@example.com)",
        sse_url: str = "https://stream.wikimedia.org/v2/stream/recentchange"
    ):
        self.sse_url = sse_url
        self.user_agent = user_agent
        self.kafka_bootstrap_servers = kafka_bootstrap_servers
        
        # Entity filter
        self.entity_filter = EntityFilter(allowlist_path)
        
        # Kafka topics
        self.raw_topic = "raw_events"
        self.cleaned_topic = "cleaned_events"
        self.dlq_topic = "dlq_events"
        
        # Initialize Kafka producer
        self.producer = self._create_kafka_producer()
        
        # Metrics
        self.events_processed = 0
        self.events_filtered = 0
        self.events_sent = 0
        self.errors = 0
    
    def _create_kafka_producer(self) -> KafkaProducer:
        """Create Kafka producer with retry configuration (supports both local Docker and MSK)"""
        try:
            config = {
                'bootstrap_servers': self.kafka_bootstrap_servers.split(','),
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'acks': 'all',
                'retries': 3,
                'max_in_flight_requests_per_connection': 1,
                'compression_type': 'gzip'
            }
            
            # For MSK with TLS (detect by port 9094 or explicit env var)
            if ':9094' in self.kafka_bootstrap_servers or os.getenv('KAFKA_SECURITY_PROTOCOL') == 'SSL':
                config['security_protocol'] = 'SSL'
                logger.info("Using SSL/TLS for MSK connection")
            else:
                logger.info("Using PLAINTEXT for local Kafka")
            
            producer = KafkaProducer(**config)
            logger.info(f"Connected to Kafka: {self.kafka_bootstrap_servers}")
            return producer
        except Exception as e:
            logger.error(f"Failed to create Kafka producer: {e}")
            raise
    
    def validate_event(self, event_data: Dict) -> bool:
        """Validate event has required fields"""
        required_fields = ['title', 'wiki']
        return all(field in event_data for field in required_fields)
    
    def enrich_event(self, event_data: Dict) -> Dict:
        """Enrich event with metadata"""
        enriched = event_data.copy()
        
        # Add ingestion metadata
        enriched['_metadata'] = {
            'ingestion_timestamp': datetime.utcnow().isoformat(),
            'source': 'wikimedia_sse',
            'version': '1.0',
            'canonical_entity': self.entity_filter.get_canonical_entity(
                event_data['wiki'],
                event_data['title']
            )
        }
        
        return enriched
    
    def send_to_kafka(self, topic: str, event: Dict, key: Optional[str] = None):
        """Send event to Kafka topic"""
        try:
            future = self.producer.send(
                topic,
                value=event,
                key=key.encode('utf-8') if key else None
            )
            
            # Block until sent (for reliability)
            future.get(timeout=10)
            self.events_sent += 1
            
        except KafkaError as e:
            logger.error(f"Failed to send to Kafka topic {topic}: {e}")
            self.errors += 1
            
            # Send to DLQ
            try:
                self.producer.send(
                    self.dlq_topic,
                    value={
                        'original_event': event,
                        'error': str(e),
                        'target_topic': topic,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
            except Exception as dlq_error:
                logger.error(f"Failed to send to DLQ: {dlq_error}")
    
    def process_event(self, event_data: Dict):
        """Process a single event"""
        try:
            self.events_processed += 1
            
            # Validate event structure
            if not self.validate_event(event_data):
                logger.warning(f"Invalid event structure: {event_data.get('id', 'unknown')}")
                self.send_to_kafka(self.dlq_topic, {
                    'original_event': event_data,
                    'error': 'Missing required fields',
                    'timestamp': datetime.utcnow().isoformat()
                })
                return
            
            wiki = event_data.get('wiki')
            title = event_data.get('title')
            
            # Filter by allowlist
            if not self.entity_filter.is_monitored(wiki, title):
                self.events_filtered += 1
                return
            
            logger.info(f"Monitored event: {wiki}:{title} (type: {event_data.get('type')})")
            
            # Send raw event
            self.send_to_kafka(
                self.raw_topic,
                event_data,
                key=f"{wiki}:{title}"
            )
            
            # Enrich and send cleaned event
            enriched_event = self.enrich_event(event_data)
            self.send_to_kafka(
                self.cleaned_topic,
                enriched_event,
                key=f"{wiki}:{title}"
            )
            
        except Exception as e:
            logger.error(f"Error processing event: {e}")
            self.errors += 1
            
            # Send to DLQ
            self.send_to_kafka(self.dlq_topic, {
                'original_event': event_data,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })
    
    def consume_stream(self,):
        """
        Consume events from Wikimedia SSE stream with auto-reconnect on disconnect.

        """
        import time
        headers = {'User-Agent': self.user_agent}
        logger.info(f"Starting SSE consumer from {self.sse_url}")
        logger.info(f"Monitoring {len(self.entity_filter.entities)} entities")


        attempt = 0
        max_backoff = 300  # 5 minutes
        while True:
            try:
                response = requests.get(self.sse_url, stream=True, headers=headers, timeout=60)
                response.raise_for_status()
                client = sseclient.SSEClient(response)
                logger.info("Connected to SSE stream.")
                attempt = 0  # Reset attempt after successful connect

                for event in client.events():
                    # Process event
                    if event.data:
                        try:
                            event_data = json.loads(event.data)
                            self.process_event(event_data)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON: {e}")
                            self.errors += 1

                    # Log metrics every 100 events
                    if self.events_processed % 100 == 0:
                        self.log_metrics()

            except KeyboardInterrupt:
                logger.info("Consumer interrupted by user")
                self.shutdown()
                return
            except Exception as e:
                attempt += 1
                backoff = min(2 ** attempt, max_backoff)
                logger.error(f"Stream error/disconnect: {e}. Reconnecting in {backoff} seconds (attempt {attempt})...")
                time.sleep(backoff)
            finally:
                # On any disconnect, flush and log metrics
                self.log_metrics()
    
    def log_metrics(self):
        """Log consumer metrics"""
        logger.info(
            f"Metrics - Processed: {self.events_processed}, "
            f"Filtered: {self.events_filtered}, "
            f"Sent: {self.events_sent}, "
            f"Errors: {self.errors}"
        )
    
    def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down consumer...")
        self.log_metrics()
        
        if self.producer:
            self.producer.flush()
            self.producer.close()
        
        logger.info("Consumer shutdown complete")


def main():
    """Main entry point for ECS Fargate (runs indefinitely)"""
    # Configuration from environment variables
    kafka_bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    allowlist_path = os.getenv('ALLOWLIST_PATH', '/app/config/entity-allowlist.yaml')
    user_agent = os.getenv('USER_AGENT', 'WikiGuard/1.0')
    
    # Create consumer
    consumer = SSEConsumer(
        kafka_bootstrap_servers=kafka_bootstrap,
        allowlist_path=allowlist_path,
        user_agent=user_agent
    )
    
    consumer.consume_stream()


if __name__ == "__main__":
    main()
