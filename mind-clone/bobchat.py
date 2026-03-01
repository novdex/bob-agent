"""
BobChat - A Simple 2-Person Messaging Platform
Created by Bob (AI)

Features:
- Send messages
- Read inbox
- Reply to messages
- View conversation history
- Works between 2 users (User A and User B)
"""

import json
import os
from datetime import datetime

CHAT_FILE = "chat_history.json"

class BobChat:
    def __init__(self, user_name):
        self.user_name = user_name
        self.inbox = []
        self.load_chat()
    
    def load_chat(self):
        """Load chat history from file"""
        if os.path.exists(CHAT_FILE):
            with open(CHAT_FILE, 'r') as f:
                self.messages = json.load(f)
        else:
            self.messages = []
    
    def save_chat(self):
        """Save chat history to file"""
        with open(CHAT_FILE, 'w') as f:
            json.dump(self.messages, f, indent=2)
    
    def send_message(self, to_user, message):
        """Send a message to the other user"""
        msg = {
            "id": len(self.messages) + 1,
            "from": self.user_name,
            "to": to_user,
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "read": False
        }
        self.messages.append(msg)
        self.save_chat()
        return f"✅ Message sent to {to_user}!"
    
    def get_inbox(self):
        """Get unread messages for current user"""
        inbox = [m for m in self.messages if m["to"] == self.user_name and not m["read"]]
        return inbox
    
    def read_inbox(self):
        """Read all unread messages"""
        inbox = self.get_inbox()
        if not inbox:
            return "📭 No new messages."
        
        output = f"\n📬 INBOX for {self.user_name}:\n" + "="*40 + "\n"
        for msg in inbox:
            output += f"\nFrom: {msg['from']}\n"
            output += f"Time: {msg['timestamp']}\n"
            output += f"Message: {msg['message']}\n"
            output += "-"*40 + "\n"
            msg["read"] = True
        
        self.save_chat()
        output += f"\n✅ {len(inbox)} message(s) read."
        return output
    
    def view_conversation(self, with_user):
        """View full conversation with another user"""
        conversation = [m for m in self.messages 
                       if (m["from"] == self.user_name and m["to"] == with_user) 
                       or (m["from"] == with_user and m["to"] == self.user_name)]
        
        if not conversation:
            return f"No conversation history with {with_user}."
        
        output = f"\n💬 Conversation between {self.user_name} and {with_user}:\n" + "="*50 + "\n"
        for msg in conversation:
            sender = "You" if msg["from"] == self.user_name else msg["from"]
            output += f"\n[{msg['timestamp']}] {sender}:\n"
            output += f"  {msg['message']}\n"
        output += "="*50
        return output
    
    def reply(self, to_user, message):
        """Quick reply to the last conversation"""
        return self.send_message(to_user, message)
    
    def get_stats(self):
        """Get chat statistics"""
        sent = len([m for m in self.messages if m["from"] == self.user_name])
        received = len([m for m in self.messages if m["to"] == self.user_name])
        unread = len([m for m in self.messages if m["to"] == self.user_name and not m["read"]])
        
        return f"\n📊 Stats for {self.user_name}:\n" + "="*30 + f"\nMessages Sent: {sent}\nMessages Received: {received}\nUnread Messages: {unread}"


# Quick helper functions
def send_msg(from_user, to_user, message):
    """Quick send message"""
    chat = BobChat(from_user)
    return chat.send_message(to_user, message)

def read_msgs(user_name):
    """Quick read messages"""
    chat = BobChat(user_name)
    return chat.read_inbox()

def view_chat(user1, user2):
    """View conversation between two users"""
    chat = BobChat(user1)
    return chat.view_conversation(user2)

if __name__ == "__main__":
    print("🚀 BobChat Platform Loaded!")
    print("\nExample usage:")
    print("  send_msg('Alice', 'Bob', 'Hello!')")
    print("  read_msgs('Bob')")
    print("  view_chat('Alice', 'Bob')")
