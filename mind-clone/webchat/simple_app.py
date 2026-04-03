"""
BobChat Web - Simple Version (No WebSockets)
Run: python simple_app.py
"""

from flask import Flask, render_template, request, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


CHAT_FILE = 'messages.json'
messages = []

def load_messages():
    global messages
    try:
        if os.path.exists(CHAT_FILE):
            with open(CHAT_FILE, 'r') as f:
                messages = json.load(f)
        else:
            messages = []
    except (json.JSONDecodeError, IOError):
        messages = []

def save_messages():
    temp_file = CHAT_FILE + '.tmp'
    with open(temp_file, 'w') as f:
        json.dump(messages, f, indent=2)
    os.replace(temp_file, CHAT_FILE)

@app.route('/')
def index():
    return render_template('simple_chat.html')

@app.route('/api/messages')
def get_messages():
    return jsonify(messages)

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
    username = data.get('username', '')
    msg_text = data.get('message', '')
    if not isinstance(username, str) or not isinstance(msg_text, str):
        return jsonify({'status': 'error', 'message': 'Invalid types'}), 400
    username = username.strip()
    msg_text = msg_text.strip()
    if not username or not msg_text:
        return jsonify({'status': 'error', 'message': 'Empty fields'}), 400
    if len(username) > 50 or len(msg_text) > 2000:
        return jsonify({'status': 'error', 'message': 'Too long'}), 400
    message = {
        'id': len(messages) + 1,
        'username': username,
        'message': msg_text,
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'date': datetime.now().strftime('%Y-%m-%d')
    }
    messages.append(message)
    if len(messages) > 500:
        messages.pop(0)
    save_messages()
    return jsonify({'status': 'success', 'message': message})

if __name__ == '__main__':
    load_messages()
    print("=" * 60)
    print("BOBCHAT WEB SERVER STARTING...")
    print("=" * 60)
    print("\nAccess the chat at: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
