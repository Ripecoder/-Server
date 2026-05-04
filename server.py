import os
import json
import requests
import psycopg
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# ── DB CONNECTION ─────────────────────────
def get_conn():
    return psycopg.connect(DATABASE_URL)

# ── AI CALL ───────────────────────────────
MODEL = "openai/gpt-oss-120b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

def get_ai_reply(messages):
    data = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a real estate assistant. Ask short questions to collect budget, location, bhk and phone."
            }
        ] + messages
    }

    res = requests.post(ENDPOINT, headers=HEADERS, json=data)

    if res.status_code != 200:
        return "AI error"

    return res.json()["choices"][0]["message"]["content"]

# ── DATA EXTRACTION ───────────────────────
def extract_data(messages):
    data = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": """Return ONLY JSON:
{
"budget":"",
"location":"",
"bhk":"",
"phone":""
}
"""
            }
        ] + messages
    }

    try:
        res = requests.post(ENDPOINT, headers=HEADERS, json=data)
        content = res.json()["choices"][0]["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except:
        return {}

def clean(data):
    return {
        "budget": ''.join(filter(str.isdigit, str(data.get("budget", "")))),
        "location": data.get("location"),
        "bhk": ''.join(filter(str.isdigit, str(data.get("bhk", "")))),
        "phone": ''.join(filter(str.isdigit, str(data.get("phone", ""))))
    }

# ── ROUTE ────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    req = request.json
    messages = req.get("messages", [])

    ai_reply = get_ai_reply(messages)

    extracted = clean(extract_data(messages))

    # ── SAVE LEAD IF PHONE EXISTS ──
    if extracted.get("phone"):
        try:
            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO "Leads" (name, phoneno, location, budget, bhk)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                "unknown",
                extracted.get("phone"),
                extracted.get("location"),
                extracted.get("budget") or None,
                extracted.get("bhk") or None
            ))

            conn.commit()
            cur.close()
            conn.close()

            print("🔥 LEAD STORED")

        except Exception as e:
            print("DB ERROR:", str(e))

    return jsonify({"reply": ai_reply})

# ── HEALTH CHECK ─────────────────────────
@app.route("/")
def home():
    return "Server running"

if __name__ == "__main__":
    app.run()
