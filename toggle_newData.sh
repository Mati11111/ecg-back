#!/bin/bash

FILE="newDataStatus.txt"

while true; do
  # poner en true
  echo '{ "newData": "true" }' > "$FILE"
  echo "[$(date)] Se cambió a true"
  
  # esperar 1 minuto
  sleep 60
  
  # volver a false
  echo '{ "newData": "false" }' > "$FILE"
  echo "[$(date)] Se cambió a false"
  
  # esperar 5 días (5 × 24 × 60 × 60 = 432000 segundos)
  sleep 432000
done
