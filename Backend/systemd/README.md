# Systemd Service Files

Production-ready systemd service files for running Sifter backend services.

## Services

| Service | Description | Port |
|---------|-------------|------|
| `sifter-backend` | Flask API via Gunicorn (4 workers) | 5000 |
| `rq-worker@{1..5}` | RQ background workers (template) | - |
| `wallet-monitor` | Real-time wallet activity monitor | - |

## Installation

```bash
# Copy service files to systemd
sudo cp *.service /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable sifter-backend
sudo systemctl enable rq-worker@{1..5}
sudo systemctl enable wallet-monitor
```

## Usage

### Start all services
```bash
sudo systemctl start sifter-backend
sudo systemctl start rq-worker@{1..5}
sudo systemctl start wallet-monitor
```

### Check status
```bash
sudo systemctl status sifter-backend
sudo systemctl status rq-worker@1
sudo systemctl status wallet-monitor
```

### View logs
```bash
# Follow logs in real-time
sudo journalctl -u sifter-backend -f
sudo journalctl -u rq-worker@1 -f
sudo journalctl -u wallet-monitor -f

# View all sifter logs
sudo journalctl -u 'sifter-*' -u 'rq-worker@*' -f
```

### Restart services
```bash
sudo systemctl restart sifter-backend
sudo systemctl restart rq-worker@{1..5}
sudo systemctl restart wallet-monitor
```

### Stop all services
```bash
sudo systemctl stop wallet-monitor
sudo systemctl stop rq-worker@{1..5}
sudo systemctl stop sifter-backend
```

## Scaling RQ Workers

The `rq-worker@.service` is a template unit. Scale workers by starting more instances:

```bash
# Start 5 workers
sudo systemctl start rq-worker@{1..5}

# Add more workers
sudo systemctl start rq-worker@6
sudo systemctl start rq-worker@7

# Stop specific worker
sudo systemctl stop rq-worker@3
```

## Configuration

### Gunicorn Workers

Edit `sifter-backend.service` to adjust worker count:
- Formula: `(2 x CPU cores) + 1`
- 2 CPU cores = 5 workers
- 4 CPU cores = 9 workers

### Environment Variables

Services read from `/home/ubuntu/sifter-backend/.env`. Ensure this file exists with:
```
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
BIRDEYE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
REDIS_URL=redis://localhost:6379
```

## Troubleshooting

### Service won't start
```bash
# Check logs for errors
sudo journalctl -u sifter-backend -n 50 --no-pager

# Verify paths exist
ls -la /home/ubuntu/sifter-backend/.venv/bin/gunicorn
ls -la /home/ubuntu/sifter-backend/.env
```

### Permission denied
```bash
# Fix ownership
sudo chown -R ubuntu:ubuntu /home/ubuntu/sifter-backend

# Create logs directory
mkdir -p /home/ubuntu/sifter-backend/logs
```

### Graceful reload (zero downtime)
```bash
sudo systemctl reload sifter-backend
```
