from dotenv import load_dotenv
import os
import cloudinary
import cloudinary.api
import requests

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("CLOUD_API_KEY"),
    api_secret=os.getenv("CLOUD_API_SECRET")
)

folder_local = "./"
os.makedirs(folder_local, exist_ok=True)
cloud_folder = "githubRepo-Ecg-Proyecto"

# ---------------- Descarga SOLO predicted_data.csv ----------------
def download_from_cloudinary(public_id, local_path):
    try:
        resource = cloudinary.api.resource(public_id, resource_type="raw")
        url = resource['url']
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:  # 👈 siempre reemplaza el archivo
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            print(f"[OK] Downloaded/Updated: {local_path}")
        else:
            print(f"[ERROR] Failed to download {public_id}: HTTP {r.status_code}")
    except Exception as e:
        print(f"[ERROR] Downloading {public_id}: {e}")

# ---------------- Verificar si el entrenamiento terminó ----------------
try:
    # Endpoint que devuelve el JSON con status
    status_url = "http://qm1n4mn1-3333.brs.devtunnels.ms"  
    resp = requests.get(status_url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # Acceder al campo exacto
    received = data.get("receivedMessage", {})
    if received.get("status") == "completed":
        print("[INFO] Entrenamiento completado. Descargando predicted_data.csv...")

        file_name = "predicted_data.csv"
        local_path = os.path.join(folder_local, file_name)
        public_id = f"{cloud_folder}/{file_name}"

        download_from_cloudinary(public_id, local_path)
    else:
        print("[INFO] Entrenamiento aún no completado. No se descarga nada.")

except Exception as e:
    print(f"[ERROR] No se pudo verificar el estado del entrenamiento: {e}")
