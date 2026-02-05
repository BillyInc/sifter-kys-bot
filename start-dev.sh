#!/bin/bash

# Start both frontend and backend for development

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Sifter KYS Development Servers${NC}"
echo "========================================"

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down servers...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Start Backend
echo -e "\n${GREEN}[1/2] Starting Backend...${NC}"
cd "$SCRIPT_DIR/Backend"

if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Backend virtual environment not found.${NC}"
    echo "Run 'make install' in the Backend directory first."
    exit 1
fi

.venv/bin/python app.py &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait a moment for backend to start
sleep 2

# Start Frontend
echo -e "\n${GREEN}[2/2] Starting Frontend...${NC}"
cd "$SCRIPT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    pnpm install
fi

pnpm run dev &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

echo -e "\n${GREEN}========================================"
echo -e "Servers started!"
echo -e "  Backend:  http://localhost:5000"
echo -e "  Frontend: http://localhost:5173"
echo -e "========================================${NC}"
echo -e "\nPress Ctrl+C to stop both servers\n"

# Wait for both processes
wait
