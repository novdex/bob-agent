#!/usr/bin/env python3
"""
Private Chat App - Secure 2-Person Chat
Only accessible with the secret link/token
"""

from flask import Flask, render_template_string, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
import secrets
import os
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*")

# Store chats in memory (in production, use a database)
chats = {}

# HTML Template for the chat interface
CHAT_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Private Chat</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .chat-container {
            width: 90%;
            max-width: 600px;
            height: 80vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .chat-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        .chat-header h1 { font-size: 24px; margin-bottom: 5px; }
        .chat-header p { font-size: 12px; opacity: 0.9; }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .message {
            margin-bottom: 15px;
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 18px;
            word-wrap: break-word;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message.sent {
            background: #667eea;
            color: white;
            margin-left: auto;
            border-bottom-right-radius: 4px;
        }
        .message.received {
            background: white;
            color: #333;
            margin-right: auto;
            border-bottom-left-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .message-time {
            font-size: 10px;
            opacity: 0.7;
            margin-top: 5px;
        }
        .input-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #eee;
            display: flex;
            gap: 10px;
        }
        #messageInput {
            flex: 1;
            padding: 12px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            outline: none;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        #messageInput:focus {
            border-color: #667eea;
        }
        #sendBtn {
            padding: 12px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            font-weight: bold;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        #sendBtn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .name-input {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .name-box {
            background: white;
            padding: 40px;
            border-radius: 20px;
            text-align: center;
            max-width: 400px;
        }
        .name-box h2 { margin-bottom: 20px; color: #333; }
        .name-box input {
            width: 100%;
            padding: 15px;
            border: 2px solid #667eea;
            border-radius: 10px;
            margin-bottom: 20px;
            font-size: 16px;
        }
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div id="nameModal" class="name-input">
        <div class="name-box">
            <h2>[LOCK] Enter Your Name</h2>
            <input type="text" id="nameInput" placeholder="Your name..." maxlength="20">
            <button id="joinBtn" style="padding: 15px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; cursor: pointer; font-size: 16px; font-weight: bold;">Join Chat</button>
        </div>
    </div>

    <div class="chat-container">
        <div class="chat-header">
            <h1>[LOCK] Private Chat Room</h1>
            <p>Only you and your friend can see this</p>
        </div>
        <div class="messages" id="messages"></div>
        <div class="input-area">
            <input type="text" id="messageInput" placeholder="Type a message..." maxlength="500">
            <button id="sendBtn">Send</button>
        </div>
    </div>

    <script>
        const socket = io();
        const roomId = '{{ room_id }}';
        let userName = '';
        let messageHistory = [];

        // Join room on name submit
        document.getElementById('joinBtn').addEventListener('click', () => {
            userName = document.getElementById('nameInput').value.trim();
            if (userName) {
                document.getElementById('nameModal').classList.add('hidden');
                socket.emit('join', { room: roomId, name: userName });
            }
        });

        // Send message
        function sendMessage() {
            const input = document.getElementById('messageInput');
            const msg = input.value.trim();
            if (msg) {
                socket.emit('message', { room: roomId, message: msg, name: userName });
                input.value = '';
            }
        }

        document.getElementById('sendBtn').addEventListener('click', sendMessage);
        document.getElementById('messageInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });

        // Receive message
        socket.on('message', (data) => {
            const messagesDiv = document.getElementById('messages');
            const msgDiv = document.createElement('div');
            msgDiv.className = `message ${data.name === userName ? 'sent' : 'received'}`;
            msgDiv.innerHTML = `
                <div style="font-weight: bold; margin-bottom: 3px; font-size: 12px;">${data.name}</div>
                <div>${escapeHtml(data.message)}</div>
                <div class="message-time">${data.time}</div>
            `;
            messagesDiv.appendChild(msgDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        });

        // Load chat history
        socket.on('history', (messages) => {
            messages.forEach(msg => {
                const messagesDiv = document.getElementById('messages');
                const msgDiv = document.createElement('div');
                msgDiv.className = `message ${msg.name === userName ? 'sent' : 'received'}`;
                msgDiv.innerHTML = `
                    <div style="font-weight: bold; margin-bottom: 3px; font-size: 12px;">${msg.name}</div>
                    <div>${escapeHtml(msg.message)}</div>
                    <div class="message-time">${msg.time}</div>
                `;
                messagesDiv.appendChild(msgDiv);
            });
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        });

        // User joined notification
        socket.on('user_joined', (data) => {
            const messagesDiv = document.getElementById('messages');
            const notifDiv = document.createElement('div');
            notifDiv.style.cssText = 'text-align: center; color: #666; font-size: 12px; margin: 10px 0;';
            notifDiv.textContent = `[USER] ${data.name} joined the chat`;
            messagesDiv.appendChild(notifDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        });

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>
'''

@app.route('/')
def home():
    """Generate a new private chat room"""
    room_id = secrets.token_urlsafe(16)
    chats[room_id] = {
        'messages': [],
        'users': set()
    }
    return f'''
    <h1>[LOCK] Private Chat Created!</h1>
    <p>Share this secret link with ONLY your friend:</p>
    <h3><a href="/chat/{room_id}">http://localhost:5000/chat/{room_id}</a></h3>
    <p style="color: red;">WARNING: Keep this link private! Anyone with this link can join.</p>
    '''

@app.route('/chat/<room_id>')
def chat_room(room_id):
    """Access a private chat room"""
    if room_id not in chats:
        return "Chat room not found!", 404
    return render_template_string(CHAT_TEMPLATE, room_id=room_id)

@socketio.on('join')
def on_join(data):
    """Handle user joining"""
    room = data['room']
    name = data['name']
    join_room(room)
    
    if room in chats:
        chats[room]['users'].add(name)
        # Send chat history
        emit('history', chats[room]['messages'])
        # Notify others
        emit('user_joined', {'name': name}, room=room)

@socketio.on('message')
def on_message(data):
    """Handle new message"""
    room = data['room']
    message_data = {
        'name': data['name'],
        'message': data['message'],
        'time': datetime.now().strftime('%H:%M')
    }
    
    if room in chats:
        chats[room]['messages'].append(message_data)
        # Keep only last 100 messages
        if len(chats[room]['messages']) > 100:
            chats[room]['messages'] = chats[room]['messages'][-100:]
        
        emit('message', message_data, room=room)

if __name__ == '__main__':
    print("=" * 60)
    print("PRIVATE CHAT APP")
    print("=" * 60)
    print("\nTo create a new chat room:")
    print("  -> Open: http://localhost:5000")
    print("\nTo run the server:")
    print("  -> python private_chat_app.py")
    print("=" * 60)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
