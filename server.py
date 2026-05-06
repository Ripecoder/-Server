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

# ── DB CONNECTION (Fixed for Supabase Pooler) ────────────────
def get_conn():
    url = os.getenv("DATABASE_URL")
    print(f"DEBUG: URL is {url[:10] if url else 'NONE'}") # Add this!
    return psycopg.connect(url, prepare_threshold=None)


# ── SINGLE AI CALL (Faster & Cheaper) ───────────────────────
MODEL = "llama-3.3-70b-versatile" 
ENDPOINT = "https://groq.com"
HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

def get_ai_response_and_data(messages):
    system_prompt = """
    You are a real estate assistant. 
    1. Provide a short, friendly reply to the user.
    2. Extract budget, location, bhk, and phone.
    3. Return ONLY a JSON object:
    {
      "reply": "your message here",
      "extracted": {"budget": "", "location": "", "bhk": "", "phone": ""}
    }
    """
    
    data = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "response_format": {"type": "json_object"}
    }

    try:
        res = requests.post(ENDPOINT, headers=HEADERS, json=data)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("🔥 AI ERROR:", str(e))
        return None

# ── DATA CLEANING ───────────────────────
def clean(val):
    if not val: return None
    return ''.join(filter(str.isdigit, str(val)))

# ── ROUTE ────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    req = request.json
    messages = req.get("messages", [])

    # Get both reply and data in ONE go
    raw_response = get_ai_response_and_data(messages)
    
    if not raw_response:
        return jsonify({"reply": "Sorry, I'm having trouble connecting. Try again?"})

    result = json.loads(raw_response)
    ai_reply = result.get("reply")
    ext = result.get("extracted", {})

    # ── SAVE LEAD IF PHONE EXISTS ──
    phone = clean(ext.get("phone"))
    if phone:
        try:
            # Using 'with' handles opening/closing/committing automatically
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO Leads (client_name, phoneno, location, bhk)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        "unknown",
                        phone,
                        ext.get("location"),
                        int(clean(ext.get("bhk"))) if clean(ext.get("bhk")) else None
                    ))
            print("🔥 LEAD STORED")
        except Exception as e:
            print("DB ERROR:", str(e))

    return jsonify({"reply": ai_reply})

@app.route("/")
def home():
    return "Server running"

if __name__ == "__main__":
    # Render provides a PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
