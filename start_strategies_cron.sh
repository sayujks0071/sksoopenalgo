#!/bin/bash
# Automate OpenAlgo Strategy Launch
# This script is intended to be run by cron

# Set the project directory (Absolute path)
PROJECT_DIR="/Users/mac/openalgo"
cd "$PROJECT_DIR" || exit 1

# Log file
LOG_FILE="$PROJECT_DIR/cron_launch.log"

echo "==================================================" >> "$LOG_FILE"
echo "Check Triggered at $(date)" >> "$LOG_FILE"

# Ensure we have the right path
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Run the python script
# Using '--all' to force start if we are close to the window, 
# but relying on internal logic is better if running exactly at start time.
# However, to be safe against minute-mismatches, we run it 'as is' 
# assuming 09:15 cron hits 09:15 schedule.

echo "Running start_all_strategies.py..." >> "$LOG_FILE"
python3 openalgo/start_all_strategies.py >> "$LOG_FILE" 2>&1

echo "Finished at $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
