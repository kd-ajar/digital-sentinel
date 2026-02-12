# WikiGuard Architecture Diagrams

This document contains architecture diagrams that match the actual implementation of the WikiGuard streaming pipeline.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           WikiGuard Streaming Pipeline                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │   WIKIMEDIA      │
    │  EventStreams    │
    │    (SSE API)     │
    └────────┬─────────┘
             │ Server-Sent Events
             ▼
┌────────────────────────┐        ┌─────────────────────────────────────────────────────┐
│     ECS FARGATE        │        │                   AMAZON MSK                         │
│  ┌──────────────────┐  │        │  ┌─────────────────────────────────────────────┐    │
│  │ sse_consumer.py  │  │  TLS   │  │              cleaned_events                 │    │
│  │                  │──┼────────┼──│  (filtered by entity-allowlist.yaml)        │    │
│  │ - Entity Filter  │  │        │  │  - Retention: 7 days                        │    │
│  │ - Kafka Producer │  │        │  │  - Partitions: Based on wiki                │    │
│  └──────────────────┘  │        │  └─────────────────────────────────────────────┘    │
└────────────────────────┘        └──────────────────────┬──────────────────────────────┘
                                                         │
                         ┌───────────────────────────────┴────────────────────────────┐
                         │                  EMR SERVERLESS                             │
                         │     (Spark Structured Streaming - Medallion Architecture)   │
                         │                                                             │
┌────────────────────────┴─────────────────────────────────────────────────────────────┴──┐
│                                                                                          │
│  ┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐             │
│  │   BRONZE APP       │    │    SILVER APP      │    │     GOLD APP       │             │
│  │ ┌────────────────┐ │    │ ┌────────────────┐ │    │ ┌────────────────┐ │             │
│  │ │bronze_writer.py│ │    │ │silver_writer.py│ │    │ │ gold_writer.py │ │             │
│  │ └───────┬────────┘ │    │ └───────┬────────┘ │    │ └───────┬────────┘ │             │
│  │         │          │    │         │          │    │         │          │             │
│  │ Trigger: 2 min     │    │ Trigger: 10 min    │    │ Trigger: 10 min    │             │
│  │ Kafka → Iceberg    │    │ Dedupe, Enrich     │    │ Aggregate Metrics  │             │
│  └─────────┼──────────┘    └─────────┼──────────┘    └─────────┼──────────┘             │
│            │                         │                         │                        │
│            │    ┌────────────────────┴─────────────────────────┘                        │
│            │    │                                                                       │
│            ▼    ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA QUALITY GATE                                        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │   │
│  │  │   PyDeequ   │  │  SQL Checks │  │   Metrics   │  │     Alert Manager       │ │   │
│  │  │ Constraints │  │  Freshness  │  │  Pass Rate  │  │  SNS (Critical)         │ │   │
│  │  │ Statistical │  │  Validity   │  │  Batch ID   │  │  Slack (Warning)        │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────────┘ │   │
│  └───────────────────────────────────┬─────────────────────────────────────────────┘   │
│                                      │                                                  │
│                          ┌───────────┴───────────┐                                      │
│                          ▼                       ▼                                      │
│                   ┌────────────┐          ┌──────────────┐                              │
│                   │   PASSED   │          │  QUARANTINE  │                              │
│                   └────────────┘          └──────────────┘                              │
└──────────────────────────┼───────────────────────┼──────────────────────────────────────┘
                           │                       │
                           ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AMAZON S3 LAKEHOUSE                                         │
│                          (Apache Iceberg & Parquet)                                      │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │                           MEDALLION LAYERS                                       │    │
│  │                                                                                  │    │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐ │    │
│  │   │     BRONZE      │  │     SILVER      │  │            GOLD                 │ │    │
│  │   │                 │  │                 │  │                                 │ │    │
│  │   │ bronze_events   │  │ silver_events   │  │ gold_entity_metrics_10min      │ │    │
│  │   │ (raw JSON)      │  │ (parsed,dedupe) │  │ gold_user_metrics_10min        │ │    │
│  │   │                 │  │                 │  │ gold_global_metrics_10min      │ │    │
│  │   │ Partition:      │  │ Partition:      │  │                                 │ │    │
│  │   │  event_date     │  │  event_date     │  │ Partition: metric_date         │ │    │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘ │    │
│  │                                                                                  │    │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐ │    │
│  │   │ QUARANTINE      │  │ QUARANTINE      │  │ QUARANTINE                      │ │    │
│  │   │ bronze_         │  │ silver_         │  │ gold_quarantine                 │ │    │
│  │   │ quarantine      │  │ quarantine      │  │                                 │ │    │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │                          SUPPORTING PATHS                                        │    │
│  │  /scripts/           - PySpark scripts                                           │    │
│  │  /checkpoints/       - Spark Structured Streaming checkpoints                    │    │
│  │  /emr-serverless-logs/ - Spark driver/executor logs                              │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────┬──────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            AWS GLUE DATA CATALOG                                         │
│                                                                                          │
│  Database: wikiguard_lakehouse                                                           │
│  Tables: bronze_events, silver_events, gold_*_metrics, *_quarantine                     │
│  Format: Apache Iceberg (ACID, Time Travel, Schema Evolution)                           │
└──────────────────────────────────┬──────────────────────────────────────────────────────┘
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
              ┌──────────────────┐  ┌──────────────────┐
              │  AMAZON ATHENA   │  │ AMAZON QUICKSIGHT│
              │                  │  │                  │
              │  SQL Queries     │  │  Dashboards      │
              │                  │  │  Visualizations  │
              └──────────────────┘  └──────────────────┘
```

---

## Data Flow Diagram

```
                           WikiGuard Data Flow
    ┌─────────────────────────────────────────────────────────────────┐
    │                     REAL-TIME STREAMING PIPELINE                │
    └─────────────────────────────────────────────────────────────────┘

    WIKIMEDIA SSE                    ECS FARGATE                 AMAZON MSK
    ─────────────                    ───────────                 ──────────
         │                                │                           │
         │  SSE Event Stream              │                           │
         ├───────────────────────────────►│                           │
         │                                │                           │
         │                    ┌───────────┴───────────┐               │
         │                    │ Entity in Allowlist?  │               │
         │                    └───────────┬───────────┘               │
         │                          YES   │   NO                      │
         │                           │    └──── (discard)             │
         │                           │                                │
         │                           │  Produce to cleaned_events     │
         │                           ├───────────────────────────────►│
         │                           │                    TLS         │
    ─────┴───────────────────────────┴────────────────────────────────┴─────

                              EMR SERVERLESS PROCESSING
    ───────────────────────────────────────────────────────────────────────

    ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
    │   BRONZE    │         │   SILVER    │         │    GOLD     │
    │  (2 min)    │         │  (10 min)   │         │  (10 min)   │
    └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
           │                       │                       │
    ┌──────▼──────┐         ┌──────▼──────┐         ┌──────▼──────┐
    │ Consume     │         │ Read Bronze │         │ Read Silver │
    │ from Kafka  │         │ Iceberg     │         │ Iceberg     │
    └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
           │                       │                       │
    ┌──────▼──────┐         ┌──────▼──────┐         ┌──────▼──────┐
    │ Quality     │         │ Parse JSON  │         │ 10-min      │
    │ Gate        │         │ Deduplicate │         │ Aggregation │
    └──────┬──────┘         │ Enrich      │         └──────┬──────┘
           │                └──────┬──────┘                │
           │                       │                       │
           │                ┌──────▼──────┐         ┌──────▼──────┐
           │                │ Quality     │         │ Quality     │
           │                │ Gate        │         │ Gate        │
           │                └──────┬──────┘         └──────┬──────┘
           │                       │                       │
    ───────┴───────────────────────┴───────────────────────┴───────────

                              S3 ICEBERG LAKEHOUSE
    ───────────────────────────────────────────────────────────────────────

    ┌───────────────────────────────────────────────────────────────────┐
    │                                                                   │
    │   PASSED                    PASSED                    PASSED      │
    │     │                         │                         │         │
    │     ▼                         ▼                         ▼         │
    │ ┌─────────────┐        ┌─────────────┐        ┌─────────────────┐│
    │ │bronze_events│        │silver_events│        │gold_*_metrics   ││
    │ │(raw JSON)   │        │(parsed)     │        │(aggregated)     ││
    │ └─────────────┘        └─────────────┘        └─────────────────┘│
    │                                                                   │
    │   FAILED                    FAILED                    FAILED      │
    │     │                         │                         │         │
    │     ▼                         ▼                         ▼         │
    │ ┌─────────────┐        ┌─────────────┐        ┌─────────────────┐│
    │ │bronze_      │        │silver_      │        │gold_            ││
    │ │quarantine   │        │quarantine   │        │quarantine       ││
    │ └─────────────┘        └─────────────┘        └─────────────────┘│
    │                                                                   │
    └───────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │                     AWS GLUE DATA CATALOG                         │
    │                     wikiguard_lakehouse                           │
    └───────────────────────────────┬───────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             ┌─────────────┐                ┌─────────────┐
             │   ATHENA    │                │ QUICKSIGHT  │
             │ SQL Queries │                │ Dashboards  │
             └─────────────┘                └─────────────┘
```

---

## Infrastructure Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              VPC (10.0.0.0/16)                                   │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                         PUBLIC SUBNETS                                      │ │
│  │                                                                             │ │
│  │    ┌─────────────────┐                                                      │ │
│  │    │   NAT Gateway   │◄──── Internet Gateway ◄──── Internet                 │ │
│  │    └────────┬────────┘                                                      │ │
│  │             │                                                               │ │
│  └─────────────┼───────────────────────────────────────────────────────────────┘ │
│                │                                                                  │
│  ┌─────────────▼──────────────────────────────────────────────────────────────┐ │
│  │                       PRIVATE SUBNETS (Multi-AZ)                            │ │
│  │                                                                             │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                        ECS CLUSTER                                   │   │ │
│  │  │  ┌─────────────────────────────────────────────────────────────┐    │   │ │
│  │  │  │  Fargate Task                                                │    │   │ │
│  │  │  │  sse_consumer.py                                             │    │   │ │
│  │  │  │  CPU: 0.25 vCPU | Memory: 0.5 GB                             │    │   │ │
│  │  │  └─────────────────────────────────────────────────────────────┘    │   │ │
│  │  └────────────────────────────────┬────────────────────────────────────┘   │ │
│  │                                   │ TLS (port 9094)                        │ │
│  │                                   ▼                                        │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                        MSK CLUSTER                                   │   │ │
│  │  │                                                                      │   │ │
│  │  │    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │   │ │
│  │  │    │   Broker 1   │  │   Broker 2   │  │   Broker 3   │             │   │ │
│  │  │    │kafka.t3.small│  │kafka.t3.small│  │kafka.t3.small│             │   │ │
│  │  │    │   (AZ-a)     │  │   (AZ-b)     │  │   (AZ-c)     │             │   │ │
│  │  │    └──────────────┘  └──────────────┘  └──────────────┘             │   │ │
│  │  │                                                                      │   │ │
│  │  └────────────────────────────────────────┬────────────────────────────┘   │ │
│  │                                   │                                        │ │
│  │                                   ▼                                        │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                     EMR SERVERLESS                                   │   │ │
│  │  │                                                                      │   │ │
│  │  │    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │   │ │
│  │  │    │  BRONZE APP  │  │  SILVER APP  │  │   GOLD APP   │             │   │ │
│  │  │    │              │  │              │  │              │             │   │ │
│  │  │    │ 1 vCPU, 2 GB │  │ 2 vCPU, 6 GB │  │ 1 vCPU, 2 GB │             │   │ │
│  │  │    │              │  │              │  │              │             │   │ │
│  │  │    └──────────────┘  └──────────────┘  └──────────────┘             │   │ │
│  │  │                                                                      │   │ │
│  │  └─────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                             │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ VPC Endpoints / Internet
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         AWS MANAGED SERVICES                                      │
│                                                                                   │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│   │     S3      │  │    Glue     │  │   Athena    │  │     SNS / Secrets Mgr   │ │
│   │  Lakehouse  │  │   Catalog   │  │   Queries   │  │     Alerts / Tokens     │ │
│   │             │  │             │  │             │  │                         │ │
│   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Medallion Architecture Detail

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          MEDALLION ARCHITECTURE                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────┐    ┌───────────────────────┐    ┌───────────────────────┐
│    BRONZE LAYER       │    │    SILVER LAYER       │    │     GOLD LAYER        │
│    (Raw Ingestion)    │    │  (Cleaned & Enriched) │    │    (Aggregated)       │
├───────────────────────┤    ├───────────────────────┤    ├───────────────────────┤
│                       │    │                       │    │                       │
│ INPUT:                │    │ INPUT:                │    │ INPUT:                │
│   Kafka cleaned_events│───►│   bronze_events       │───►│   silver_events       │
│                       │    │   (Iceberg stream)    │    │   (Iceberg stream)    │
│                       │    │                       │    │                       │
├───────────────────────┤    ├───────────────────────┤    ├───────────────────────┤
│                       │    │                       │    │                       │
│ PROCESSING:           │    │ PROCESSING:           │    │ PROCESSING:           │
│  • Raw JSON preserve  │    │  • Parse JSON fields  │    │  • 10-min windows     │
│  • Kafka metadata     │    │  • Dedupe (meta_id)   │    │  • Entity metrics     │
│  • Ingestion timestamp│    │  • Derived fields:    │    │  • User metrics       │
│                       │    │    - is_anonymous     │    │  • Global metrics     │
│                       │    │    - is_bot           │    │  • Anomaly detection  │
│                       │    │    - bytes_changed    │    │                       │
│                       │    │    - processing_lag   │    │                       │
│                       │    │                       │    │                       │
├───────────────────────┤    ├───────────────────────┤    ├───────────────────────┤
│                       │    │                       │    │                       │
│ QUALITY CHECKS:       │    │ QUALITY CHECKS:       │    │ QUALITY CHECKS:       │
│  ✓ Size >= 1          │    │  ✓ Size >= 1          │    │  ✓ Size >= 1          │
│  ✓ event_id NOT NULL  │    │  ✓ Completeness       │    │  ✓ total_events >= 0  │
│  ✓ event_data NOT NULL│    │  ✓ Freshness <= 3600s │    │  ✓ entity NOT NULL    │
│  ✓ kafka_partition >=0│    │  ✓ event_type valid   │    │  ✓ wiki NOT NULL      │
│  ✓ kafka_offset >= 0  │    │  ✓ wikimedia_id > 0   │    │  ✓ Logical constraints│
│                       │    │  ✓ Temporal validity  │    │                       │
│                       │    │                       │    │                       │
├───────────────────────┤    ├───────────────────────┤    ├───────────────────────┤
│                       │    │                       │    │                       │
│ OUTPUT:               │    │ OUTPUT:               │    │ OUTPUT:               │
│  ┌─────────────────┐  │    │  ┌─────────────────┐  │    │  ┌─────────────────┐  │
│  │ bronze_events   │  │    │  │ silver_events   │  │    │  │ gold_entity_    │  │
│  │ (Passed)        │  │    │  │ (Passed)        │  │    │  │ metrics_10min   │  │
│  └─────────────────┘  │    │  └─────────────────┘  │    │  ├─────────────────┤  │
│  ┌─────────────────┐  │    │  ┌─────────────────┐  │    │  │ gold_user_      │  │
│  │ bronze_         │  │    │  │ silver_         │  │    │  │ metrics_10min   │  │
│  │ quarantine      │  │    │  │ quarantine      │  │    │  ├─────────────────┤  │
│  │ (Failed)        │  │    │  │ (Failed)        │  │    │  │ gold_global_    │  │
│  └─────────────────┘  │    │  └─────────────────┘  │    │  │ metrics_10min   │  │
│                       │    │                       │    │  └─────────────────┘  │
│                       │    │                       │    │  ┌─────────────────┐  │
│                       │    │                       │    │  │ gold_quarantine │  │
│                       │    │                       │    │  │ (Failed)        │  │
│                       │    │                       │    │  └─────────────────┘  │
│                       │    │                       │    │                       │
├───────────────────────┤    ├───────────────────────┤    ├───────────────────────┤
│ TRIGGER: 2 min        │    │ TRIGGER: 10 min       │    │ TRIGGER: 10 min       │
│ PARTITION: event_date │    │ PARTITION: event_date │    │ PARTITION: metric_date│
└───────────────────────┘    └───────────────────────┘    └───────────────────────┘
```

---

## Data Quality Gate Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DATA QUALITY GATE FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────┐
                              │   INPUT BATCH   │
                              │  (DataFrame)    │
                              └────────┬────────┘
                                       │
                                       ▼
              ┌────────────────────────────────────────────────────┐
              │                  QUALITY GATE                       │
              │                                                     │
              │   ┌─────────────────────────────────────────────┐  │
              │   │              PyDeequ Checks                  │  │
              │   │  • Completeness (NOT NULL)                   │  │
              │   │  • Uniqueness (after dedupe)                 │  │
              │   │  • Constraints (ranges, enums)               │  │
              │   │  • Statistical validation                    │  │
              │   └─────────────────────────────────────────────┘  │
              │                        +                            │
              │   ┌─────────────────────────────────────────────┐  │
              │   │               SQL Checks                     │  │
              │   │  • Freshness (processing_lag <= 3600s)       │  │
              │   │  • Validity (event_type in enum)             │  │
              │   │  • Temporal (timestamp ranges)               │  │
              │   │  • Business rules                            │  │
              │   └─────────────────────────────────────────────┘  │
              │                                                     │
              └────────────────────────┬───────────────────────────┘
                                       │
                           ┌───────────┴───────────┐
                           │    COLLECT METRICS    │
                           │  • Pass Rate          │
                           │  • Failed Checks      │
                           │  • Batch ID           │
                           └───────────┬───────────┘
                                       │
                     ┌─────────────────┼─────────────────┐
                     │                 │                 │
                     ▼                 ▼                 ▼
            ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
            │   PASSED    │   │   FAILED    │   │   ALERTS    │
            │   RECORDS   │   │   RECORDS   │   │             │
            └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
                   │                 │                 │
                   ▼                 ▼                 │
          ┌─────────────────┐ ┌─────────────────┐      │
          │   MAIN TABLE    │ │   QUARANTINE    │      │
          │                 │ │   TABLE         │      │
          │  bronze_events  │ │                 │      │
          │  silver_events  │ │ + failure_reason│      │
          │  gold_*_metrics │ │ + failed_checks │      │
          │                 │ │ + original_data │      │
          └─────────────────┘ └─────────────────┘      │
                                                       │
                    ┌──────────────────────────────────┘
                    │
                    ▼
    ┌───────────────────────────────────────────────────────────────┐
    │                      ALERT MANAGER                             │
    │                                                                │
    │   ┌─────────────────────────────────────────────────────────┐ │
    │   │  CRITICAL (Pass Rate < 80%)                              │ │
    │   │  • SNS Notification (Email)                              │ │
    │   │  • Slack Message (#wikiguard-alerts)                     │ │
    │   │  Triggers: Completeness, Size, Critical constraints      │ │
    │   └─────────────────────────────────────────────────────────┘ │
    │                                                                │
    │   ┌─────────────────────────────────────────────────────────┐ │
    │   │  WARNING (Pass Rate < 95%)                               │ │
    │   │  • Slack Message only                                    │ │
    │   │  Triggers: Non-critical constraint failures              │ │
    │   └─────────────────────────────────────────────────────────┘ │
    │                                                                │
    │   ┌─────────────────────────────────────────────────────────┐ │
    │   │  SUCCESS (Pass Rate >= 95%)                              │ │
    │   │  • Log only (no notification)                            │ │
    │   └─────────────────────────────────────────────────────────┘ │
    │                                                                │
    └───────────────────────────────────────────────────────────────┘
```

---

## Replay & Backfill Operations

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       REPLAY & BACKFILL OPERATIONS                               │
└─────────────────────────────────────────────────────────────────────────────────┘

NORMAL OPERATION
================

    MSK ──────► Bronze ──────► Silver ──────► Gold
    (latest)   (2 min)        (10 min)       (10 min)


RECOVERY OPTION 1: Replay from Kafka (within 7-day retention)
=============================================================

    ┌─────────────────────────────────────────────────────────────────────┐
    │ 1. Delete Bronze checkpoint                                         │
    │    aws s3 rm s3://bucket/checkpoints/bronze/ --recursive           │
    │                                                                      │
    │ 2. Set starting_offsets = "earliest" in bronze_writer.py           │
    │                                                                      │
    │ 3. Restart Bronze job                                               │
    │    ./serverless_submit_bronze.sh                                    │
    │                                                                      │
    │ 4. Bronze reprocesses ALL Kafka messages (up to 7 days)            │
    └─────────────────────────────────────────────────────────────────────┘

    MSK ═══════════════════════════════════════════════════► Bronze
         (ALL messages from earliest offset)                  (reprocess)


RECOVERY OPTION 2: Replay Silver from Bronze
============================================

    ┌─────────────────────────────────────────────────────────────────────┐
    │ 1. Delete Silver checkpoint                                         │
    │    aws s3 rm s3://bucket/checkpoints/silver/ --recursive           │
    │                                                                      │
    │                                                                      │
    │ 3. Restart Silver job                                               │
    │    ./serverless_submit_silver.sh                                    │
    └─────────────────────────────────────────────────────────────────────┘

    bronze_events ═══════════════════════════════════════► Silver
                   (reprocess all unprocessed Bronze data)  (reprocess)

RECOVERY OPTION 3: Reprocess Quarantined Data
=============================================

    ┌─────────────────────────────────────────────────────────────────────┐
    │ 1. Identify quarantine reason                                       │
    │    SELECT quarantine_reason, COUNT(*)                              │
    │    FROM silver_quarantine GROUP BY 1;                              │
    │                                                                      │
    │ 2. Fix root cause (e.g., update quality gate thresholds)           │
    │                                                                      │
    │ 3. Export and reprocess quarantined records                        │
    │    INSERT INTO silver_events                                       │
    │    SELECT [fixed_columns] FROM silver_quarantine WHERE ...;        │
    │                                                                      │
    │ 4. Clean up quarantine                                             │
    └─────────────────────────────────────────────────────────────────────┘

    silver_quarantine ──► Fix & Transform ──► silver_events
    (failed records)      (manual/batch)      (recovered)
```

---

## Component Summary Table

| Component | Technology | Purpose | Configuration |
|-----------|------------|---------|---------------|
| **Ingestion** | ECS Fargate | Consume Wikimedia SSE, filter, produce to Kafka | 0.25 vCPU, 0.5 GB |
| **Message Queue** | Amazon MSK | Event buffering, decoupling, replay capability | 2× kafka.t3.small, 7-day retention |
| **Bronze Processing** | EMR Serverless (Spark) | Raw ingestion from Kafka to Iceberg | 1 vCPU, 2 GB, 2-min trigger |
| **Silver Processing** | EMR Serverless (Spark) | Parse, dedupe, enrich, quality validation | 2 vCPU, 6 GB, 10-min trigger |
| **Gold Processing** | EMR Serverless (Spark) | 10-minute window aggregations | 1 vCPU, 2 GB, 10-min trigger |
| **Storage** | S3 + Apache Iceberg | ACID lakehouse tables with time travel | Standard tier, partitioned by date |
| **Catalog** | AWS Glue Data Catalog | Schema registry, Iceberg metadata | Database: wikiguard_lakehouse |
| **Query Engine** | Amazon Athena | SQL queries on Iceberg tables | Serverless |
| **Visualization** | Amazon QuickSight | Dashboards and reports | Direct Athena connection |
| **Alerting** | SNS + Slack | Data quality alerts | Critical→SNS, Warning→Slack |
| **Infrastructure** | Terraform | Infrastructure as Code | Modular design |

---

## File Reference

| Diagram | Source File | Description |
|---------|-------------|-------------|
| Architecture ASCII | [docs/RUNBOOK.md](RUNBOOK.md) | Operations runbook with ASCII diagram |
| Architecture Mermaid | This file | Mermaid diagrams for documentation |
| Original PNG | [Screenshoot/architecture/architecture.png](../Screenshoot/architecture/architecture.png) | Original architecture image |
