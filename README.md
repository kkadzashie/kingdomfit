# KingdomFit

A faith-based fitness accountability app for a private community. Members log daily workouts, earn badges, compete on a leaderboard, and get coaching from scripture-grounded AI coaches.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3 / Flask |
| Database | Supabase PostgreSQL (via `DATABASE_URL`) |
| Frontend | Single HTML file — vanilla JS, inline CSS, no build step |
| Hosting | Render.com (web service + managed Postgres) |
| AI Coaches | Anthropic Claude API (`claude-sonnet-4-20250514`) |
| Mobile | PWA — "Add to Home Screen" on iOS and Android |

---

## Project Structure

```
kingdomfit/
├── server.py          # Flask app — all routes and DB logic (~571 lines)
├── requirements.txt   # Python dependencies
└── public/
    └── index.html     # Entire SPA — HTML, CSS, JS in one file (~375 KB)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (from Supabase or Render) |
| `PORT` | No | Server port (default: 3000) |

The Anthropic API key is entered by the user in-app in the Coaches screen and stored in browser `localStorage`. It is sent directly from the browser to the Anthropic API — it never touches the Flask server.

---

## Running Locally

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:pass@host/dbname"
python server.py
# open http://localhost:3000
```

---

## Database Schema

The `init_db()` function in `server.py` creates all tables on startup if they don't exist.

### `users`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| name | TEXT NOT NULL | Display name |
| name_lower | TEXT UNIQUE NOT NULL | Lowercase for case-insensitive lookup |
| pin_hash | TEXT NOT NULL | SHA-256 hash of 4-digit PIN |
| is_admin | BOOLEAN | Default false |
| created_at | DATE | Default current date |

### `workouts`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| user_id | INT FK → users | |
| log_date | DATE NOT NULL | |
| activity | TEXT NOT NULL | e.g. "Running", "Weights" |
| duration_minutes | INT NOT NULL | |
| notes | TEXT | Default empty string |
| logged_at | TIMESTAMP | Default now() |

Multiple workout entries per day are allowed (multiple sessions).

### `reactions`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| workout_id | INT FK → workouts (CASCADE) | |
| user_id | INT FK → users | |
| emoji | TEXT NOT NULL | |
| — | UNIQUE(workout_id, user_id) | One reaction per user per workout |

### `badges`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| user_id | INT FK → users | |
| badge_key | TEXT NOT NULL | See badge definitions below |
| earned_at | DATE | Default current date |
| — | UNIQUE(user_id, badge_key) | Each badge awarded once per user |

### `monthly_winners`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| month | TEXT NOT NULL | Format: `YYYY-MM_points` or `YYYY-MM_hours` |
| winner_name | TEXT | |
| points | INT | |
| total_days | INT | |
| streak | INT | |
| total_hours | FLOAT | |
| winner_type | TEXT | `'points'` or `'hours'` |

### `invite_codes`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| code | TEXT UNIQUE | URL-safe base64 token |
| created_by | INT FK → users | |
| used_by | INT FK → users | Null until redeemed |
| created_at | TIMESTAMP | |

### `comments`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| workout_id | INT FK → workouts (CASCADE) | |
| user_id | INT FK → users | |
| parent_id | INT FK → comments (CASCADE) | Null for top-level; set for replies |
| body | TEXT NOT NULL | |
| created_at | TIMESTAMP | |

### `app_settings`
| Column | Type | Notes |
|---|---|---|
| key | TEXT PK | |
| value | TEXT | |

Known keys: `invite_only` (`"true"` / `"false"`), `monthly_prize` (display string).

---

## API Endpoints

All endpoints return JSON. Errors return `{"error": "message"}` with an appropriate HTTP status code.

### Authentication

#### `POST /api/register`
Register a new user.

**Body:**
```json
{ "name": "Jane", "pin": "1234", "invite_code": "abc123" }
```
`invite_code` is required only when the `invite_only` setting is `"true"`.

**Response:**
```json
{ "id": 1, "name": "Jane", "is_admin": false }
```

---

#### `POST /api/login`
Login with name and PIN.

**Body:**
```json
{ "name": "Jane", "pin": "1234" }
```

**Response:**
```json
{ "id": 1, "name": "Jane", "is_admin": false }
```

---

### Workouts

#### `POST /api/workouts`
Log a workout entry.

**Body:**
```json
{
  "user_id": 1,
  "log_date": "2025-06-15",
  "activity": "Running",
  "duration_minutes": 45,
  "notes": "Morning 5K"
}
```

Constraints: `log_date` must be within the past 7 days. `duration_minutes` must be ≥ 1.

**Response:**
```json
{
  "id": 42,
  "new_badges": ["streak_7"],
  "day_total": 75,
  "day_qualifies": true
}
```

`day_qualifies` is true when the total minutes logged for that date is ≥ 30.

---

#### `DELETE /api/workouts/<user_id>/<log_date>`
Delete a workout. Pass a numeric workout `id` or a `YYYY-MM-DD` date string as `<log_date>`.

---

#### `GET /api/workouts/<user_id>`
Get all workouts for a user.

**Query params:** `month=YYYY-MM` (optional filter)

**Response:** Array of workout objects.

---

### Feed & Social

#### `GET /api/feed`
Get workouts from the past 7 days with reactions and comment counts.

**Response:** Array of workout objects, each including `user_name` and `reactions` array.

---

#### `POST /api/reactions`
Add or update an emoji reaction to a workout. Upserts — one reaction per user per workout.

**Body:**
```json
{ "workout_id": 42, "user_id": 1, "emoji": "🔥" }
```

---

#### `DELETE /api/reactions/<workout_id>/<user_id>`
Remove a user's reaction from a workout.

---

#### `GET /api/comments/<workout_id>`
Get all comments and replies for a workout.

**Response:**
```json
[
  { "id": 1, "parent_id": null, "body": "Nice work!", "user_name": "Jane", "created_at": "..." }
]
```

---

#### `POST /api/comments`
Post a comment or reply.

**Body:**
```json
{ "workout_id": 42, "user_id": 1, "body": "Keep it up!", "parent_id": null }
```

Set `parent_id` to the parent comment's `id` to create a reply.

---

### Leaderboard & Stats

#### `GET /api/leaderboard`
Get the monthly leaderboard.

**Query params:** `month=YYYY-MM` (default: current month in Arizona time)

**Response:**
```json
[
  {
    "id": 1, "name": "Jane",
    "totalDays": 15, "streak": 5,
    "points": 25, "badges": 3, "totalHours": 12.5
  }
]
```

Sorted by `points` desc, then `streak` desc, then `totalDays` desc.

---

#### `GET /api/h2h`
Head-to-head comparison between two users.

**Query params:** `u1=<id>`, `u2=<id>`, `month=YYYY-MM`

**Response:**
```json
{
  "u1": { "name": "Jane", "days": 15, "streak": 5, "points": 25 },
  "u2": { "name": "John", "days": 12, "streak": 3, "points": 18 }
}
```

---

#### `GET /api/badges/<user_id>`
Get a user's earned badges.

**Response:**
```json
[{ "badge_key": "streak_7", "label": "Week Warrior", "emoji": "🔥", "desc": "...", "earned_at": "2025-06-01" }]
```

---

#### `GET /api/records/<user_id>`
Get a user's personal records.

**Response:**
```json
{
  "longest_streak": 14,
  "current_streak": 5,
  "total_workouts": 120,
  "best_month": "2025-05",
  "best_month_days": 28,
  "favorite_activity": "Running"
}
```

---

### Monthly Winners

#### `GET /api/winners`
Get the last 12 monthly winners.

---

#### `POST /api/winners`
Record a monthly winner (admin action from the app).

**Body:**
```json
{
  "month": "2025-05",
  "winner_name": "Jane",
  "points": 45,
  "total_days": 20,
  "streak": 8,
  "total_hours": 18.5,
  "winner_type": "points"
}
```

---

### Admin

#### `GET /api/admin/users`
List all users with stats.

#### `DELETE /api/admin/users/<user_id>`
Delete a user and all their data (workouts, reactions, badges).

#### `POST /api/admin/reset-pin`
Reset a user's PIN.

**Body:** `{ "user_id": 1, "new_pin": "5678" }`

#### `GET /api/admin/settings`
Get app settings (`invite_only`, `monthly_prize`).

#### `POST /api/admin/settings`
Update app settings.

**Body:** `{ "invite_only": "true", "monthly_prize": "Nike Gift Card" }`

Only the keys `invite_only` and `monthly_prize` are accepted.

#### `GET /api/prize` / `POST /api/prize`
Get or set the monthly prize description.

#### `POST /api/invites`
Create an invite code.

**Body:** `{ "user_id": 1 }`  
**Response:** `{ "code": "xK9mZ..." }`

#### `GET /api/invites`
List all invite codes with status and creator/user info.

---

### User Settings

#### `POST /api/change-name`
Change a user's display name.

**Body:** `{ "user_id": 1, "new_name": "Jane D." }`

---

## Business Rules

### Timezone
All date logic runs in **Arizona time** (`America/Phoenix`, UTC-7, no DST). The helpers `az_today()` and `az_month()` in `server.py` ensure consistent date boundaries regardless of server location.

### 30-Minute Threshold
A calendar day "qualifies" (counts toward points, streaks, and badges) when the sum of all workout durations logged for that date is **≥ 30 minutes**. Individual entries can be shorter as long as the daily total reaches 30.

### Points Formula
```
points = total_qualifying_days_this_month + (current_streak × 2)
```

- `total_qualifying_days_this_month` — count of days in the current month where the 30-minute threshold was met
- `current_streak` — consecutive qualifying days running backward from today

Example: 15 qualifying days + a 5-day streak → `15 + (5 × 2) = 25 points`.

### Streak Calculation
Streaks count backward from today in Arizona time. A day breaks the streak if no workout reaching the 30-minute threshold was logged.

### Backdating
Workouts can be logged for any date within the **past 7 days** only.

### Admin Account
A user named `mrs. dk` (case-insensitive) is automatically granted admin privileges at registration. The admin can manage users, reset PINs, control invite-only mode, and manage monthly winners.

### Invite-Only Mode
When `invite_only` is `"true"`, new registrations require a valid, unused invite code. Admins are exempt. Codes are single-use; once consumed they record `used_by`.

---

## Badges

| Badge Key | Emoji | Label | Condition |
|---|---|---|---|
| `first_workout` | 👟 | First Step | Logged first workout |
| `streak_7` | 🔥 | Week Warrior | 7-day qualifying streak |
| `streak_14` | ⚡ | Fortnight Fire | 14-day qualifying streak |
| `streak_30` | 🌋 | Month on Fire | 30-day qualifying streak |
| `perfect_month` | 👑 | Perfect Month | Every day of current month qualifies |
| `days_10` | 🎯 | Double Digits | 10+ qualifying days this month |
| `days_20` | ⚙️ | Grinder | 20+ qualifying days this month |
| `variety_5` | 🎨 | Well Rounded | 5+ distinct activity types logged |
| `comeback` | 💪 | Comeback Kid | Logged workout after 5+ day gap |
| `early_bird` | ✝️ | Kingdom Builder | One of first 5 registered users |

Badges are checked and awarded automatically when a workout is logged (`POST /api/workouts`).

---

## AI Coaches

The Coaches tab exposes two scripture-grounded AI personas powered by the Anthropic Claude API. The API call is made **client-side** from the browser; the user must supply their own Anthropic API key in the app settings.

**Model:** `claude-sonnet-4-20250514`  
**Endpoint:** `https://api.anthropic.com/v1/messages`  
**Max tokens:** 1000 per response  
**Context:** Full conversation history is maintained in memory per session.

### Abigail — Mental Wellness Coach 👸
> "She was a woman of good understanding." — 1 Samuel 25:3

Addresses emotional health, mental wellness, and spiritual identity. Grounded in Isaiah 43:2, Romans 8:37, Philippians 4:6–7, 2 Timothy 1:7, Isaiah 61:3, Psalm 34:18, Joel 2:25, John 10:10. Never diagnoses; refers users to a licensed counselor for clinical concerns and to a pastor for spiritual crisis. Offers prayer. Responses capped at ~200 words.

### Anna — Nutrition Coach 🌿
> "She served God with fastings and prayers night and day." — Luke 2:37

Addresses nutrition and body stewardship. Grounded in 1 Corinthians 6:19–20, Daniel 1:12–15, 1 Corinthians 9:27, Romans 12:1, 3 John 1:2, Proverbs 31:17, Genesis 1:29, Isaiah 40:31. Never provides medical nutrition therapy; refers users to a doctor or registered dietitian for medical concerns. Responses capped at ~200 words.

---

## Frontend Architecture

The entire UI lives in `public/index.html` — a single-file SPA with no build process, no framework, and no external JS dependencies.

**Design system:**
- Dark theme, mobile-first (max-width 430px)
- Fonts: DM Sans (body) + DM Serif Display (headings) via Google Fonts
- Accent colors: Gold `#c9a84c`, Green `#4ade80`, Red `#f87171`

**Screen flow:**
1. **Welcome** — login or register CTA (unauthenticated)
2. **Login / Register** — PIN keypad, name entry
3. **Home** — main app with 5 bottom-nav tabs:
   - **Home** — today's workouts, calendar, monthly stats
   - **Board** — leaderboard, head-to-head, monthly champions
   - **Feed** — community workout feed with reactions and comments
   - **Coaches** — Abigail & Anna AI chat
   - **Me** — profile, badges, records, settings, admin panel

---

## iOS & Android — PWA Install

KingdomFit ships as a **Progressive Web App**. There is no native Xcode or Android Studio project, no Capacitor, no Cordova.

### iOS (Safari)
1. Open the app URL in Safari.
2. Tap the **Share** button → **Add to Home Screen**.
3. The app launches full-screen with no browser chrome (`apple-mobile-web-app-capable`).
4. Safe-area insets handle the notch/home indicator via `env(safe-area-inset-bottom)`.

### Android (Chrome)
1. Open the app URL in Chrome.
2. Tap the browser menu → **Add to Home screen** (or accept the install banner).
3. The app installs to the launcher and opens standalone.

### Theme Color
System UI bars use `#0a0a0a` (dark) as set in `<meta name="theme-color">`.

### Converting to a Native Binary (optional, not currently implemented)
If a native app store listing is ever needed, [Capacitor](https://capacitorjs.com) can wrap the existing SPA with minimal changes:
```bash
npm init @capacitor/app
npx cap add ios
npx cap add android
npx cap copy
npx cap open ios        # opens Xcode
npx cap open android    # opens Android Studio
```
No code changes are required to the HTML/JS — Capacitor serves the existing `public/` directory.

---

## Deployment (Render.com)

1. Connect the GitHub repo to a new **Web Service** on Render.
2. Set **Build Command:** `pip install -r requirements.txt`
3. Set **Start Command:** `python server.py`
4. Add a **PostgreSQL** database on Render; copy the internal `DATABASE_URL` into the web service environment.
5. The `init_db()` function runs at startup and creates all tables automatically.

---

## Security Notes

- Passwords are stored as SHA-256 hashes of the 4-digit PIN. This is intentionally lightweight for a private community app.
- SQL queries use parameterized statements throughout — no string interpolation.
- The Anthropic API key is stored in browser `localStorage` and sent directly to Anthropic. It is never sent to the Flask server.
- Admin access is gated by the `is_admin` flag set at registration (name match) or manually in the database. There is no server-side session auth — user ID is passed in request bodies and trusted. This is appropriate for a closed, trusted community.
