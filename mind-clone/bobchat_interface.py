"""
BobChat Simple Interface
Easy-to-use functions for chatting
"""

from bobchat import BobChat, send_msg, read_msgs, view_chat

def chat_menu():
    """Simple interactive menu for BobChat"""
    print("=" * 50)
    print("WELCOME TO BOBCHAT!")
    print("=" * 50)
    
    # Get user name
    your_name = input("\nEnter your name: ").strip()
    chat = BobChat(your_name)
    
    # Get friend's name
    friend_name = input("Enter your friend's name: ").strip()
    
    print(f"\nHello {your_name}! You're chatting with {friend_name}.")
    print("Commands: send | read | view | stats | quit")
    
    while True:
        print("\n" + "-" * 50)
        command = input("What do you want to do? ").strip().lower()
        
        if command == "send":
            message = input(f"Message to {friend_name}: ")
            print(send_msg(your_name, friend_name, message))
            
        elif command == "read":
            print(read_msgs(your_name))
            
        elif command == "view":
            print(view_chat(your_name, friend_name))
            
        elif command == "stats":
            print(chat.get_stats())
            
        elif command == "quit":
            print(f"\nGoodbye {your_name}!")
            break
            
        else:
            print("Unknown command. Use: send, read, view, stats, quit")

if __name__ == "__main__":
    chat_menu()
