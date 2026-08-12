# Employee Feedback & Recognition

A simple Streamlit app for employee Recognition, Feedback, and Warning records.

## V1 Features

- Import an Employee Master from Excel/CSV.
- Uses **用户编码 / User ID** as the unique employee key.
- Re-uploading the master **updates existing employees and adds new employees**.
- Employees missing from a later upload are **not deleted**.
- Historical Feedback / Warning / Recognition records are never overwritten by a master-data refresh.
- Homepage groups employees by **考勤组 / Attendance Group**.
- Employees inside each group are ranked by **Feedback count (high to low)**.
- Fuzzy search by **name / User ID / ERP**.
- Click an employee name to open the employee profile.
- Add Recognition.
- Add Feedback, Verbal Warning, Written Warning, or Final Warning.
- Export a full Excel backup at any time.
- Performance/Score is intentionally ignored in V1.

## Data Storage

The app supports two modes:

### 1. Supabase (recommended for online deployment)
Use this for permanent cloud storage. Data remains in Supabase even if the Streamlit app restarts or is redeployed.

### 2. SQLite fallback
If Supabase is not configured, the app automatically creates `employee_feedback.db` beside `app.py`. This is convenient for local testing, but should **not** be relied on for permanent storage on Streamlit Community Cloud.

---

# Setup - Recommended Cloud Version

## Step 1 - Create a Supabase project
Create a Supabase project.

## Step 2 - Create the database tables
Open Supabase **SQL Editor**, copy everything from `supabase_schema.sql`, and run it once.

## Step 3 - Get the two Supabase values
In Supabase, get:

- Project URL
- **Secret key** (`sb_secret_...`)

The Secret Key is server-side only. Never put it in public GitHub code.

## Step 4 - Upload this project to GitHub
Upload:

- `app.py`
- `requirements.txt`
- `supabase_schema.sql`
- `.gitignore`
- `.streamlit/secrets.toml.example` (optional)

Do **not** upload a real `.streamlit/secrets.toml` containing your key.

## Step 5 - Deploy on Streamlit Community Cloud
Create an app and set the main file to:

`app.py`

Then open **App settings > Secrets** and enter:

```toml
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_YOUR_SECRET_KEY"
```

Save and restart the app.

The left sidebar should show:

`Cloud DB connected`

---

# First Employee Import

Go to **Employee Master** and upload the employee workbook.

For the current sample workbook, select sheet:

`0`

The importer looks for these required columns:

- 用户编码
- 姓名
- 考勤组

It also stores useful fields when present, including ERP, 在职状态, 账号状态, 部门, 岗位, 用工性质, 供应商, 入职日期, 离职日期, plus the original row as JSON.

Columns containing `成绩` or `Score` are intentionally ignored in V1.

Click **Save to Database** after previewing the import.

---

# Update Rule

`用户编码 / User ID` is the unique key.

- Same User ID -> overwrite/update that employee's master data.
- New User ID -> add a new employee.
- Old employee absent from a new upload -> keep the old employee in the database.
- Feedback / Recognition / Warning history -> always remains linked to the User ID.

---

# Local Test

Install packages:

```bash
pip install -r requirements.txt
```

Run:

```bash
streamlit run app.py
```

Without Supabase settings the app automatically uses SQLite local mode.
