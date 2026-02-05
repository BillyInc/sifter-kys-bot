.PHONY: help venv install install-dev run run-prod clean lint test \
        docker-build docker-run docker-stop docker-logs docker-shell docker-restart \
        pm2-start pm2-stop pm2-restart pm2-logs pm2-status pm2-setup

PYTHON := python3
VENV := .venv
BIN := $(VENV)/bin
IMAGE_NAME := sifter-backend
CONTAINER_NAME := sifter-backend
PORT := 8080

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

venv: ## Create virtual environment
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv $(VENV)
	@echo ""
	@echo "Virtual environment created. Activate with:"
	@echo "  source $(VENV)/bin/activate"

install: venv ## Install dependencies
	@echo "Installing dependencies..."
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	@echo ""
	@echo "Dependencies installed successfully."

install-dev: install ## Install dev dependencies
	@echo "Installing dev dependencies..."
	$(BIN)/pip install pytest black flake8 pyright
	@echo ""
	@echo "Dev dependencies installed."

run: ## Run development server
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	@echo "Starting development server..."
	$(BIN)/python app.py

run-prod: ## Run production server with gunicorn
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	@echo "Starting production server..."
	$(BIN)/gunicorn --bind 0.0.0.0:5000 --workers 4 app:app

lint: ## Run linters
	@echo "Running flake8..."
	$(BIN)/flake8 --max-line-length=100 --exclude=$(VENV) .
	@echo "Running pyright..."
	$(BIN)/pyright .

test: ## Run tests
	@echo "Running tests..."
	$(BIN)/pytest -v

clean: ## Remove virtual environment and cache files
	@echo "Cleaning up..."
	rm -rf $(VENV)
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

# PM2 targets
pm2-setup: install ## Setup PM2 and create logs directory
	@echo "Setting up PM2..."
	@mkdir -p logs
	@if ! command -v pm2 &> /dev/null; then \
		echo "PM2 not found. Install with: sudo npm install -g pm2"; \
		exit 1; \
	fi
	@echo "PM2 setup complete. Run 'make pm2-start' to start the server."

pm2-start: ## Start server with PM2
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	@mkdir -p logs
	pm2 start ecosystem.config.js
	@echo "Server started. Run 'make pm2-logs' to view logs."

pm2-stop: ## Stop PM2 server
	pm2 stop sifter-backend

pm2-restart: ## Restart PM2 server
	pm2 restart sifter-backend

pm2-logs: ## View PM2 logs
	pm2 logs sifter-backend

pm2-status: ## Show PM2 status
	pm2 list

pm2-delete: ## Remove from PM2
	pm2 delete sifter-backend

pm2-startup: ## Enable PM2 to start on boot
	pm2 startup
	pm2 save
	@echo "PM2 will now start on boot."
