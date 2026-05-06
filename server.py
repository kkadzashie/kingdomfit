from flask import Flask, request, jsonify, send_from_directory
import sqlite3, hashlib, os, json
from datetime import date, datetime

app = Flask(__name__, static_folder='public', static_url_path='')
DB = '/data/kingdomfit.db'

def get_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_lower TEXT UNIQUE NOT NULL,
            pin_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (date('now'))
        );
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            activity TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            logged_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, log_date)
        );
    """)
    db.commit()
    db.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def calc_streak(workouts):
    if not workouts:
        return 0
    dates = set(w['log_date'] for w in workouts)
    streak = 0
    d = date.today()
    while True:
        k = d.isoformat()
        if k in dates:
            streak += 1
            from datetime import timedelta
            d = d - timedelta(days=1)
        else:
            break
    return streak

# ── Auth ─────────────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = (data.get('name') or '').strip()
    pin  = data.get('pin', '')
    if not name or len(pin) != 4 or not pin.isdigit():
        return jsonify(error='Name and 4-digit PIN required'), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO users (name, name_lower, pin_hash) VALUES (?, ?, ?)',
            (name, name.lower(), hash_pin(pin))
        )
        db.commit()
        return jsonify(id=cur.lastrowid, name=name)
    except sqlite3.IntegrityError:
        return jsonify(error='Name already taken'), 409
    finally:
        db.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    name = (data.get('name') or '').strip().lower()
    pin  = data.get('pin', '')
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE name_lower = ?', (name,)).fetchone()
    db.close()
    if not user or user['pin_hash'] != hash_pin(pin):
        return jsonify(error='Invalid name or PIN'), 401
    return jsonify(id=user['id'], name=user['name'])

# ── Workouts ─────────────────────────────────────────────────────────────────
@app.route('/api/workouts', methods=['POST'])
def log_workout():
    data = request.json
    user_id  = data.get('user_id')
    log_date = data.get('log_date')
    activity = data.get('activity', '').strip()
    duration = data.get('duration_minutes')
    notes    = data.get('notes', '').strip()
    if not all([user_id, log_date, activity, duration]):
        return jsonify(error='Missing fields'), 400
    if int(duration) < 30:
        return jsonify(error='Minimum 30 minutes required'), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO workouts (user_id, log_date, activity, duration_minutes, notes) VALUES (?, ?, ?, ?, ?)',
            (user_id, log_date, activity, int(duration), notes)
        )
        db.commit()
        return jsonify(id=cur.lastrowid)
    except sqlite3.IntegrityError:
        return jsonify(error='Already logged for today'), 409
    finally:
        db.close()

@app.route('/api/workouts/<int:user_id>/<log_date>', methods=['DELETE'])
def delete_workout(user_id, log_date):
    db = get_db()
    db.execute('DELETE FROM workouts WHERE user_id = ? AND log_date = ?', (user_id, log_date))
    db.commit()
    db.close()
    return jsonify(ok=True)

@app.route('/api/workouts/<int:user_id>')
def get_workouts(user_id):
    month = request.args.get('month')
    db = get_db()
    if month:
        rows = db.execute(
            'SELECT * FROM workouts WHERE user_id = ? AND log_date LIKE ? ORDER BY log_date DESC',
            (user_id, month + '%')
        ).fetchall()
    else:
        rows = db.execute(
            'SELECT * FROM workouts WHERE user_id = ? ORDER BY log_date DESC',
            (user_id,)
        ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

# ── Leaderboard ──────────────────────────────────────────────────────────────
@app.route('/api/leaderboard')
def leaderboard():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    db = get_db()
    users = db.execute('SELECT id, name FROM users').fetchall()
    board = []
    for u in users:
        month_ws = db.execute(
            'SELECT log_date FROM workouts WHERE user_id = ? AND log_date LIKE ?',
            (u['id'], month + '%')
        ).fetchall()
        all_ws = db.execute(
            'SELECT log_date FROM workouts WHERE user_id = ? ORDER BY log_date DESC',
            (u['id'],)
        ).fetchall()
        streak    = calc_streak([dict(w) for w in all_ws])
        total_days = len(month_ws)
        points    = total_days + (streak * 2)
        board.append(dict(id=u['id'], name=u['name'], totalDays=total_days, streak=streak, points=points))
    db.close()
    board.sort(key=lambda x: (-x['points'], -x['streak'], -x['totalDays']))
    return jsonify(board)

# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join('public', path)):
        return send_from_directory('public', path)
    return send_from_directory('public', 'index.html')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 3000))
    print(f'KingdomFit running on http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
