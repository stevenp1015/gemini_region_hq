#!/bin/bash
# start_legion.sh

# Start minion spawner in background
./scripts/spawn_minions.sh 3 &
SPAWNER_PID=$!

# Wait briefly for minions to initialize
sleep 3

# Start the GUI
python -m management_gui.gui_app

# When GUI exits, also kill the spawner
kill $SPAWNER_PID