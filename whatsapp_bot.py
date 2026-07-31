import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# CONFIGURATION
# Replace these with values from developers.facebook.com WhatsApp API Setup page
ACCESS_TOKEN = "YOUR_META_TEMPORARY_ACCESS_TOKEN"
PHONE_NUMBER_ID = "YOUR_META_PHONE_NUMBER_ID"
VERIFY_TOKEN = "my_secret_token_123"  # Change this to any custom secret string

@app.route("/", methods=["GET"])
def verify_webhook():
    """Handles verification requests from Meta Cloud API."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully!")
        return challenge, 200
    return "Verification token mismatch", 403

@app.route("/", methods=["POST"])
def receive_message():
    """Handles incoming message payloads from Meta."""
    data = request.json
    print("Incoming webhook payload:", data)

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        # Check if messages array exists (meaning we received a message)
        if "messages" in value:
            message_obj = value["messages"][0]
            sender_id = message_obj["from"]  # Recipient's phone number
            message_text = message_obj.get("text", {}).get("body", "").strip()

            print(f"Received message: '{message_text}' from {sender_id}")

            # Respond to the user
            send_whatsapp_message(sender_id, f"Echo: You sent me '{message_text}'! 🤖")

    except Exception as e:
        print("Error parsing incoming message:", e)

    return jsonify({"status": "success"}), 200

def send_whatsapp_message(to_phone_number, text_message):
    """Sends a text message using Meta Graph API."""
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {
            "body": text_message
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    print("Send response status:", response.status_code)
    print("Send response content:", response.json())
    return response.json()

if __name__ == "__main__":
    # Run locally on port 5000
    print("Starting WhatsApp Bot Webhook Server...")
    app.run(port=5000, host="0.0.0.0")
