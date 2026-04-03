#!/usr/bin/env python3
"""
Deploy Arsh & Bob Chat to Render
Run this script after pushing to GitHub
"""

import subprocess
import sys
import json

def main():
    print("="*60)
    print("Arsh & Bob Chat - Render Deployment Helper")
    print("="*60)
    
    print("\nStep 1: Make sure your code is on GitHub")
    print("  - Create a new repo at https://github.com/new")
    print("  - Push your code there")
    print("\nStep 2: Deploy to Render")
    print("  - Go to https://dashboard.render.com/")
    print("  - Sign up (free, no credit card)")
    print("  - Click 'New +' → 'Web Service'")
    print("  - Connect your GitHub repo")
    print("  - Use these settings:")
    print("      Runtime: Python 3")
    print("      Build Command: pip install -r requirements.txt")
    print("      Start Command: gunicorn app:app")
    print("  - Click 'Create Web Service'")
    print("\nStep 3: Share the URL!")
    print("  - Your app will be at: https://<your-service-name>.onrender.com")
    print("  - Give this link to your friend!")
    
    print("\n" + "="*60)
    print("Quick Commands:")
    print("="*60)
    print("\nTo push to GitHub:")
    print("  git remote add origin https://github.com/YOUR_USERNAME/arsh-bob-chat.git")
    print("  git push -u origin master")
    
    print("\n" + "="*60)
    print("Need help? Contact: your-email@example.com")
    print("="*60)

if __name__ == "__main__":
    main()
