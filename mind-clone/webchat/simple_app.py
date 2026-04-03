"""
BobChat Web - Simple Version (No WebSockets)
Run: python simple_app.py
"""

from flask import Flask, render_template, request, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)

CHAT_FILE = 'messages.json'
messages = []

def load_messages():
    global messages
    if os.path.exists(CHAT_FILE):
        with open(CHAT_FILE, 'r') as f:
            messages = json.load(f)
    else:
        messages = []

def save_messages():
    with open(CHAT_FILE, 'w') as f:
        json.dump(messages, f, indent=2)

@app.route('/')
def index():
    return render_template('simple_chat.html')

@app.route('/api/messages')
def get_messages():
    return jsonify(messages)

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    message = {
        'id': len(messages) + 1,
        'username': data.get('username'),
        'message': data.get('message'),
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'date': datetime.now().strftime('%Y-%m-%d')
    }
    messages.append(message)
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
