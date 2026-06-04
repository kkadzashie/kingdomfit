from flask import Flask, request, jsonify, send_from_directory
import psycopg2, psycopg2.extras, hashlib, os, secrets
from datetime import date, timedelta, datetime
import pytz

# Arizona never observes DST — always UTC-7
AZ_TZ = pytz.timezone('America/Phoenix')

def az_today():
    """Current date in Arizona time."""
    return datetime.now(AZ_TZ).date()

def az_month():
    """Current YYYY-MM in Arizona time."""
    return datetime.now(AZ_TZ).strftime('%Y-%m')

app = Flask(__name__, static_folder='public', static_url_path='')
DATABASE_URL = os.environ.get('DATABASE_URL')
ADMIN_NAME = 'mrs. dk'

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
            is_admin BOOLEAN DEFAULT FALSE,
            created_at DATE DEFAULT CURRENT_DATE
        );
        CREATE TABLE IF NOT EXISTS workouts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            log_date DATE NOT NULL,
            activity TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            logged_at TIMESTAMP DEFAULT NOW()
        );
        -- Multiple sessions per day allowed, no unique constraint on activity
        CREATE TABLE IF NOT EXISTS reactions (
            id SERIAL PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            emoji TEXT NOT NULL,
            UNIQUE(workout_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS badges (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            badge_key TEXT NOT NULL,
            earned_at DATE DEFAULT CURRENT_DATE,
            UNIQUE(user_id, badge_key)
        );
        CREATE TABLE IF NOT EXISTS monthly_winners (
            id SERIAL PRIMARY KEY,
            month TEXT NOT NULL,
            winner_name TEXT,
            points INTEGER,
            total_days INTEGER,
            streak INTEGER,
            total_hours FLOAT DEFAULT 0,
            winner_type TEXT DEFAULT 'points'
        );
        CREATE TABLE IF NOT EXISTS invite_codes (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            created_by INTEGER REFERENCES users(id),
            used_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        INSERT INTO app_settings (key,value) VALUES ('invite_only','false') ON CONFLICT DO NOTHING;
    """)
    conn.commit()
    cur.close(); conn.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def calc_streak(workouts):
    if not workouts: return 0
    # Only count days with >=30 min total
    day_totals = {}
    for w in workouts:
        dk = str(w['log_date'])[:10]
        day_totals[dk] = day_totals.get(dk, 0) + (w.get('duration_minutes') or 0)
    qualified = set(dk for dk,total in day_totals.items() if total >= 30)
    streak = 0
    d = az_today()
    while d.isoformat() in qualified:
        streak += 1
        d -= timedelta(days=1)
    return streak

def calc_longest_streak(workouts):
    if not workouts: return 0
    day_totals = {}
    for w in workouts:
        dk = str(w['log_date'])[:10]
        day_totals[dk] = day_totals.get(dk, 0) + (w.get('duration_minutes') or 0)
    dates = sorted(dk for dk,total in day_totals.items() if total >= 30)
    if not dates: return 0
    best = cur = 1
    for i in range(1, len(dates)):
        diff = (date.fromisoformat(dates[i]) - date.fromisoformat(dates[i-1])).days
        cur = cur + 1 if diff == 1 else 1
        best = max(best, cur)
    return best

BADGE_DEFS = {
    'first_workout': {'label':'First Step',     'emoji':'👟','desc':'Logged your first workout'},
    'streak_7':      {'label':'Week Warrior',   'emoji':'🔥','desc':'7-day streak'},
    'streak_14':     {'label':'Fortnight Fire', 'emoji':'⚡','desc':'14-day streak'},
    'streak_30':     {'label':'Month on Fire',  'emoji':'🌋','desc':'30-day streak'},
    'perfect_month': {'label':'Perfect Month',  'emoji':'👑','desc':'Logged every day this month'},
    'comeback':      {'label':'Comeback Kid',   'emoji':'💪','desc':'Returned after 5+ day break'},
    'days_10':       {'label':'Double Digits',  'emoji':'🎯','desc':'10 days in a month'},
    'days_20':       {'label':'Grinder',        'emoji':'⚙️','desc':'20 days in a month'},
    'variety_5':     {'label':'Well Rounded',   'emoji':'🎨','desc':'5 different activity types'},
    'early_bird':    {'label':'Kingdom Builder','emoji':'✝️','desc':'One of the first 5 members'},
}

def check_badges(user_id, conn):
    cur = conn.cursor()
    cur.execute('SELECT log_date,activity FROM workouts WHERE user_id=%s ORDER BY log_date', (user_id,))
    ws = cur.fetchall()
    cur.execute('SELECT badge_key FROM badges WHERE user_id=%s', (user_id,))
    existing = set(r['badge_key'] for r in cur.fetchall())
    new_badges = []
    def award(k):
        if k not in existing:
            cur.execute('INSERT INTO badges(user_id,badge_key) VALUES(%s,%s) ON CONFLICT DO NOTHING',(user_id,k))
            new_badges.append(k); existing.add(k)
    if ws: award('first_workout')
    streak = calc_streak(ws)
    if streak>=7: award('streak_7')
    if streak>=14: award('streak_14')
    if streak>=30: award('streak_30')
    now = az_today()
    mk = now.strftime('%Y-%m')
    import calendar
    days_in_month = calendar.monthrange(now.year,now.month)[1]
    month_day_totals = {}
    for w in ws:
        dk = str(w['log_date'])[:10]
        if dk[:7]==mk:
            month_day_totals[dk] = month_day_totals.get(dk,0) + (w.get('duration_minutes') or 0)
    mc = sum(1 for t in month_day_totals.values() if t>=30)
    if mc>=days_in_month: award('perfect_month')
    if mc>=10: award('days_10')
    if mc>=20: award('days_20')
    acts = set(w['activity'] for w in ws)
    if len(acts)>=5: award('variety_5')
    dates_sorted = sorted(str(w['log_date'])[:10] for w in ws)
    today_s = az_today().isoformat()
    if len(dates_sorted)>=2 and dates_sorted[-1]==today_s:
        gap = (az_today()-date.fromisoformat(dates_sorted[-2])).days
        if gap>=6: award('comeback')
    cur.execute('SELECT COUNT(*) as cnt FROM users WHERE id<=%s',(user_id,))
    if cur.fetchone()['cnt']<=5: award('early_bird')
    conn.commit(); cur.close()
    return new_badges

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = (data.get('name') or '').strip()
    pin  = data.get('pin','')
    invite_code = data.get('invite_code','').strip()
    if not name or len(pin)!=4 or not pin.isdigit():
        return jsonify(error='Name and 4-digit PIN required'),400
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key='invite_only'")
    row = cur.fetchone()
    invite_only = row and row['value']=='true'
    if invite_only and name.lower()!=ADMIN_NAME:
        if not invite_code: return jsonify(error='An invite code is required to join'),403
        cur.execute('SELECT * FROM invite_codes WHERE code=%s AND used_by IS NULL',(invite_code,))
        if not cur.fetchone(): return jsonify(error='Invalid or already used invite code'),403
    is_admin = name.lower()==ADMIN_NAME
    try:
        cur.execute('INSERT INTO users(name,name_lower,pin_hash,is_admin) VALUES(%s,%s,%s,%s) RETURNING id,name,is_admin',
                    (name,name.lower(),hash_pin(pin),is_admin))
        row = cur.fetchone()
        if invite_only and invite_code:
            cur.execute('UPDATE invite_codes SET used_by=%s WHERE code=%s',(row['id'],invite_code))
        conn.commit()
        return jsonify(id=row['id'],name=row['name'],is_admin=row['is_admin'])
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); return jsonify(error='Name already taken'),409
    finally:
        cur.close(); conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    name = (data.get('name') or '').strip().lower()
    pin  = data.get('pin','')
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE name_lower=%s',(name,))
    user = cur.fetchone(); cur.close(); conn.close()
    if not user or user['pin_hash']!=hash_pin(pin):
        return jsonify(error='Invalid name or PIN'),401
    return jsonify(id=user['id'],name=user['name'],is_admin=user['is_admin'])

# ── Workouts ──────────────────────────────────────────────────────────────────
@app.route('/api/workouts', methods=['POST'])
def log_workout():
    data = request.json
    user_id=data.get('user_id'); log_date=data.get('log_date')
    activity=data.get('activity','').strip(); duration=data.get('duration_minutes')
    notes=data.get('notes','').strip()
    if not all([user_id,log_date,activity,duration]): return jsonify(error='Missing fields'),400
    if int(duration)<1: return jsonify(error='Duration must be at least 1 minute'),400
    try:
        log_d = date.fromisoformat(log_date)
        if log_d>az_today(): return jsonify(error='Cannot log future dates'),400
        if (az_today()-log_d).days>7: return jsonify(error='Can only log up to 7 days back'),400
    except: return jsonify(error='Invalid date'),400
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('INSERT INTO workouts(user_id,log_date,activity,duration_minutes,notes) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                    (user_id,log_date,activity,int(duration),notes))
        wid = cur.fetchone()['id']; conn.commit()
        new_badges = check_badges(user_id,conn)
        # Check if day now qualifies (>=30 min total)
        cur.execute('SELECT COALESCE(SUM(duration_minutes),0) as total FROM workouts WHERE user_id=%s AND log_date=%s',(user_id,log_date))
        day_total = cur.fetchone()['total']
        return jsonify(id=wid,new_badges=new_badges,day_total=day_total,day_qualifies=day_total>=30)
    except Exception as ex:
        conn.rollback(); return jsonify(error=str(ex)),500
    finally:
        cur.close(); conn.close()

@app.route('/api/workouts/<int:user_id>/<log_date>', methods=['DELETE'])
def delete_workout(user_id,log_date):
    conn=get_db(); cur=conn.cursor()
    # Delete all sessions for that day, or by workout id if numeric
    try:
        wid = int(log_date)
        cur.execute('DELETE FROM workouts WHERE id=%s AND user_id=%s',(wid,user_id))
    except ValueError:
        cur.execute('DELETE FROM workouts WHERE user_id=%s AND log_date=%s',(user_id,log_date))
    conn.commit(); cur.close(); conn.close()
    return jsonify(ok=True)

@app.route('/api/workouts/<int:user_id>')
def get_workouts(user_id):
    month=request.args.get('month')
    conn=get_db(); cur=conn.cursor()
    if month:
        cur.execute("SELECT id, user_id, TO_CHAR(log_date,'YYYY-MM-DD') as log_date, activity, duration_minutes, notes FROM workouts WHERE user_id=%s AND TO_CHAR(log_date,'YYYY-MM')=%s ORDER BY log_date DESC",(user_id,month))
    else:
        cur.execute("SELECT id, user_id, TO_CHAR(log_date,'YYYY-MM-DD') as log_date, activity, duration_minutes, notes FROM workouts WHERE user_id=%s ORDER BY log_date DESC",(user_id,))
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

# ── Reactions ─────────────────────────────────────────────────────────────────
@app.route('/api/reactions',methods=['POST'])
def add_reaction():
    data=request.json
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('INSERT INTO reactions(workout_id,user_id,emoji) VALUES(%s,%s,%s) ON CONFLICT(workout_id,user_id) DO UPDATE SET emoji=%s',
                    (data['workout_id'],data['user_id'],data['emoji'],data['emoji']))
        conn.commit(); return jsonify(ok=True)
    finally:
        cur.close(); conn.close()

@app.route('/api/reactions/<int:workout_id>/<int:user_id>',methods=['DELETE'])
def remove_reaction(workout_id,user_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute('DELETE FROM reactions WHERE workout_id=%s AND user_id=%s',(workout_id,user_id))
    conn.commit(); cur.close(); conn.close()
    return jsonify(ok=True)

# ── Feed ──────────────────────────────────────────────────────────────────────
@app.route('/api/feed')
def feed():
    conn=get_db(); cur=conn.cursor()
    cur.execute("""
        SELECT w.id,TO_CHAR(w.log_date,'YYYY-MM-DD') as log_date,w.activity,w.duration_minutes,w.notes,
               u.name as user_name,u.id as user_id,
               COALESCE(json_agg(DISTINCT json_build_object('emoji',r.emoji,'user_id',r.user_id))
               FILTER(WHERE r.id IS NOT NULL),'[]') as reactions,
               0 as comment_count
        FROM workouts w JOIN users u ON u.id=w.user_id
        LEFT JOIN reactions r ON r.workout_id=w.id
        WHERE w.log_date>=CURRENT_DATE-INTERVAL '7 days'
        GROUP BY w.id,u.id ORDER BY w.log_date DESC,w.logged_at DESC LIMIT 30
    """)
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

# ── Badges ────────────────────────────────────────────────────────────────────
@app.route('/api/badges/<int:user_id>')
def get_badges(user_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute('SELECT badge_key,earned_at FROM badges WHERE user_id=%s ORDER BY earned_at',(user_id,))
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([{**BADGE_DEFS[r['badge_key']],'key':r['badge_key'],'earned_at':str(r['earned_at'])} for r in rows if r['badge_key'] in BADGE_DEFS])

# ── Records ───────────────────────────────────────────────────────────────────
@app.route('/api/records/<int:user_id>')
def get_records(user_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute("""SELECT TO_CHAR(log_date,'YYYY-MM-DD') as log_date, activity, duration_minutes FROM workouts WHERE user_id=%s ORDER BY log_date""",(user_id,))
    ws=cur.fetchall(); cur.close(); conn.close()
    day_totals={}
    for w in ws:
        dk=str(w['log_date'])[:10]; day_totals[dk]=day_totals.get(dk,0)+(w.get('duration_minutes') or 0)
    mc2={}
    for dk,total in day_totals.items():
        if total>=30:
            mk=dk[:7]; mc2[mk]=mc2.get(mk,0)+1
    best_mk=max(mc2,key=mc2.get) if mc2 else None
    ac={}
    for w in ws: ac[w['activity']]=ac.get(w['activity'],0)+1
    return jsonify(longest_streak=calc_longest_streak(ws),current_streak=calc_streak(ws),
                   total_workouts=len(ws),best_month=best_mk,best_month_days=mc2.get(best_mk,0),
                   favorite_activity=max(ac,key=ac.get) if ac else None)

# ── Leaderboard ───────────────────────────────────────────────────────────────
@app.route('/api/leaderboard')
def leaderboard():
    month=request.args.get('month',az_today().strftime('%Y-%m'))
    conn=get_db(); cur=conn.cursor()
    cur.execute('SELECT id,name FROM users ORDER BY id')
    users=cur.fetchall(); board=[]
    for u in users:
        cur.execute("SELECT log_date,duration_minutes FROM workouts WHERE user_id=%s AND TO_CHAR(log_date,'YYYY-MM')=%s",(u['id'],month))
        mws=cur.fetchall()
        cur.execute('SELECT log_date,duration_minutes FROM workouts WHERE user_id=%s ORDER BY log_date DESC',(u['id'],))
        aws=cur.fetchall()
        cur.execute('SELECT badge_key FROM badges WHERE user_id=%s',(u['id'],))
        bkeys=[r['badge_key'] for r in cur.fetchall()]
        # Count days with >=30 min total for the month
        day_totals_m = {}
        for w in mws:
            dk = str(w['log_date'])[:10]
            day_totals_m[dk] = day_totals_m.get(dk,0) + (w.get('duration_minutes') or 0)
        days = sum(1 for t in day_totals_m.values() if t>=30)
        total_mins = sum((w.get('duration_minutes') or 0) for w in mws)
        total_hours = round(total_mins / 60, 1)
        streak=calc_streak([dict(w) for w in aws]); pts=days+(streak*2)
        board.append(dict(id=u['id'],name=u['name'],totalDays=days,streak=streak,points=pts,badges=bkeys,totalHours=total_hours))
    cur.close(); conn.close()
    board.sort(key=lambda x:(-x['points'],-x['streak'],-x['totalDays']))
    return jsonify(board)

# ── Head-to-head ──────────────────────────────────────────────────────────────
@app.route('/api/h2h')
def h2h():
    u1=request.args.get('u1',type=int); u2=request.args.get('u2',type=int)
    month=request.args.get('month',az_today().strftime('%Y-%m'))
    conn=get_db(); cur=conn.cursor(); result={}
    for uid in [u1,u2]:
        cur.execute("SELECT log_date,duration_minutes FROM workouts WHERE user_id=%s AND TO_CHAR(log_date,'YYYY-MM')=%s",(uid,month))
        mws=cur.fetchall()
        cur.execute('SELECT log_date,duration_minutes FROM workouts WHERE user_id=%s ORDER BY log_date DESC',(uid,))
        aws=cur.fetchall()
        cur.execute('SELECT name FROM users WHERE id=%s',(uid,))
        name=cur.fetchone()['name']
        dt_m={};
        for w in mws:
            dk=str(w['log_date'])[:10]; dt_m[dk]=dt_m.get(dk,0)+(w.get('duration_minutes') or 0)
        days=sum(1 for t in dt_m.values() if t>=30)
        streak=calc_streak([dict(w) for w in aws])
        result[str(uid)]=dict(name=name,days=days,streak=streak,points=days+streak*2)
    cur.close(); conn.close(); return jsonify(result)

# ── Monthly winners ───────────────────────────────────────────────────────────
@app.route('/api/winners')
def get_winners():
    conn=get_db(); cur=conn.cursor()
    cur.execute('SELECT * FROM monthly_winners ORDER BY month DESC LIMIT 12')
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/winners',methods=['POST'])
def record_winner():
    data=request.json; conn=get_db(); cur=conn.cursor()
    winner_type = data.get('winner_type','points')
    total_hours = data.get('total_hours',0)
    month_key = data['month'] + '_' + winner_type
    cur.execute('''INSERT INTO monthly_winners(month,winner_name,points,total_days,streak,total_hours,winner_type)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING''',
                (month_key,data['winner_name'],data['points'],data['total_days'],data['streak'],total_hours,winner_type))
    conn.commit(); cur.close(); conn.close(); return jsonify(ok=True)

# ── Admin ─────────────────────────────────────────────────────────────────────
@app.route('/api/admin/users')
def admin_users():
    conn=get_db(); cur=conn.cursor()
    cur.execute('''SELECT u.id,u.name,u.created_at,COUNT(w.id) as total_workouts,MAX(w.log_date) as last_workout
                   FROM users u LEFT JOIN workouts w ON w.user_id=u.id GROUP BY u.id ORDER BY u.id''')
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/users/<int:user_id>',methods=['DELETE'])
def admin_delete_user(user_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute('DELETE FROM reactions WHERE user_id=%s',(user_id,))
    cur.execute('DELETE FROM workouts WHERE user_id=%s',(user_id,))
    cur.execute('DELETE FROM badges WHERE user_id=%s',(user_id,))
    cur.execute('DELETE FROM users WHERE id=%s',(user_id,))
    conn.commit(); cur.close(); conn.close(); return jsonify(ok=True)

@app.route('/api/admin/reset-pin',methods=['POST'])
def admin_reset_pin():
    data=request.json; conn=get_db(); cur=conn.cursor()
    cur.execute('UPDATE users SET pin_hash=%s WHERE id=%s',(hash_pin(data['new_pin']),data['user_id']))
    conn.commit(); cur.close(); conn.close(); return jsonify(ok=True)


@app.route('/api/admin/settings')
def get_settings():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT key,value FROM app_settings")
    rows={r['key']:r['value'] for r in cur.fetchall()}
    cur.close(); conn.close()
    return jsonify(rows)

@app.route('/api/prize')
def get_prize():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key='monthly_prize'")
    row=cur.fetchone(); cur.close(); conn.close()
    return jsonify(prize=row['value'] if row else '')

@app.route('/api/prize', methods=['POST'])
def set_prize():
    data=request.json; prize=data.get('prize','')
    conn=get_db(); cur=conn.cursor()
    cur.execute("INSERT INTO app_settings(key,value) VALUES('monthly_prize',%s) ON CONFLICT(key) DO UPDATE SET value=%s",
                (prize, prize))
    conn.commit(); cur.close(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/settings',methods=['POST'])
def update_settings():
    data=request.json; conn=get_db(); cur=conn.cursor()
    for k,v in data.items():
        if k in ('invite_only','monthly_prize'):  # only allow known keys
            cur.execute('INSERT INTO app_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=%s',(k,str(v),str(v)))
    conn.commit(); cur.close(); conn.close(); return jsonify(ok=True)

@app.route('/api/invites',methods=['POST'])
def create_invite():
    data=request.json; code=secrets.token_urlsafe(8)
    conn=get_db(); cur=conn.cursor()
    cur.execute('INSERT INTO invite_codes(code,created_by) VALUES(%s,%s) RETURNING code',(code,data['user_id']))
    row=cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return jsonify(code=row['code'])

@app.route('/api/invites')
def list_invites():
    conn=get_db(); cur=conn.cursor()
    cur.execute('''SELECT i.code,i.created_at,u.name as used_by_name
                   FROM invite_codes i LEFT JOIN users u ON u.id=i.used_by ORDER BY i.created_at DESC''')
    rows=cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])



@app.route('/api/comments/<int:workout_id>')
def get_comments(workout_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute("""SELECT c.id, c.parent_id, c.workout_id, c.body, c.created_at, u.name as user_name
                   FROM comments c JOIN users u ON c.user_id=u.id
                   WHERE c.workout_id=%s ORDER BY c.created_at ASC""", (workout_id,))
    rows=[dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r['created_at'] = str(r['created_at'])
    return jsonify(rows)

@app.route('/api/comments', methods=['POST'])
def add_comment():
    data=request.json
    workout_id=data.get('workout_id')
    user_id=data.get('user_id')
    body=(data.get('body') or '').strip()
    parent_id=data.get('parent_id')
    if not body or not workout_id or not user_id:
        return jsonify(error='Missing fields'), 400
    conn=get_db(); cur=conn.cursor()
    cur.execute('INSERT INTO comments(workout_id,user_id,body,parent_id) VALUES(%s,%s,%s,%s) RETURNING id',
                (workout_id, user_id, body, parent_id))
    cid=cur.fetchone()['id']; conn.commit(); cur.close(); conn.close()
    return jsonify(ok=True, id=cid)

@app.route('/api/change-name', methods=['POST'])
def change_name():
    data = request.json
    user_id = data.get('user_id')
    new_name = (data.get('new_name') or '').strip()
    if not new_name: return jsonify(error='Name required'), 400
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('UPDATE users SET name=%s, name_lower=%s WHERE id=%s',
                    (new_name, new_name.lower(), user_id))
        conn.commit()
        return jsonify(ok=True)
    except Exception as e:
        conn.rollback()
        if 'unique' in str(e).lower():
            return jsonify(error='Name already taken'), 409
        return jsonify(error='Could not update name'), 500
    finally:
        cur.close(); conn.close()

@app.route('/',defaults={'path':''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join('public',path)):
        return send_from_directory('public',path)
    return send_from_directory('public','index.html')

if __name__=='__main__':
    init_db()
    port=int(os.environ.get('PORT',3000))
    print(f'KingdomFit running on http://localhost:{port}')
    app.run(host='0.0.0.0',port=port,debug=False)
