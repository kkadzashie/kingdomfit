from flask import Flask, request, jsonify, send_from_directory
import psycopg2, psycopg2.extras, hashlib, os
from datetime import date, timedelta

app = Flask(__name__, static_folder='public', static_url_path='')
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres.imwjvmpnwtjwvkwralzl:S!WvhY7GhtRJR@KQQldo@aws-1-us-west-2.pooler.supabase.com:5432/postgres')

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            name_lower TEXT UNIQUE NOT NULL,
            pin_hash TEXT NOT NULL,
            created_at DATE DEFAULT CURRENT_DATE
        );
        CREATE TABLE IF NOT EXISTS workouts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            log_date DATE NOT NULL,
            activity TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            logged_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, log_date)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def calc_streak(workouts):
    if not workouts:
        return 0
    dates = set(str(w['log_date']) for w in workouts)
    streak = 0
    d = date.today()
    while True:
        if d.isoformat() in dates:
            streak += 1
            d = d - timedelta(days=1)
        else:
            break
    return streak

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = (data.get('name') or '').strip()
    pin  = data.get('pin', '')
    if not name or len(pin) != 4 or not pin.isdigit():
        return jsonify(error='Name and 4-digit PIN required'), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (name, name_lower, pin_hash) VALUES (%s, %s, %s) RETURNING id, name',
                    (name, name.lower(), hash_pin(pin)))
        row = cur.fetchone()
        conn.commit()
        return jsonify(id=row['id'], name=row['name'])
    except psycopg2.errors.UniqueViolation:
        return jsonify(error='Name already taken'), 409
    finally:
        cur.close(); conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    name = (data.get('name') or '').strip().lower()
    pin  = data.get('pin', '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE name_lower = %s', (name,))
    user = cur.fetchone()
    cur.close(); conn.close()
    if not user or user['pin_hash'] != hash_pin(pin):
        return jsonify(error='Invalid name or PIN'), 401
    return jsonify(id=user['id'], name=user['name'])

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
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO workouts (user_id, log_date, activity, duration_minutes, notes) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                    (user_id, log_date, activity, int(duration), notes))
        row = cur.fetchone()
        conn.commit()
        return jsonify(id=row['id'])
    except psycopg2.errors.UniqueViolation:
        return jsonify(error='Already logged for today'), 409
    finally:
        cur.close(); conn.close()

@app.route('/api/workouts/<int:user_id>/<log_date>', methods=['DELETE'])
def delete_workout(user_id, log_date):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM workouts WHERE user_id = %s AND log_date = %s', (user_id, log_date))
    conn.commit()
    cur.close(); conn.close()
    return jsonify(ok=True)

@app.route('/api/workouts/<int:user_id>')
def get_workouts(user_id):
    month = request.args.get('month')
    conn = get_db()
    cur = conn.cursor()
    if month:
        cur.execute("SELECT * FROM workouts WHERE user_id = %s AND TO_CHAR(log_date,'YYYY-MM') = %s ORDER BY log_date DESC",
                    (user_id, month))
    else:
        cur.execute('SELECT * FROM workouts WHERE user_id = %s ORDER BY log_date DESC', (user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/leaderboard')
def leaderboard():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM users')
    users = cur.fetchall()
    board = []
    for u in users:
        cur.execute("SELECT log_date FROM workouts WHERE user_id = %s AND TO_CHAR(log_date,'YYYY-MM') = %s",
                    (u['id'], month))
        month_ws = cur.fetchall()
        cur.execute('SELECT log_date FROM workouts WHERE user_id = %s ORDER BY log_date DESC', (u['id'],))
        all_ws = cur.fetchall()
        streak = calc_streak([dict(w) for w in all_ws])
        total_days = len(month_ws)
        points = total_days + (streak * 2)
        board.append(dict(id=u['id'], name=u['name'], totalDays=total_days, streak=streak, points=points))
    cur.close(); conn.close()
    board.sort(key=lambda x: (-x['points'], -x['streak'], -x['totalDays']))
    return jsonify(board)

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
