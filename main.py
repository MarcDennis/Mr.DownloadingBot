from fastapi import FastAPI
from pydantic import BaseModel
import os
import uuid
import shutil
import requests
import yt_dlp

app = FastAPI()

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8575552994:AAHQMGA2e_COpgGclg5hD_223ggTVeTYWeI"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class DownloadRequest(BaseModel):
    url: str
    chat_id: str
    reply_to_message_id: str = ""


def clean_filename(name: str) -> str:
    bad = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for ch in bad:
        name = name.replace(ch, "")
    return name[:120].strip()


def send_message(chat_id: str, text: str, reply_to_message_id: str = ""):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_to_message_id:
        try:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        except:
            pass

    requests.post(
        f"{TG_API}/sendMessage",
        data=payload,
        timeout=60
    )


def send_video(chat_id: str, file_path: str, caption: str, reply_to_message_id: str = ""):
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "supports_streaming": True
    }

    if reply_to_message_id:
        try:
            data["reply_to_message_id"] = int(reply_to_message_id)
        except:
            pass

    with open(file_path, "rb") as f:
        requests.post(
            f"{TG_API}/sendVideo",
            data=data,
            files={"video": f},
            timeout=600
        )


def send_document(chat_id: str, file_path: str, caption: str, reply_to_message_id: str = ""):
    data = {
        "chat_id": chat_id,
        "caption": caption
    }

    if reply_to_message_id:
        try:
            data["reply_to_message_id"] = int(reply_to_message_id)
        except:
            pass

    with open(file_path, "rb") as f:
        requests.post(
            f"{TG_API}/sendDocument",
            data=data,
            files={"document": f},
            timeout=600
        )


@app.get("/")
def root():
    return {"ok": True, "message": "Mr Downloading Bot API is running"}


@app.post("/download")
def download_media(data: DownloadRequest):
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(DOWNLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        ydl_opts = {
            "outtmpl": os.path.join(task_dir, "%(title).120s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4"
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(data.url, download=True)

        if not info:
            send_message(
                data.chat_id,
                "Failed to fetch this media.\n\n@MrDownloadingBot",
                data.reply_to_message_id
            )
            return {"ok": False, "message": "Failed to fetch media"}

        title = clean_filename(info.get("title", "Downloaded Media"))
        uploader = info.get("uploader", "Unknown")

        # Find downloaded file
        files = []
        for root, dirs, filenames in os.walk(task_dir):
            for fn in filenames:
                files.append(os.path.join(root, fn))

        if not files:
            send_message(
                data.chat_id,
                "No downloadable file was found.\n\n@MrDownloadingBot",
                data.reply_to_message_id
            )
            return {"ok": False, "message": "No file found"}

        # Pick largest file
        files.sort(key=lambda x: os.path.getsize(x), reverse=True)
        final_file = files[0]

        caption = (
            f"{title}\n\n"
            f"Source: {uploader}\n"
            f"-@MrDownloadingBot"
        )

        ext = os.path.splitext(final_file)[1].lower()

        # Send as video if common video format
        if ext in [".mp4", ".mov", ".m4v", ".webm"]:
            send_video(data.chat_id, final_file, caption, data.reply_to_message_id)
        else:
            send_document(data.chat_id, final_file, caption, data.reply_to_message_id)

        return {"ok": True, "message": "Done! Downloaded."}

    except Exception as e:
        send_message(
            data.chat_id,
            "Failed to download.\n\nMake Sure the link is Public and Supported.\n-@MrDownloadingBot",
            data.reply_to_message_id
        )
        return {"ok": False, "message": str(e)}

    finally:
        try:
            shutil.rmtree(task_dir)
        except:
            pass
