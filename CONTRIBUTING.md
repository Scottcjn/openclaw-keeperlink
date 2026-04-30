# Contributing to openclaw-keeperlink

openclaw-keeperlink enables P2P agent jobs that settle onchain — post over AXL, pay via x402, execute via KeeperHub, swap on Uniswap, and persist receipts on 0G.

## Project Structure

```
openclaw-keeperlink/
├── docs/           # Architecture and API documentation
├── node-a/         # Agent node A (initiator)
├── node-b/         # Agent node B (worker)
├── scripts/        # Deployment and utility scripts
├── shared/         # Shared libraries between nodes
├── skills/         # Agent skill definitions
├── ARCHITECTURE.md # Full system architecture
├── FEEDBACK.md     # User feedback and feature requests
└── docker-compose.yml
```

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Access to AXL token for job posting
- x402 payment endpoint configuration
- KeeperHub agent account

### Setup

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink.git
cd openclaw-keeperlink
cp .env.example .env
# Configure .env with your keys and endpoints
docker-compose up
```

### Running Nodes

```bash
# Start both nodes
docker-compose up -d

# View logs
docker-compose logs -f

# Stop nodes
docker-compose down
```

## Architecture Overview

The system uses a two-node design:

1. **node-a** (Initiator) — Posts job requests over AXL, handles payment via x402
2. **node-b** (Worker) — Executes jobs via KeeperHub, returns results and receipts

Payment flow:
```
Initiator -> AXL posting -> x402 payment -> KeeperHub execution -> Uniswap swap -> 0G persistence
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full details.

## Making Changes

1. **Fork** the repository
2. **Create a feature branch**: `git checkout -b feat/<feature-name>`
3. **Make your change** — prefer shared library changes in `shared/` over duplicating in nodes
4. **Test locally** with `docker-compose up`
5. **Submit a PR**

## Code Standards

- **Shared libraries first** — put common logic in `shared/`, not in individual nodes
- **Environment-based config** — no hardcoded values; use `.env`
- **Idempotent scripts** — scripts should be safe to re-run
- **Docker best practices** — minimize layer size, use multi-stage builds where applicable

## Testing

```bash
# Full integration test
docker-compose -f docker-compose.yml -f docker-compose.test.yml up --abort-on-container-exit

# Unit tests only
docker-compose exec node-a pytest tests/

# Manual smoke test
docker-compose exec node-a python scripts/smoke_test.py
```

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
