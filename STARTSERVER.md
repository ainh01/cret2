# Start VTask Cret

## Start from PowerShell

Open PowerShell or the VS Code terminal and run:

```powershell
cd C:\Users\TBI9HC\Desktop\dev\MECURY25
conda run --no-capture-output -n vtask-cret python -m uvicorn app:app --host 0.0.0.0 --port 3003
```

Wait for `Application startup complete` and `Uvicorn running on http://0.0.0.0:3003`.
Keep this terminal open while using the app.

Open:

- One-shot: http://localhost:3003/
- Auto mode: http://localhost:3003/automode
- Settings: http://localhost:3003/setting

## Start using VS Code

1. Open this project folder in VS Code.
2. Select **Terminal → Run Task**.
3. Select **Run VTask Cret**.

This task uses the same Conda environment and port as the command above.

## Stop or restart

Press **Ctrl+C** in the server terminal to stop it. Run the startup command or task again to restart.

If port 3003 is already in use, check whether the app is already running at the URLs above. Stop the existing server before starting another instance on the same port.

## Environment setup (only if needed)

The existing project uses the Conda environment `vtask-cret`. If it is missing, create it and install the dependencies from the project folder:

```powershell
conda create -n vtask-cret python=3.12 pip -y
conda run -n vtask-cret python -m pip install -r requirements.txt
```

If the environment exists but dependencies are missing, run only the installation command.

Configure the API endpoint and key through the Settings page. The app saves these in the project's `.env` file, along with the global streaming preference (enabled by default).

AI requests use the proxy `http://127.0.0.1:3128` by default. Ensure it is running, or configure `PROXY` in `.env` and restart the server. Set `PROXY=` to use a direct connection.

File import uses MarkItDown with the document, audio and YouTube extras installed from `requirements.txt`
(`pptx`, `docx`, `xlsx`, `xls`, `pdf`, `audio-transcription`, `youtube-transcription`). Some audio
conversions additionally require FFmpeg. Images are not converted or OCR'd: the browser reads them as
data URLs and they are sent straight to the model.