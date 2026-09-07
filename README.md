# Tibia Mapper

Aplicación local en Python + Flask para administrar rutinas, checkpoints visuales, eventos, Battle y configuración.

## Ejecutar en desarrollo

```powershell
pip install -r requirements.txt
python app.py
```

Luego abre `http://127.0.0.1:5000`.

## EXE portable para otro PC

El proyecto queda preparado para generar una distribución Windows x64 que **no necesita Python en el PC destino**.

La distribución es de tipo `onedir`: `tibia-mapper.exe` debe viajar junto con los archivos y carpetas generados por PyInstaller. No copies solamente el `.exe`; copia/descomprime el paquete completo.

### Opción 1: compilar en tu PC

En Windows:

```powershell
git pull
build_exe.bat
```

Al terminar tendrás:

```text
dist\tibia-mapper\
dist\tibia-mapper-windows-x64.zip
```

El ZIP es el archivo recomendado para pasar al otro PC.

### Opción 2: descargar el EXE generado por GitHub

El repositorio incluye el workflow:

```text
.github/workflows/build-windows-exe.yml
```

Cada `push` a `main` genera automáticamente el paquete Windows.

En GitHub:

1. Abre la pestaña **Actions**.
2. Entra a **Build Windows EXE**.
3. Abre la ejecución más reciente que terminó correctamente.
4. En **Artifacts**, descarga `tibia-mapper-windows-x64`.
5. Descomprime el ZIP descargado y luego descomprime `tibia-mapper-windows-x64.zip` si GitHub lo entrega dentro del artifact.

También puedes ejecutar el workflow manualmente con **Run workflow**.

## Pasarlo al otro PC

Copia o descomprime **toda** la carpeta portable y ejecuta:

```text
tibia-mapper.exe
```

El navegador se abre automáticamente en:

```text
http://127.0.0.1:5000
```

Los datos editables se guardan junto al ejecutable:

```text
routines\
events\
checkpoints\
battle_targets\
battle_targets\images\
data\
logs\
settings.json
```

Por eso puedes reemplazar los binarios de una versión futura conservando esas carpetas/archivos para mantener la configuración, rutinas, eventos y referencias Battle.

## Capturas NVIDIA en el PC destino

La aplicación no instala NVIDIA ni GeForce/NVIDIA App. El PC destino debe tener funcionando la captura de NVIDIA con `Alt+F1`, igual que el equipo de desarrollo.

La aplicación espera las capturas en la carpeta equivalente a:

```text
C:\Users\<usuario>\Videos\Desktop
```

Si NVIDIA guarda las capturas en otra ubicación, habrá que ajustar `capture_utils.py`.

## Archivos de empaquetado

- `tibia-mapper.spec`: configuración PyInstaller; incluye `templates/` y `static/`.
- `build_exe.bat`: compila y además crea `tibia-mapper-windows-x64.zip`.
- `.github/workflows/build-windows-exe.yml`: genera automáticamente el ZIP portable en Windows.
- `launcher.py`: inicia Flask y abre el navegador.
- `app_paths.py`: mantiene los datos persistentes junto al ejecutable cuando está empaquetado.

## Estructura principal

- `app.py`: servidor Flask y API.
- `launcher.py`: entrada para el EXE.
- `app_paths.py`: rutas compatibles con Python y PyInstaller.
- `routine_store.py`: persistencia de rutinas.
- `event_store.py`: persistencia de eventos.
- `battle_store.py`: referencias visuales de Battle.
- `battle_monitor.py`: detección y estado Battle.
- `checkpoint_store.py`: checkpoints visuales.
- `capture_utils.py`: capturas NVIDIA.
- `recorder.py`: grabación F11/F12.
- `mapper_store.py`: SQLite.
- `session_log.py`: logs.
- `templates/`: frontend HTML.
- `static/`: estilos y recursos web.
