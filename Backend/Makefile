.PHONY: help install install-dev run run-prod clean lint test format \
        docker-build docker-run docker-stop docker-logs docker-shell docker-restart \
        systemd-install systemd-start systemd-stop systemd-restart systemd-logs systemd-status

IMAGE_NAME := sifter-backend
CONTAINER_NAME := sifter-backend
PORT := 8080

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install dependencies (creates .venv via uv)
	@echo "Installing dependencies with uv..."
	uv sync
	@echo ""
	@echo "Dependencies installed. Run commands with 'uv run <cmd>'."

install-dev: ## Install with dev dependencies
	@echo "Installing with dev dependencies..."
	uv sync --extra dev
	@echo ""
	@echo "Dev dependencies installed."

run: ## Run development server
	@echo "Starting development server..."
	uv run python app.py

run-prod: ## Run production server with gunicorn
	@echo "Starting production server..."
	uv run gunicorn --bind 0.0.0.0:5000 --workers 4 app:app

lint: ## Run linters
	@echo "Running flake8..."
	uv run flake8 --max-line-length=100 --exclude=.venv .
	@echo "Running pyright..."
	uv run pyright .

test: ## Run tests
	@echo "Running tests..."
	uv run pytest -v

format: ## Format code with black
	@echo "Formatting with black..."
	uv run black .

clean: ## Remove virtual environment and cache files
	@echo "Cleaning up..."
	rm -rf .venv
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	rm -rf .pytest_cache
	rm -rf *.egg-info
	find . -type f -name "*.pyc" -delete
	@echo "Cleaned."

setup: install ## Alias for install
	@echo "Setup complete!"

# Docker targets
docker-build: ## Build Docker image
	@echo "Building Docker image..."
	docker build -t $(IMAGE_NAME) .

docker-run: ## Run Docker container
	@echo "Starting Docker container on port $(PORT)..."
	docker run -d \
		--name $(CONTAINER_NAME) \
		-p $(PORT):$(PORT) \
		-e PORT=$(PORT) \
		--env-file .env \
		$(IMAGE_NAME)
	@echo "Container started. Access at http://localhost:$(PORT)"

docker-stop: ## Stop and remove Docker container
	@echo "Stopping container..."
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)
	@echo "Container stopped."

docker-logs: ## Show Docker container logs
	docker logs -f $(CONTAINER_NAME)

docker-shell: ## Open shell in running container
	docker exec -it $(CONTAINER_NAME) /bin/bash

docker-restart: docker-stop docker-run ## Restart Docker container

# Systemd targets (production)
systemd-install: ## Install systemd service files (requires sudo)
	@echo "Installing systemd service files..."
	@mkdir -p logs
	sudo cp systemd/*.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable sifter-backend rq-worker@{1..5} wallet-monitor
	@echo "Systemd services installed. Run 'make systemd-start' to start."

systemd-start: ## Start all services
	@echo "Starting services..."
	sudo systemctl start sifter-backend
	sudo systemctl start rq-worker@{1..5}
	sudo systemctl start wallet-monitor
	@echo "Services started."

systemd-stop: ## Stop all services
	@echo "Stopping services..."
	sudo systemctl stop wallet-monitor
	sudo systemctl stop rq-worker@{1..5}
	sudo systemctl stop sifter-backend
	@echo "Services stopped."

systemd-restart: ## Restart all services
	@echo "Restarting services..."
	sudo systemctl reload-or-restart sifter-backend
	sudo systemctl restart rq-worker@{1..5}
	sudo systemctl restart wallet-monitor
	@echo "Services restarted."

systemd-logs: ## View service logs
	sudo journalctl -u sifter-backend -u 'rq-worker@*' -u wallet-monitor -f

systemd-status: ## Show service status
	@echo "=== Sifter Backend ==="
	@sudo systemctl status sifter-backend --no-pager || true
	@echo ""
	@echo "=== RQ Workers ==="
	@sudo systemctl status 'rq-worker@*' --no-pager || true
	@echo ""
	@echo "=== Wallet Monitor ==="
	@sudo systemctl status wallet-monitor --no-pager || true
