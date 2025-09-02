#!/bin/bash

echo "Esperando a que ngrok_link.txt tenga contenido..."
while [ ! -s ~/Downloads/backend/ngrok_link.txt ]; do
        sleep 1
done
echo "ngrok_link.txt detectado."

# === FRONTEND ===
echo "Copiando ngrok_link.txt al frontend..."
mkdir -p ~/Downloads/ecg-front/src/assets
cp ~/Downloads/backend/ngrok_link.txt ~/Downloads/ecg-front/src/assets/
echo "Archivo copiado al frontend."

echo "Entrando al repositorio frontend..."
cd ~/Downloads/ecg-front

echo "Asignando credenciales..."
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa_ecg

echo "Descargando cambios..."
git pull
echo "Repositorio frontend actualizado."

echo "Agregando archivo al staging area..."
git add ./src/assets/ngrok_link.txt

echo "Haciendo commit..."
git commit -m "BACKEND MODIFIED --> URL CHANGED"
echo "Commit realizado."

echo "Haciendo push al repositorio frontend..."
git push origin master
echo "Push completado."

# === ECG-ARRHYTHMIA-CATEGORIZATOR ===
echo "Copiando ngrok_link.txt al ECG-Arrhythmia-Categorizator-..."
mkdir -p ~/Downloads/ECG-Arrhythmia-Categorizator-/src/assets
cp ~/Downloads/backend/ngrok_link.txt ~/Downloads/ECG-Arrhythmia-Categorizator-/src/assets/
echo "Archivo copiado al ECG-Arrhythmia-Categorizator-."

echo "Entrando al repositorio ECG-Arrhythmia-Categorizator-..."
cd ~/Downloads/ECG-Arrhythmia-Categorizator-

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa_categorizator

echo "Descargando cambios..."
git pull
echo "Repositorio ECG-Arrhythmia-Categorizator- actualizado."

echo "Agregando archivo al staging area..."
mv ./src/assets/ngrok_link.txt ./processing_data/ngrok_link.txt
git add ./processing_data/ngrok_link.txt

echo "Haciendo commit..."
git commit -m "BACKEND MODIFIED --> URL CHANGED"
echo "Commit realizado."

echo "Haciendo push al repositorio ECG-Arrhythmia-Categorizator-..."
git push origin main
echo "Push completado."

# === LIMPIEZA FINAL ===
echo "Vaciando ngrok_link.txt en backend..."
> ~/Downloads/backend/ngrok_link.txt
echo "Archivo vaciado."

echo "✅ FRONTEND & ECG-ARRHYTHMIA-CATEGORIZATOR NEW URL SENT ✅"
