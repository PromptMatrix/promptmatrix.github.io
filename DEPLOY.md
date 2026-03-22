# PromptMatrix — Deploy to Vercel + Supabase (Free)

Total cost: $0. Time: ~20 minutes.

---

## What you need before starting

- GitHub account
- Vercel account (free) — vercel.com
- Supabase account (free) — supabase.com
- Upstash account (free, optional but recommended) — upstash.com
- Resend account (free) — resend.com

---

## Step 1 — Supabase (database)

1. Go to supabase.com → New project
2. Choose a name, set a strong password, pick the region closest to your users
3. Wait ~2 minutes for provisioning

4. Go to **Settings → Database → Connection string → Transaction pooler**
   - Copy the URI — it looks like:
     `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
   - **Important:** use port 6543 (Transaction pooler), NOT 5432 (direct)
   - Replace `[your-password]` with the password you set in step 2

5. Save this URL — you'll need it in Step 3.

---

## Step 2 — Upstash Redis (cache, optional)

Skip this if you want to keep it simple. The app works without it — serve
requests just hit Supabase directly (~100ms instead of ~30ms).

1. Go to console.upstash.com → Create Database
2. Choose a name, pick the region closest to your Supabase region
3. Go to the database → REST API tab
4. Copy `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`

---

## Step 3 — Resend (email)

1. Go to resend.com → Sign up
2. Settings → API Keys → Create API Key
3. Copy the key (starts with `re_`)
4. Add your domain or use the sandbox `onboarding@resend.dev` for testing

---

## Step 4 — GitHub

1. Create a new repository: `promptmatrix-backend`
2. Push this entire folder to it:

```bash
git init
git add .
git commit -m "Initial PromptMatrix backend"
git remote add origin https://github.com/YOUR_USERNAME/promptmatrix-backend.git
git push -u origin main
```

---

## Step 5 — Vercel

1. Go to vercel.com → Add New Project → Import from GitHub
2. Select `promptmatrix-backend`
3. **Do not change any build settings** — Vercel auto-detects `vercel.json`
4. Before deploying, go to **Environment Variables** and add every variable below

### Environment Variables to add in Vercel dashboard

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Your Supabase transaction pooler URL from Step 1 |
| `JWT_SECRET_KEY` | Run: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | Run: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_ENV` | `production` |
| `APP_URL` | `https://your-project.vercel.app` (fill after first deploy) |
| `FRONTEND_URL` | `https://promptmatrix.github.io` |
| `RESEND_API_KEY` | Your Resend key from Step 3 |
| `FROM_EMAIL` | `noreply@promptmatrix.io` or your verified domain |
| `UPSTASH_REDIS_REST_URL` | From Step 2 (leave blank to skip cache) |
| `UPSTASH_REDIS_REST_TOKEN` | From Step 2 (leave blank to skip cache) |
| `RAZORPAY_KEY_ID` | Your Razorpay key (for payment webhooks) |
| `RAZORPAY_WEBHOOK_SECRET` | Your Razorpay webhook secret |

5. Click **Deploy**

First deploy takes ~3 minutes. Subsequent deploys: ~30 seconds.

---

## Step 6 — Connect your app HTML

Open `promptmatrix-app.html` and replace the API constant:

```javascript
// Find this line near the top of the <script> section:
const API = 'REPLACE_WITH_YOUR_VERCEL_BACKEND_URL';

// Replace with your actual Vercel URL, e.g.:
const API = 'https://promptmatrix-backend-abc123.vercel.app';
```

The URL is visible on your Vercel project dashboard.

---

## Step 7 — Verify everything works

```bash
# Health check
curl https://your-project.vercel.app/api/status

# Expected response:
# {"status": "ok", "version": "0.1.0", "env": "production"}
```

If you get a 200, the backend is live and connected to Supabase.

---

## Step 8 — Razorpay webhook (for payments)

1. Razorpay dashboard → Webhooks → Add webhook
2. URL: `https://your-project.vercel.app/api/v1/webhooks/razorpay`
3. Events: `payment.captured`
4. Secret: use the same value as `RAZORPAY_WEBHOOK_SECRET`

**Important:** Your Razorpay payment link must include the `org_id` in the
payment notes so the webhook knows which workspace to upgrade:
- In Razorpay → Payment Links → create link with custom note field `org_id`
- Or pass it as a query param in the checkout flow

---

## Free tier limits

| Service | Free limit | Hits limit when |
|---------|-----------|-----------------|
| Supabase | 500MB DB, 2GB bandwidth | ~50k prompts stored |
| **Supabase pause** | **After 7 days inactivity** | **Your project sleeps if unused** |
| Vercel | 100GB bandwidth, 100k function invocations/day | ~100k serve requests/day |
| Upstash Redis | 10,000 commands/day | ~5,000 serve requests/day |
| Resend | 100 emails/day | ~100 invites or approvals/day |

**Supabase free tier gotcha:** If no one uses the app for 7 days, Supabase
pauses the database. First request after a pause takes 10-30 seconds to wake.
This is fine for beta. The `pool_pre_ping=True` setting in database.py handles
this gracefully — stale connections are dropped and recreated automatically.

To avoid pauses: upgrade to Supabase Pro ($25/month), or just use it daily.

---

## Local development

```bash
# 1. Copy .env.example to .env and fill in values
cp .env.example .env

# 2. Install deps
pip install -r requirements.txt

# 3. Run
uvicorn main:app --reload --port 8000

# 4. Test
curl http://localhost:8000/api/status
```

For local dev you can use SQLite by setting:
```
DATABASE_URL=sqlite:///./promptmatrix.db
```

---

## When you outgrow free tier

**Database:** Upgrade Supabase to Pro ($25/mo) — removes pause, 8GB storage, daily backups
**Cache:** Upstash paid starts at $0.20 per 100k commands
**Hosting:** Vercel Pro ($20/mo) — removes function timeout limits, more bandwidth
**Email:** Resend paid starts at $20/mo for 50k emails

You can run PromptMatrix at meaningful beta scale (hundreds of users,
thousands of serve requests/day) entirely on free tier.
