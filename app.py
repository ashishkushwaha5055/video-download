import os
import re
import tempfile
from flask import Flask, render_template, request, jsonify, send_file
from yt_dlp import YoutubeDL

app = Flask(__name__)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def get_media_info(url):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def list_video_formats(info):
    resolutions = {}
    for f in info.get("formats", []):
        if f.get("vcodec") != "none" and f.get("height"):
            height = f["height"]
            if height not in resolutions or f.get("tbr", 0) > resolutions[height].get("tbr", 0):
                resolutions[height] = f
    return resolutions

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/get_info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        info = get_media_info(url)
        is_playlist = info.get("_type") == "playlist" or info.get("entries") is not None

        if is_playlist:
            return jsonify({"error": "Playlist downloading is disabled on cloud deployment due to timeout limits. Please use single video links."}), 400
        else:
            title = info.get("title", "YouTube Video")
            duration = info.get("duration")
            
            with YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                full_info = ydl.extract_info(url, download=False)
            
            formats = list_video_formats(full_info)
            available_res = []
            for h in sorted(formats.keys(), reverse=True):
                size = formats[h].get("filesize") or formats[h].get("filesize_approx")
                size_str = f" (~{round(size / (1024 * 1024), 2)} MB)" if size else ""
                available_res.append({"height": h, "label": f"{h}p{size_str}"})

            return jsonify({
                "type": "video",
                "title": title,
                "duration": duration,
                "resolutions": available_res,
                "url": url
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    media_type = data.get("type")
    resolution = data.get("resolution")

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        tmp_dir = tempfile.mkdtemp()
        
        if media_type == "mp3":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
                ],
                "quiet": True,
            }
        elif media_type == "mp4":
            res = int(resolution) if resolution else 720
            format_string = f"bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={res}]+bestaudio/best[height<={res}]"
            ydl_opts = {
                "format": format_string,
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(tmp_dir, "%(title)s_%(height)sp.%(ext)s"),
                "quiet": True,
            }
        else:
            return jsonify({"error": "Invalid media type"}), 400

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info_dict)
            
            if media_type == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"

        if not os.path.exists(filename):
            files = os.listdir(tmp_dir)
            if not files:
                return jsonify({"error": "Download failed, file not found."}), 500
            filename = os.path.join(tmp_dir, files[0])

        return send_file(filename, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
