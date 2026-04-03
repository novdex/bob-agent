# Deploy Arsh & Bob Chat

## Quick Deploy Options (Pick One)

### Option 1: Vercel (Easiest - 1 Click)
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/yourusername/arsh-bob-chat)

**Steps:**
1. Push this code to a GitHub repository
2. Click the "Deploy" button above
3. Your chat will be live in 2 minutes

---

### Option 2: Render (Free, Always On)
**Steps:**
1. Push this code to GitHub
2. Go to https://dashboard.render.com/
3. Click "New +" → "Web Service"
4. Connect your GitHub repo
5. Use these settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
6. Click "Create Web Service"

---

### Option 3: Railway (Simple CLI)
**Steps:**
1. Install Railway CLI: `npm install -g @railway/cli`
2. Login: `railway login`
3. In this folder, run: `railway init`
4. Deploy: `railway up`
5. Get URL: `railway domain`

---

### Option 4: PythonAnywhere (Free, No GitHub needed)
**Steps:**
1. Go to https://www.pythonanywhere.com/ and create free account
2. Open Bash console
3. Run:
   ```bash
   git clone <your-github-repo-url>
   cd arsh-bob-chat
   pip install -r requirements.txt
   ```
4. Go to Web tab, create new app
5. Set WSGI file to point to `app.py`
6. Reload web app

---

## Recommended: Render (Best Free Option)

**Why Render?**
- ✅ Completely free (no credit card)
- ✅ Easy GitHub integration
- ✅ Custom domain support
- ✅ HTTPS included
- ✅ Never sleeps (unlike Heroku free tier)

**After Deployment:**
- Your app will be at: `https://arsh-bob-chat.onrender.com`
- Share this link with your friend!
- Messages persist while the app is running
- Free tier never expires

---

## Local Testing

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000
