#!/bin/bash
# do_prediction.sh
# Ejecuta download_trained_model.py usando el venv local

# Activar venv
source ./venv/bin/activate

# Ejecutar el script Python
python ./data/download_trained_model.py

# Salir del venv al terminar
deactivate
