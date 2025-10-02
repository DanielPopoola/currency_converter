#!/bin/bash

echo "Starting Rate Ingestor Worker..."
echo "Press Ctrl+C to stop"
echo ""

export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run the worker
python -m app.workers.rate_ingestor