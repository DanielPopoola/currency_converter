#!/bin/bash

# Script to run the FastAPI server

echo "Starting FastAPI Server..."
echo "API will be available at http://localhost:8000"
echo "Docs at http://localhost:8000/docs"
echo ""

# Activate virtual environment if needed
# source venv/bin/activate

# Set Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run FastAPI with uvicorn
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload