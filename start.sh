#!/bin/bash
# Starts both the trading bot and the dashboard in the same service.
# Used when Railway doesn't allow volume sharing between services.

python dashboard/app.py &
python main.py
