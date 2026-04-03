from flask import Flask, request, jsonify, render_template_string
import time
import os

app = Flask(__name__)

# Simple in-memory message storage
messages = []
users = ["Arsh", "Bob"]

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Arsh & Bob Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        h1 { text-align: center; color: #333; }
        .chat-box { border: 1px solid #ccc; height: 400px; overflow-y: auto; padding: 10px; margin-bottom: 10px; background: white; border-radius: 8px; }
        .message { margin: 10px 0; padding: 10px; border-radius: 8px; animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .Arsh { background: #e3f2fd; margin-right: 20%; }
        .Bob { background: #f3e5f5; margin-left: 20%; }
        .sender { font-weight: bold; color: #333; }
        .time { font-size: 0.8em; color: #666; }
        form { display: flex; gap: 10px; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        input, select { padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 16px; }
        button { padding: 12px 24px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background: #45a049; }
        .empty { text-align: center; color: #999; padding: 50px; }
        .status { text-align: center; color: #4caf50; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>Arsh & Bob Chat</h1>
    <div class="status">Live Chat - Start messaging!</div>
    <div class="chat-box" id="chatBox">
        {% if messages %}
            {% for msg in messages %}
            <div class="message {{ msg.sender }}">
                <span class="sender">{{ msg.sender }}:</span> {{ msg.text }}
                <div class="time">{{ msg.time }}</div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">No messages yet. Be the first to send a message!</div>
        {% endif %}
    </div>
    <form action="/send" method="POST">
        <select name="sender">
            <option value="Arsh">Arsh</option>
            <option value="Bob">Bob</option>
        </select>
        <input type="text" name="text" placeholder="Type a message..." required style="flex: 1;">
        <button type="submit">Send</button>
    </form>
    <script>
        // Auto-scroll to bottom
        var chatBox = document.getElementById("chatBox");
        chatBox.scrollTop = chatBox.scrollHeight;
        // Refresh every 3 seconds to see new messages
        setInterval(function() {
            location.reload();
        }, 3000);
    </script>
</body>
</html>
'''

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, messages=messages)

@app.route("/api/messages", methods=["GET"])
def get_messages():
    return jsonify(messages)

@app.route("/send", methods=["POST"])
def send_message():
    sender = request.form.get("sender")
    text = request.form.get("text")
    if sender in users and text:
        message = {
            "sender": sender,
            "text": text,
            "time": time.strftime("%H:%M:%S")
        }
        messages.append(message)
        # Keep only last 100 messages to prevent memory issues
        if len(messages) > 100:
            messages.pop(0)
        return jsonify({"status": "ok", "message": message})
    return jsonify({"status": "error"}), 400

@app.route("/api/send", methods=["POST"])
def api_send_message():
    data = request.get_json()
    sender = data.get("sender")
    text = data.get("text")
    if sender in users and text:
        message = {
            "sender": sender,
            "text": text,
            "time": time.strftime("%H:%M:%S")
        }
        messages.append(message)
        # Keep only last 100 messages
        if len(messages) > 100:
            messages.pop(0)
        return jsonify({"status": "ok", "message": message})
    return jsonify({"status": "error"}), 400

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
