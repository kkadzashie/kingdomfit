# Kingdom Fit — Fitness Accountability Tracker

## Features
- PIN-based login (no email needed)
- Log: activity type + duration + optional notes (30 min minimum)
- 4 stat cards: streak · days this month · points · % completion
- Monthly calendar heatmap showing every workout day
- Full workout history with activity + duration
- Live leaderboard: ranked by points, streak badges, monthly auto-reset
- Points = total days + (streak × 2)

---

## Deploy free in 5 minutes — Render.com

### Step 1 — Push to GitHub
```bash
git init && git add . && git commit -m "launch"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/kingdomfit.git
git push -u origin main
```

### Step 2 — Deploy on Render
1. Go to https://render.com → New → Web Service
2. Connect your GitHub repo
3. Settings:
   - Runtime: **Python 3**
   - Build Command: `pip install flask`
   - Start Command: `python server.py`
   - Instance Type: **Free**
4. Click "Create Web Service"
5. Share the URL — everyone opens it on their phone

---

## Alternative: Railway.app
1. https://railway.app → Deploy from GitHub
2. Set start command: `python server.py`
3. Done — faster than Render free tier

---

## Run locally
```bash
pip install flask
python server.py
# Open http://localhost:3000
```

---

## Points system
- 1 point per workout day
- +2 bonus points per streak day
- Example: 15 days, 6-day streak = 15 + 12 = 27 pts

## Monthly resets
Leaderboard and calendar auto-scope to current month. No manual reset needed.
