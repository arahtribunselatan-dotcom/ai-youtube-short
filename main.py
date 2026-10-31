import os
import re
import json
import asyncio
import subprocess
from pathlib import Path

from google import genai
import edge_tts
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output")
OUT.mkdir(exist_ok=True)

MODEL = "gemini-3.8-flash"
VOICE = "en-US-GuyNeural"


def generate_script():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = """
Create one original YouTube Shorts science fact video.
Topic: Amazing science and psychology facts.
Audience: Global English-speaking viewers.
Duration: 30-45 seconds.
Use an exciting opening hook and simple English.
Use accurate, cautious scientific claims.
Avoid fake facts and exaggerated claims.

Return ONLY valid JSON:
{
 "title": "short title",
 "narration": "complete voiceover script",
 "description": "short video description"
}
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    data = json.loads(raw)

    for key in ("title", "narration", "description"):
        if not data.get(key):
            raise ValueError(f"Missing field: {key}")

    return data


def make_background(title):
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h))
    pixels = img.load()

    for y in range(h):
        for x in range(w):
            glow = max(0, 1 - abs(x - 800) / 900)
            pixels[x, y] = (
                int(8 + glow * 12),
                int(15 + (y / h) * 12),
                int(35 + glow * 65)
            )

    draw = ImageDraw.Draw(img)

    draw.ellipse((650, 200, 1250, 800), outline=(45, 95, 180), width=8)
    draw.ellipse((-250, 1100, 500, 1850), outline=(35, 85, 145), width=10)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 65)

    words = title.upper().split()
    lines, line = [], ""

    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] > 900:
            lines.append(line)
            line = word
        else:
            line = test

    if line:
        lines.append(line)

    y = 690
    for line in lines[:4]:
        draw.text((90, y), line, font=font, fill="white")
        y += 100

    img.save(OUT / "background.png")


def make_subtitles(text, duration):
    words = text.split()
    chunks = [
        " ".join(words[i:i + 6])
        for i in range(0, len(words), 6)
    ]

    total = sum(len(c.split()) for c in chunks)
    current = 0
    entries = []

    def stamp(seconds):
        ms = int(seconds * 1000)
        hh, ms = divmod(ms, 3600000)
        mm, ms = divmod(ms, 60000)
        ss, ms = divmod(ms, 1000)
        return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"

    for i, chunk in enumerate(chunks, 1):
        start = duration * current / total
        current += len(chunk.split())
        end = duration * current / total

        entries.append(
            f"{i}\n{stamp(start)} --> {stamp(end)}\n{chunk}\n"
        )

    (OUT / "captions.srt").write_text(
        "\n".join(entries), encoding="utf-8"
    )


async def make_voice(text):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(OUT / "voice.mp3"))


def get_duration():
    result = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(OUT / "voice.mp3")
    ])
    return float(result.decode().strip())


def render_video(duration):
    subtitles = str(OUT / "captions.srt").replace("\\", "/")

    vf = (
        "scale=1080:1920,"
        "zoompan=z='min(zoom+0.0003,1.08)':"
        "d=1:s=1080x1920:fps=30,"
        f"subtitles={subtitles}:"
        "force_style='FontName=DejaVu Sans,"
        "FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,"
        "Outline=3,Shadow=1,Alignment=2,MarginV=180'"
    )

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(OUT / "background.png"),
        "-i", str(OUT / "voice.mp3"),
        "-vf", vf,
        "-t", str(duration),
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        str(OUT / "short.mp4")
    ], check=True)


def main():
    print("Generating AI script...")
    data = generate_script()

    print("Generating voice...")
    asyncio.run(make_voice(data["narration"]))

    duration = get_duration()
    make_background(data["title"])
    make_subtitles(data["narration"], duration)

    print("Rendering video...")
    render_video(duration)

    (OUT / "metadata.json").write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

    print("SUCCESS: output/short.mp4 created!")


if __name__ == "__main__":
    main()
