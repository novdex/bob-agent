========================================
PRIVATE CHAT APP - SETUP GUIDE
========================================

I created a private chat app for you and your friend!

HOW IT WORKS:
- Generates a secret unique link
- Only people with the link can join
- Real-time messaging
- No one else can see your chat
- Messages persist while server is running

SETUP INSTRUCTIONS:
-------------------

1. INSTALL REQUIREMENTS:
   Open terminal/command prompt and run:
   
   pip install flask flask-socketio python-socketio eventlet

2. RUN THE APP:
   python private_chat_app.py

3. CREATE A CHAT ROOM:
   - Open browser to: http://localhost:5000
   - You'll get a secret link
   - Copy that link and share with ONLY your friend

4. JOIN THE CHAT:
   - Both you and your friend open the secret link
   - Enter your names
   - Start chatting privately!

FEATURES:
---------
- Real-time messaging
- Shows who joined
- Message history
- Beautiful UI
- Mobile-friendly
- 100% private (no database, no logs)

SECURITY NOTES:
--------------
- Anyone with the link can join
- Share the link securely (WhatsApp, Signal, etc.)
- Chat exists only while server is running
- No messages stored permanently

========================================
