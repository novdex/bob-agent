# Arsh & Bob Chat

A simple Flask chat application for 2 users.

## Features
- Real-time chat between Arsh and Bob
- Beautiful UI with auto-refresh
- REST API for programmatic access
- Mobile-friendly design

## Live Demo
Deployed on Render: [Your URL will appear here after deployment]

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python app.py
```

## API Endpoints

- `GET /` - Web interface
- `GET /api/messages` - Get all messages
- `POST /api/send` - Send message (JSON: `{sender: "Arsh|Bob", text: "message"}`)

## Deployment

This app is configured for deployment on Render using Gunicorn.
