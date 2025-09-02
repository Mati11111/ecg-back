# Scripts
La mayor cantidad de scripts estan controlados mediante pm2, a continuacion se adjuntan los scripts utilizados en caso de ser requeridos.

## COMANDOS RELEVANTES
Comandos generalmente utilizados en pm2.

### LISTAR PROCESOS
```bash
pm2 list
```
### VISUALIZAR PROCESO
```bash
pm2 log <ID>
```
### DETENER PROCESO
```bash
pm2 kill <ID>
```

## UPDATE FRONT-ECG
Este script mantiene el raspberry con el url de ngrok actualizado, espera constantenmente a que el backend dentro del raspberry cambie el url mencionado, lo recoge y lo envia en formato .txt para el frontend con un push, finalmente limpia el archivo y sigue esperando. El frontend esta esperando con un webhook de github.

### EJECUCION
```bash
pm2 start ./update_front.sh --name 'Update front-ecg' 
```
### DETENER PROCESO
```bash
pm2 stop <ID>
```

## RUN BACKEND-ECG
Este script ejecuta el backend como tal, utiliza el archivo **app.py** como main, es el servidor y se debe ejecutar solo una vez y con **--no-autorestart** para no crear multiples instancias. Para finalizar el proceso revisar log y usar `kill <UID>` con la UID mostrada para eliminar proceso

### EJECUCION
```bash
pm2 start ./test_api.sh --name 'Run backend-ecg' --no-autorestart
```
### DETENER PROCESO
```bash
pm2 kill <ID>
```

### TRAINING MODEL TIMER
Script encargado de cambiar entre true/false dentro de endpoint /newData. Esto indica al dispositivo que entrena al modelo si hay que entrenar al modelo o no, por defecto espera durante 5 dias.
### EJECUCION
```bash
pm2 start ./toggle_newData.sh --name 'Run newData Timer'
```
### DETENER PROCESO
```bash
pm2 stop <ID>
```

### DOWNLOAD PREDICTION
Script que activa un entorno de venv que ejecuta un codigo que descarga la informacion generada por el dispositivo de entrenamiento del modelo desde cloudinary. Este codigo en python esta escuchando constantemente el url del dispositivo de entrenamiento expuesto, esperando la confirmacion para realizar la descarga.
### EJECUCION
```bash
pm2 start ./do_prediction.sh --name 'Run get prediction'
```
### DETENER PROCESO
```bash
pm2 stop <ID>
```
