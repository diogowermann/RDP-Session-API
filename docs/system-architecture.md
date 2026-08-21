# RDP Session API — system architecture

> Technical reference for the central API. The code remains the authority when implementation and documentation differ.

## 1. Purpose

RDP Session API centralizes Remote Desktop Services telemetry from one or more Windows servers. It accepts event streams and WTS snapshots from the companion Agent, persists raw and consolidated state, and exposes read-only JSON endpoints for dashboards and integrations.

The design separates **write credentials used by Agents** from **read credentials used by consumers**.

## 2. Repositories and responsibilities

| Repository | Responsibility |
|---|---|
| `RDP-Session-API` | FastAPI service, authentication, persistence, reconciliation, query endpoints, Linux deployment |
| `RDP-Session-Agent` | Windows Event Log collection, WTS snapshots, durable spool, Scheduled Task execution |

## 3. Context view

```mermaid
flowchart LR
    subgraph WindowsServers["Windows Servers"]
        S1["RDP Session Agent"]
        S2["RDP Session Agent"]
        SN["RDP Session Agent"]
    end

    subgraph ApiHost["Linux API Host"]
        Proxy["HTTPS Reverse Proxy"]
        API["FastAPI / Uvicorn :8091"]
        DB[("MariaDB / MySQL")]
    end

    Consumers["Grafana / API consumers"]

    S1 -->|"events + snapshots"| Proxy
    S2 -->|"events + snapshots"| Proxy
    SN -->|"events + snapshots"| Proxy
    Consumers -->|"X-API-Key + JSON"| Proxy
    Proxy --> API
    API --> DB
```

## 4. Trust boundaries

1. Agents authenticate with a server-specific `X-Server-ID` and Bearer secret.
2. Each monitored server receives an independent Agent credential.
3. The API stores only a hash of the Agent secret.
4. Read/query clients authenticate separately with `X-API-Key`.
5. Uvicorn is intended to stay on loopback behind a TLS reverse proxy.
6. Database credentials and query keys live outside the Git checkout.
7. TLS private keys and environment-specific proxy configuration are not repository content.

## 5. Internal components

```mermaid
flowchart TB
    Routers["FastAPI routers"] --> Services["Domain services"]
    Services --> State["Session state machine"]
    Services --> Reconcile["Snapshot reconciliation"]
    Services --> Models["SQLAlchemy models"]
    Models --> DB[("Database")]

    Auth["Agent + query authentication"] --> Routers
    Alembic["Alembic migrations"] --> DB
```

### API routers

Expose ingestion, health, server summary, active session, and history endpoints.

### Domain services

Apply idempotency, normalize timestamps, update consolidated state, and reconcile WTS observations.

### Persistence

The API uses dedicated SQLAlchemy models and Alembic migrations instead of writing to an unrelated application's database.

## 6. Main data model

```mermaid
erDiagram
    SERVER ||--o{ SERVER_CREDENTIAL : owns
    SERVER ||--o{ SESSION_EVENT : receives
    SERVER ||--o{ RDP_SESSION : consolidates

    SERVER {
        string id PK
        string hostname
        string fqdn
        string os_version
        string agent_version
        datetime last_seen_at
        datetime last_snapshot_at
        datetime last_boot_at
        boolean enabled
    }

    SERVER_CREDENTIAL {
        string id PK
        string server_id FK
        string token_hash
        datetime created_at
        datetime last_used_at
        datetime revoked_at
    }

    SESSION_EVENT {
        string id PK
        string server_id FK
        string event_type
        int event_id
        int event_record_id
        int windows_session_id
        string username
        datetime boot_time
        datetime occurred_at
        string event_fingerprint
    }

    RDP_SESSION {
        string id PK
        string server_id FK
        int windows_session_id
        string username
        string state
        datetime logon_at
        datetime logoff_at
        int disconnect_count
        int duration_minutes
        string end_reason
    }
```

## 7. Event ingestion flow

```mermaid
sequenceDiagram
    participant Agent as Windows Agent
    participant API as RDP Session API
    participant DB as Database

    Agent->>API: POST /agent/events
    API->>API: authenticate server
    API->>API: normalize boot/time values
    API->>DB: check event fingerprint
    alt event is new
        API->>DB: persist raw event
        API->>DB: update consolidated session
        API-->>Agent: accepted=1
    else duplicate
        API-->>Agent: duplicates=1
    end
```

Event fingerprinting makes replay safe when the Agent resends a locally spooled batch.

## 8. Snapshot reconciliation flow

```mermaid
sequenceDiagram
    participant Agent as Windows Agent / WTS
    participant API as RDP Session API
    participant DB as Database

    Agent->>API: POST /agent/snapshot
    API->>API: authenticate server
    API->>DB: compare observed sessions with open sessions
    API->>DB: create/update observed sessions
    API->>DB: close missing open sessions as RECONCILIATION
    API-->>Agent: observed / created / updated / closed
```

The snapshot is a current-state correction mechanism. It complements Event Log ingestion rather than replacing it.

## 9. Session state machine

```mermaid
stateDiagram-v2
    [*] --> ACTIVE: LOGON
    ACTIVE --> DISCONNECTED: DISCONNECT
    DISCONNECTED --> ACTIVE: RECONNECT
    ACTIVE --> CLOSED: LOGOFF
    DISCONNECTED --> CLOSED: LOGOFF
    ACTIVE --> CLOSED: RECONCILIATION
    DISCONNECTED --> CLOSED: RECONCILIATION
    ACTIVE --> CLOSED: REBOOT
    DISCONNECTED --> CLOSED: REBOOT
```

### End reasons

Typical terminal reasons include:

- `LOGOFF` — lifecycle event explicitly closed the session;
- `RECONCILIATION` — WTS no longer observed an open session;
- `REBOOT` — a different boot instance invalidated sessions from the previous boot.

## 10. Authentication model

```mermaid
flowchart LR
    Agent["RDP Session Agent"] -->|"X-Server-ID + Bearer secret"| Ingest["Write endpoints"]
    Consumer["Grafana / client"] -->|"X-API-Key"| Query["Read endpoints"]
    Ingest --> API["RDP Session API"]
    Query --> API
```

Agent credentials intentionally cannot be used to read global session history.

## 11. Deployment model

```mermaid
flowchart TB
    InternetOrLAN["Trusted network clients"] -->|HTTPS :443| Nginx["Reverse proxy"]
    Nginx -->|HTTP loopback| Uvicorn["systemd: rdp-session-api"]
    Uvicorn --> DB[("MariaDB / MySQL")]

    Env["/etc/rdp-session-api/rdp-session-api.env"] --> Uvicorn
    Systemd["systemd"] --> Uvicorn
    Systemd -->|ExecStartPre| Alembic["alembic upgrade head"]
```

The bundled systemd path provides:

- dedicated non-login service account;
- loopback-only Uvicorn bind;
- migration preflight;
- automatic restart;
- journald logging;
- basic service hardening.

## 12. Multi-server onboarding

For every additional Windows server:

1. register the server in the API;
2. receive its unique `server_id` and one-time secret;
3. install the companion Agent using those values;
4. validate `/servers/{server_id}/summary`;
5. repeat without sharing credentials between servers.

No API deployment change is required when adding another monitored server.

## 13. Grafana integration

Grafana is a read-only consumer of the API and can run on a separate host.

```mermaid
flowchart LR
    Grafana["Grafana Server"] -->|"HTTPS + X-API-Key"| Proxy["API Reverse Proxy"]
    Proxy --> API["RDP Session API"]
```

Useful dashboard sources include:

- server list;
- active users;
- active/disconnected/open session counts;
- active session table;
- session history.

The Grafana host must trust the certificate chain used by the API endpoint.
