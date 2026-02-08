# Sifter KYS

A full-stack Solana token analytics platform featuring Twitter caller analysis, professional wallet pump detection, real-time wallet activity monitoring, and Telegram alerts.

## Quick Start

```bash
# Start both backend and frontend
./start-dev.sh

# Backend: http://localhost:5000
# Frontend: http://localhost:5173
```

## Deployment

### GitHub Secrets Setup

The CI/CD pipeline (`deploy-backend.yml`) requires the following secrets to be configured in your GitHub repository:

| Secret | Description |
|--------|-------------|
| `SSH_PRIVATE_KEY` | SSH private key for server access |
| `SERVER_HOST` | Server hostname/IP address |
| `SERVER_USER` | SSH username for deployment |
| `ENV_FILE` | Full contents of Backend `.env` file |

**To add secrets via GitHub UI:**

1. Go to https://github.com/peterpsam/sifter-kys-bot/settings/secrets/actions
2. Click "New repository secret" for each one

**Or use the GitHub CLI:**

```bash
gh secret set SSH_PRIVATE_KEY < ~/.ssh/your_deploy_key
gh secret set SERVER_HOST -b "your.server.com"
gh secret set SERVER_USER -b "deploy_user"
gh secret set ENV_FILE < Backend/.env
```

## Development

See [CLAUDE.md](./CLAUDE.md) for detailed development commands and architecture documentation.
