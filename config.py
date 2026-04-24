import os
import platform
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
HF_API_KEY        = os.getenv("HF_API_KEY", "")
YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY", "")
TWITTER_BEARER    = os.getenv("TWITTER_BEARER_TOKEN", "")
NEWS_API_KEY      = os.getenv("NEWS_API_KEY", "")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/tmp/wat-video-output")

W, H = 1080, 1920
FPS  = 24

VOICES = {
    "ja": "ja-JP-NanamiNeural",
    "en": "en-US-AriaNeural",
    "es": "es-MX-DaliaNeural",
}

SUPPORTED_LANGUAGES = list(VOICES.keys())

COLORS = {
    "W": (255, 80,  40),
    "A": (80,  160, 255),
    "T": (80,  220, 120),
}

if platform.system() == "Windows":
    FONT_BOLD   = "C:/Windows/Fonts/arialbd.ttf"
    FONT_NORMAL = "C:/Windows/Fonts/arial.ttf"
else:
    FONT_BOLD   = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    FONT_NORMAL = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
