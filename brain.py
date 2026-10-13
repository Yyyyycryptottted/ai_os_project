Python
import os
from dotenv import load_dotenv

load_dotenv()
import difflib
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid


import pygame
import speech_recognition as sr
from google import genai
from google.genai import types  # NEW: Required for Agent Function Calling
from gtts import gTTS

from PIL import ImageGrab
import pyautogui
import psutil

# ----------------------------------------------------------------------------
# CONFIG (persisted in config.json next to this file)
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "name": "jarvis",
    "model": "gemini-3.5-flash-lite", 
    "stt_language": "en-US",
    "follow_up_seconds": 8,
    "wake_sensitivity": 0.75,
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg

def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        print(f"Could not save config: {e}", flush=True)

config = load_config()

# ----------------------------------------------------------------------------
# AGENT TOOLS (Function Calling)
# ----------------------------------------------------------------------------
def execute_save_note(filename: str, content: str):
    """Physically writes a text file to the user's Desktop."""
    # Tell the Electron UI to open the Notes app for visual effect
    print("COMMAND:OPEN_NOTEPAD", flush=True) 
    
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    if not filename.endswith(".txt"):
        filename += ".txt"
        
    filepath = os.path.join(desktop_path, filename)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully saved to {filepath}"
    except Exception as e:
        return f"Failed to save file: {str(e)}"

# Tell Gemini exactly what this tool does and what arguments it needs
desktop_writer_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="save_note_to_desktop",
            description="Writes a message, letter, or note and saves it as a text file directly on the user's computer desktop.",
            parameters={
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "The name of the file, e.g., rahul_message.txt"},
                    "content": {"type": "string", "description": "The full text content to write into the file."}
                },
                "required": ["filename", "content"]
            }
        )
    ]
)

# ----------------------------------------------------------------------------
# 1. AI BRAIN (Gemini)
# ----------------------------------------------------------------------------
 # Change your code to look something like this:
api_key = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)
chat = None

def build_chat():
    global chat
    chat = client.chats.create(
        model=config["model"],
        config=types.GenerateContentConfig(
            system_instruction=(
                f"You are {config['name'].title()}, a fast, helpful desktop OS assistant. "
                "Keep responses under 2 short sentences. "
                "Always reply exactly as: [2-letter-language-code]|[message]. "
                "Reply in the language the user spoke. "
                "Examples: en|Hello!  ml|നമസ്കാരം.  es|¡Hola!"
            ),
            tools=[desktop_writer_tool], # NEW: Injecting the agent tool here
            temperature=0.4
        )
    )

build_chat()

# ----------------------------------------------------------------------------
# 2. SPEAKER
# ----------------------------------------------------------------------------
pygame.mixer.init()
speak_lock = threading.Lock()
stop_speaking = threading.Event()
LANG_RE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2})?$")

def speak(text, lang_code="en"):
    print(f"AI: {text}", flush=True)
    if not LANG_RE.match(lang_code or ""):
        lang_code = "en"

    filename = os.path.join(tempfile.gettempdir(), f"voice_{uuid.uuid4().hex}.mp3")
    with speak_lock:
        stop_speaking.clear()
        try:
            try:
                gTTS(text=text, lang=lang_code).save(filename)
            except ValueError:
                gTTS(text=text, lang="en").save(filename)

            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not stop_speaking.is_set():
                time.sleep(0.05)
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception as e:
            print(f"Audio playback error: {e}", flush=True)
        finally:
            try:
                os.remove(filename)
            except OSError:
                pass

# ----------------------------------------------------------------------------
# 3. BACKGROUND THREADS (Activation & Proactive Alerts)
# ----------------------------------------------------------------------------
active = threading.Event()
shutdown = threading.Event()

def set_name(new_name, announce=True):
    cleaned = re.sub(r"[^\w\s-]", "", new_name, flags=re.UNICODE).strip().lower()[:20]
    if not cleaned:
        return False
    config["name"] = cleaned
    save_config()
    build_chat()
    print(f"NAME:{cleaned}", flush=True)
    if announce:
        speak(f"Okay, you can call me {cleaned} from now on.", "en")
    return True

def stdin_listener():
    while not shutdown.is_set():
        try:
            line = sys.stdin.readline()
            if not line:
                break
            raw = line.strip()
            cmd = raw.upper()
            if cmd == "ACTIVATE":
                active.set()
                print("STATUS:ACTIVATED", flush=True)
            elif cmd == "DEACTIVATE":
                active.clear()
                stop_speaking.set()
                print("STATUS:DEACTIVATED", flush=True)
            elif cmd.startswith("SETNAME:"):
                set_name(raw.split(":", 1)[1], announce=False)
        except Exception:
            break

def system_monitor():
    battery_alert_given = False
    while not shutdown.is_set():
        try:
            if hasattr(psutil, "sensors_battery"):
                battery = psutil.sensors_battery()
                if battery:
                    if battery.percent <= 20 and not battery.power_plugged and not battery_alert_given:
                        speak(f"Warning. Your battery is at {battery.percent} percent. Please connect to a power source.", "en")
                        battery_alert_given = True
                    elif battery.power_plugged:
                        battery_alert_given = False
        except Exception:
            pass
        time.sleep(60)

threading.Thread(target=stdin_listener, daemon=True).start()
threading.Thread(target=system_monitor, daemon=True).start()

# ----------------------------------------------------------------------------
# 4. WAKE-NAME PARSER
# ----------------------------------------------------------------------------
def split_wake_name(text):
    name_words = config["name"].split()
    n = len(name_words)
    words = text.split()
    target = " ".join(name_words)

    for i in range(min(4, len(words))):
        chunk = " ".join(words[i:i + n])
        ratio = difflib.SequenceMatcher(None, chunk, target).ratio()
        if ratio >= config["wake_sensitivity"]:
            cleaned_cmd = " ".join(words[:i] + words[i + n:]).strip(" ,.!?")
            return cleaned_cmd, True
    return text, False

def try_rename(text):
    RENAME_PATTERNS = [
        r"(?:call yourself|change your name to|your name is|your new name is|rename yourself to|from now on you are)\s+(.+)",
        r"(?:i will call you|i'll call you)\s+(.+)",
    ]
    for pattern in RENAME_PATTERNS:
        m = re.search(pattern, text)
        if m:
            new_name = re.sub(r"\b(please|okay|ok)\b", "", m.group(1)).strip()
            if not set_name(new_name):
                speak("Sorry, I didn't catch that name.", "en")
            return True
    return False

# ----------------------------------------------------------------------------
# 5. OS AUTOMATION & AI PIPELINE
# ----------------------------------------------------------------------------
COMMANDS = [
    (("open google", "search google", "open browser", "open youtube"),
     "Opening the system browser.", "COMMAND:OPEN_BROWSER"),
    (("open notepad", "open notes"),
     "Opening your notes.", "COMMAND:OPEN_NOTEPAD"),
    (("open settings", "system settings", "open control center"),
     "Opening system settings.", "COMMAND:OPEN_SETTINGS"),
    (("open recycle bin", "open trash"),
     "Opening the recycle bin.", "COMMAND:OPEN_RECYCLE"),
]
EXIT_WORDS = ("goodbye", "shut down", "shutdown", "exit")

def handle_local(text):
    if any(w in text for w in EXIT_WORDS):
        speak("Shutting down the system. Goodbye!", "en")
        shutdown.set()
        return True

    if try_rename(text):
        return True

    for triggers, reply, signal in COMMANDS:
        if any(t in text for t in triggers):
            speak(reply, "en")
            print(signal, flush=True)
            return True

    if any(q in text for q in ("time is it", "current time", "what's the time")):
        speak(f"The current time is {time.strftime('%I:%M %p')}.", "en")
        return True

    if "play music" in text or "pause music" in text:
        pyautogui.press('playpause')
        speak("Toggling media playback.", "en")
        return True
    if "mute volume" in text or "mute audio" in text:
        pyautogui.press('volumemute')
        speak("Audio muted.", "en")
        return True
    if "minimize windows" in text or "show desktop" in text:
        pyautogui.hotkey('win', 'd')
        speak("Minimizing all windows.", "en")
        return True

    if "search my notes" in text or "read my notes" in text or "check my notes" in text:
        notes_dir = os.path.join(os.path.expanduser("~"), "Documents", "AI OS", "Notes")
        notes_content = ""
        try:
            if os.path.exists(notes_dir):
                for f in os.listdir(notes_dir):
                    if f.endswith(".txt") or f.endswith(".md"):
                        with open(os.path.join(notes_dir, f), 'r', encoding='utf-8') as file:
                            notes_content += f"\n--- File: {f} ---\n{file.read()[:500]}\n"
        except Exception as e:
            print(f"File read error: {e}", flush=True)
            
        if notes_content:
            prompt = f"Here is the content of my local notes:\n{notes_content}\n\nBased on these notes, {text}"
            ask_ai(prompt)
        else:
            speak("I couldn't find any saved notes to search.", "en")
        return True

    if "what is on my screen" in text or "look at my screen" in text or "read my screen" in text:
        speak("Taking a look...", "en")
        print("Thinking...", flush=True)
        try:
            img = ImageGrab.grab()
            response = chat.send_message([text, img])
            parse_and_speak(response)
        except Exception as e:
            speak("I had trouble capturing the screen.", "en")
            print(f"Vision Error: {e}", flush=True)
        return True

    return False

def parse_and_speak(response):
    reply = (response.text or "").strip()
    lang, sep, message = reply.partition("|")
    if sep and LANG_RE.match(lang.strip()):
        speak(message.strip(), lang.strip())
    else:
        speak(reply, "en")

def ask_ai(text):
    print("Thinking...", flush=True)
    for attempt in range(2):
        try:
            response = chat.send_message(text)
            
            # --- NEW: AGENT EXECUTION LOOP ---
            if response.function_calls:
                for call in response.function_calls:
                    if call.name == "save_note_to_desktop":
                        print(">> Executing Agent Task: Saving file to desktop...", flush=True)
                        
                        args = call.args
                        fname = args.get("filename", "note.txt") if isinstance(args, dict) else getattr(args, "filename", "note.txt")
                        fcontent = args.get("content", "") if isinstance(args, dict) else getattr(args, "content", "")
                        
                        # 1. Run the Python physical task
                        result = execute_save_note(fname, fcontent)
                        
                        # 2. Send the result back to Gemini so it can answer the user
                        response = chat.send_message(
                            types.Part.from_function_response(
                                name="save_note_to_desktop",
                                response={"result": result}
                            )
                        )
            
            parse_and_speak(response)
            return
        except Exception as e:
            print(f"AI error (attempt {attempt + 1}): {e}", flush=True)
            time.sleep(0.5)
    speak("Sorry, I couldn't reach my brain right now.", "en")

# ----------------------------------------------------------------------------
# 6. MAIN LOOP
# ----------------------------------------------------------------------------
def main():
    r = sr.Recognizer()
    r.dynamic_energy_threshold = True
    r.pause_threshold = 0.7

    with sr.Microphone() as source:
        print("Calibrating background noise...", flush=True)
        r.adjust_for_ambient_noise(source, duration=1.5)

        speak(f"System online. Standby mode active. Press Control R to activate.", "en")
        print(f"NAME:{config['name']}", flush=True)
        print("STATUS:DEACTIVATED", flush=True)

        while not shutdown.is_set():
            if not active.is_set():
                time.sleep(0.2)
                continue

            print(">> THE MIC IS NOW HOT. SPEAK NOW! <<", flush=True)

            try:
                audio = r.listen(source, timeout=2, phrase_time_limit=15)
                if not active.is_set():
                    continue

                heard = r.recognize_google(audio, language=config["stt_language"]).lower().strip()
                print(f"You asked: {heard}", flush=True)

                command, called = split_wake_name(heard)
                target_cmd = command if command else heard

                if called and not command:
                    speak("Yes?", "en")
                else:
                    if not handle_local(target_cmd):
                        ask_ai(target_cmd)

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                print("Network connection down.", flush=True)
                time.sleep(2)
            except Exception as e:
                print(f"An error occurred: {e}", flush=True)

if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.mixer.quit()