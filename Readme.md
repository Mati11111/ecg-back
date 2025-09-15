# Endpoints
## Health
Muestra el estado del servidor.
```
/health
```
### Respuesta esperada
```json
{
  "ok": true,
  "samples_in_memory": 300,
  "writing": false,
  "last_known_port": null,
  "baudrate": 115200,
  "hr_detector": "simple_threshold",
  "buffer_ecg": 0,
  "buffer_bpm": 0,
  "umbral": 400,
  "refract_sec": 0.3,
  "ws_clients": 0,
  "test_signal": {
    "enabled": true,
    "freq": 1,
    "amp": 800,
    "offset": 0
  }
}
```

## Ecg 
Muestra los datos ecg provenientes del aruduino.
```
/ecg
```
### Respuesta esperada
```json
[
  {
    "timestamp": "2025-08-31 22:56:58.922",
    "value": -794
  },
]
```

## Bpm 
Muestra los datos bpm provenientes del aruduino.
```
/bpm
```
### Respuesta esperada
```json
{
  "bpm": 60,
  "timestamp": "2025-08-31 22:58:24.236"
}
```

## Test signal 
Activa/desactiva modo senoide y ajusta parameteros. Al activarse, la lectura por serial se ignora y se envian valores senoidales a WS y DB.

Puede ajustar parametros *freq* , *amp* y *offset*.
```
/test_signal?enabled=<parameter>
```
### Ejemplo de uso
```
/test_signal?enabled=true
```

### Respuesta esperada
```json
{
  "ok": true,
  "test_signal": {
    "enabled": true,
    "freq": 1,
    "amp": 800,
    "offset": 0
  }
}
```

## Database info
Muestra data relevante de la base de datos.
```
/db/info
```
### Respuesta esperada
```json
{
  "name": "ecg_data.db",
  "path": "/home/pi/Downloads/backend/data/ecg_data.db",
  "size_bytes": 16384,
  "modified": "2025-08-27 15:21:21"
}
```

## Database set
Cambia la base de datos activa mediante *?name=*
```
/db/set
```

### Ejemplo de uso
```
/db/set?name=<test>
```

### Respuesta esperada
```json
{
    "ok": true,
    "db_name": "test.db",
    "path": "/home/pi/Downloads/backend/data/test.db"
}
```

## Database list
Lista todos los .db en DATA_DIR con tamaño y fecha.
```
/db/list
```
### Respuesta esperada
```json
[
  {
    "name": "ecg_data.db",
    "size_bytes": 16384,
    "modified": "2025-08-27 15:21:21"
  }
]
```

## Database export
Exporta la DB indicada a CSV por streaming
```
/db/export
```
### Ejemplos de uso

```
/db/export?name=archivo.db&table=ecg

/db/export?name=archivo.db&table=bpm
```

### Respuesta esperada
```json
{
  "ok": false,
  "error": "DB no encontrada"
}
```

## Activar Escritura
Activa/desactiva escritura en BD, estado puede ser on/off.
```
/activar_escritura/{estado}
```
### Respuesta esperada
```json
{
  "escritura_activada": false
}
```

## Enviar Estado de Entrenamiento
Envia estado de entrenamiento a dispositivo de entrenamiento para entrenar modelo, puede mostrar true o false para realizar entrenamiento, deberia cambiar semanalmente por defecto.
```
/newData
```
### Respuesta esperada
```json
{
  "newData": false
}
```

## Verificar Estado de Entrenamiento
Luego de usar el endpoint */newData*, se espera respuesta del servidor de entrenamiento para descargar datos con la respuestas.

** *En un principio se utilzo para descargar el modelo entrenado y utilizarlo en el dispositivo del backend, finalmente se descarta para reducir el trabajo del raspberry* **

### Respuesta esperada
```json
{
  "ok": false,
  "error": "404 Client Error: Not Found for url: https://qm1n4mn1-3333.brs.devtunnels.ms/"
}
```

## Resultados de Prediccion Sistema Predictor a Backend
Muestra un arreglo con los resultados de la prediccion realizados, enviados al backend para luego se redireccionados al fron, se muestran 187 segementos siendo el utlimo valor la clase predicha.
```
/predictedData
```

** *Actualmente se recibe la prediccion realizada desde el serivdor de entrenamiento* **

### Respuesta esperada
```json
[
  {
    "0": 1,
    "1": 0.961092,
    "2": 0.914343,
    "3": 0.875486,
    ...
    "186": 0.777508,
    "Predicted_Class": 0
  }
]
```

## Resultados de Prediccion Backend a Frontend
Esta informacion generada por el sistema predictor es procesada por el backend y enviada al frontend a traves de este endpoint, es realizado de esta manera ya que solo el backend tiene acceso al front.

```
/sendPrediction
```

### Respuesta esperada
```json
(WIP)
```

## Realizar Prediccion
Endpoint utilizado para recibir señal de boton RUN en frontend, activa  la prediccion en el backend

```
/doPrediction
```

### Respuesta esperada
```json
(WIP)
```

## Status de Entrenamiento
Enpoint que comunica el backend con el sistema predictor, verifica si la prediccion fue, solicitada, finalizada, pendiente, etc. Esto es fundamental para que se realice el entrenamiento al momento de pulsar el boton RUN.

```
/checkTrainingStatus
```

### Respuesta esperada
```json
(WIP)
```
