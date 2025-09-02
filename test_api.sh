#!/bin/bash

echo "CLEANING PREVIOUS URLS AND USED PORTS"
fuser -k 5000/tcp 2>/dev/null
pkill ngrok 2>/dev/null

# ---------- START APP TEMPORARILY ----------
echo "STARTING APP TEMPORARILY TO APPLY CHANGES..."
python ~/Downloads/backend/app.py &
APP_PID=$!
sleep 5  # espera a que cargue

# ---------- KILL APP ----------
echo "KILLING APP TO RESTART..."
kill $APP_PID
sleep 2

# ---------- START TESTING SERVER ----------
echo "STARTING TESTING SERVER..."
python ~/Downloads/backend/app.py &
APP_PID=$!
sleep 5
curl "http://localhost:5000/test_signal?enabled=true"
echo -e "\n\n"

# ---------- START NGROK TUNNEL ----------
echo "STARTING NGROK TUNNEL..."
ngrok http 5000 --log=stdout > ngrok.log &
NGROK_PID=$!

NGROK_URL=""
while [ -z "$NGROK_URL" ]; do
    sleep 1
    NGROK_URL=$(grep "started tunnel" ngrok.log | grep -o 'https://[a-z0-9]*\.ngrok[^ ]*' | head -n 1)
done

echo $NGROK_URL > ngrok_link.txt
echo "NEW URL GENERATED: $NGROK_URL"
echo -e "\n\n"
echo "!! SERVER STILL RUNNING !!"
echo "Use 'ps aux | grep app.py' then 'kill <PID>' to stop it"
echo "Or to stop ngrok: kill $NGROK_PID"
