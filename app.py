from __future__ import annotations

import io
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    from supabase import Client, create_client
except Exception:
    Client = Any  # type: ignore
    create_client = None


APP_TITLE = "Employee Feedback & Recognition"
LOCAL_DB_PATH = Path(__file__).with_name("employee_feedback.db")

EMPLOYEE_COLUMNS = [
    "employee_id",
    "erp",
    "name",
    "attendance_group",
    "employment_status",
    "account_status",
    "department",
    "job",
    "employment_type",
    "vendor",
    "hire_date",
    "termination_date",
    "raw_data",
    "updated_at",
]

FEEDBACK_TYPES = [
    "Feedback",
    "Verbal Warning",
    "Written Warning",
    "Final Warning",
]


# -----------------------------
# Helpers
# -----------------------------
def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None

    # Excel sometimes turns an ID-like integer into a floating number.
    if text.endswith(".0"):
        try:
            number = float(text)
            if number.is_integer():
                return str(int(number))
        except Exception:
            pass
    return text


def to_date_string(value: Any) -> Optional[str]:
    text = clean_value(value)
    if not text:
        return None
    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return text
        return parsed.date().isoformat()
    except Exception:
        return text


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def safe_raw_data(record: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): json_safe(v) for k, v in record.items()}


def chunks(items: List[Dict[str, Any]], size: int = 200) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def format_date(value: Any) -> str:
    if value in (None, "", pd.NaT):
        return "—"
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return str(value)
        return parsed.strftime("%b %d, %Y")
    except Exception:
        return str(value)


def escape_html(text: Any) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# -----------------------------
# Data import mapping
# -----------------------------
ALIASES = {
    "employee_id": ["用户编码", "Employee ID", "User ID", "US号", "US ID"],
    "erp": ["ERP", "erp"],
    "name": ["姓名", "姓名 Name", "Name", "Employee Name"],
    "attendance_group": ["考勤组", "Attendance Group"],
    "employment_status": ["在职状态", "Employment Status"],
    "account_status": ["账号状态", "Account Status"],
    "department": ["部门", "Department"],
    "job": ["岗位", "Job", "Position"],
    "employment_type": ["用工性质", "Employment Type"],
    "vendor": ["供应商", "Vendor", "Agency"],
    "hire_date": ["入职日期", "Hire Date"],
    "termination_date": ["离职日期", "Termination Date"],
}


def find_column(columns: Iterable[Any], aliases: List[str]) -> Optional[str]:
    normalized = {str(c).strip(): str(c) for c in columns if c is not None}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    # case-insensitive fallback
    lower = {k.lower(): v for k, v in normalized.items()}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    return None


def dataframe_to_employee_rows(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[str]]:
    # Explicitly ignore score/performance columns in V1.
    score_like = [c for c in df.columns if "成绩" in str(c) or "score" in str(c).lower()]
    df = df.drop(columns=score_like, errors="ignore")

    mapping: Dict[str, Optional[str]] = {
        field: find_column(df.columns, aliases) for field, aliases in ALIASES.items()
    }

    missing = []
    if not mapping["employee_id"]:
        missing.append("用户编码")
    if not mapping["name"]:
        missing.append("姓名")
    if not mapping["attendance_group"]:
        missing.append("考勤组")
    if missing:
        return [], missing

    rows: List[Dict[str, Any]] = []
    for _, series in df.iterrows():
        employee_id = clean_value(series.get(mapping["employee_id"]))
        if not employee_id:
            continue
        raw = safe_raw_data(series.to_dict())
        row = {
            "employee_id": employee_id,
            "erp": clean_value(series.get(mapping["erp"])) if mapping["erp"] else None,
            "name": clean_value(series.get(mapping["name"])) or employee_id,
            "attendance_group": clean_value(series.get(mapping["attendance_group"])) or "未分组",
            "employment_status": clean_value(series.get(mapping["employment_status"])) if mapping["employment_status"] else None,
            "account_status": clean_value(series.get(mapping["account_status"])) if mapping["account_status"] else None,
            "department": clean_value(series.get(mapping["department"])) if mapping["department"] else None,
            "job": clean_value(series.get(mapping["job"])) if mapping["job"] else None,
            "employment_type": clean_value(series.get(mapping["employment_type"])) if mapping["employment_type"] else None,
            "vendor": clean_value(series.get(mapping["vendor"])) if mapping["vendor"] else None,
            "hire_date": to_date_string(series.get(mapping["hire_date"])) if mapping["hire_date"] else None,
            "termination_date": to_date_string(series.get(mapping["termination_date"])) if mapping["termination_date"] else None,
            "raw_data": raw,
            "updated_at": now_iso(),
        }
        rows.append(row)

    # If the same employee appears more than once in one import, keep the last row.
    deduped = {row["employee_id"]: row for row in rows}
    return list(deduped.values()), []


# -----------------------------
# Database backends
# -----------------------------
@dataclass
class DBStatus:
    mode: str
    detail: str


class Database:
    def __init__(self) -> None:
        self.mode = "sqlite"
        self.supabase: Optional[Client] = None
        self.sqlite_path = LOCAL_DB_PATH

        url = None
        key = None
        try:
            url = st.secrets.get("SUPABASE_URL")
            key = st.secrets.get("SUPABASE_SECRET_KEY") or st.secrets.get("SUPABASE_KEY")
        except Exception:
            pass
        url = url or os.getenv("SUPABASE_URL")
        key = key or os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY")

        if url and key and create_client is not None:
            try:
                self.supabase = create_client(url, key)
                # Small connection test. Tables must already exist.
                self.supabase.table("employees").select("employee_id").limit(1).execute()
                self.mode = "supabase"
            except Exception as exc:
                self.supabase = None
                st.session_state["db_connection_warning"] = str(exc)

        if self.mode == "sqlite":
            self._init_sqlite()

    def status(self) -> DBStatus:
        if self.mode == "supabase":
            return DBStatus("supabase", "Supabase 云端数据库（永久保存）")
        return DBStatus("sqlite", f"SQLite 本地数据库：{self.sqlite_path.name}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    erp TEXT,
                    name TEXT NOT NULL,
                    attendance_group TEXT,
                    employment_status TEXT,
                    account_status TEXT,
                    department TEXT,
                    job TEXT,
                    employment_type TEXT,
                    vendor TEXT,
                    hire_date TEXT,
                    termination_date TEXT,
                    raw_data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_records (
                    id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    record_date TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    note TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recognition_records (
                    id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    record_date TEXT NOT NULL,
                    content TEXT NOT NULL,
                    note TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_employee ON feedback_records(employee_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recognition_employee ON recognition_records(employee_id)")
            conn.commit()

    def list_employees(self) -> List[Dict[str, Any]]:
        if self.mode == "supabase":
            assert self.supabase is not None
            data = self.supabase.table("employees").select("*").limit(10000).execute().data or []
            return data
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM employees").fetchall()
            output = []
            for row in rows:
                item = dict(row)
                try:
                    item["raw_data"] = json.loads(item.get("raw_data") or "{}")
                except Exception:
                    item["raw_data"] = {}
                output.append(item)
            return output

    def get_employee(self, employee_id: str) -> Optional[Dict[str, Any]]:
        if self.mode == "supabase":
            assert self.supabase is not None
            data = (
                self.supabase.table("employees")
                .select("*")
                .eq("employee_id", employee_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return data[0] if data else None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["raw_data"] = json.loads(item.get("raw_data") or "{}")
            except Exception:
                item["raw_data"] = {}
            return item

    def upsert_employees(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        if self.mode == "supabase":
            assert self.supabase is not None
            for batch in chunks(rows):
                self.supabase.table("employees").upsert(batch, on_conflict="employee_id").execute()
            return

        sql = """
        INSERT INTO employees (
            employee_id, erp, name, attendance_group, employment_status,
            account_status, department, job, employment_type, vendor,
            hire_date, termination_date, raw_data, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(employee_id) DO UPDATE SET
            erp=excluded.erp,
            name=excluded.name,
            attendance_group=excluded.attendance_group,
            employment_status=excluded.employment_status,
            account_status=excluded.account_status,
            department=excluded.department,
            job=excluded.job,
            employment_type=excluded.employment_type,
            vendor=excluded.vendor,
            hire_date=excluded.hire_date,
            termination_date=excluded.termination_date,
            raw_data=excluded.raw_data,
            updated_at=excluded.updated_at
        """
        values = [
            (
                r.get("employee_id"),
                r.get("erp"),
                r.get("name"),
                r.get("attendance_group"),
                r.get("employment_status"),
                r.get("account_status"),
                r.get("department"),
                r.get("job"),
                r.get("employment_type"),
                r.get("vendor"),
                r.get("hire_date"),
                r.get("termination_date"),
                json.dumps(r.get("raw_data") or {}, ensure_ascii=False),
                r.get("updated_at") or now_iso(),
            )
            for r in rows
        ]
        with self._connect() as conn:
            conn.executemany(sql, values)
            conn.commit()

    def list_feedback(self, employee_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.mode == "supabase":
            assert self.supabase is not None
            query = self.supabase.table("feedback_records").select("*")
            if employee_id:
                query = query.eq("employee_id", employee_id)
            return query.order("record_date", desc=True).order("created_at", desc=True).limit(10000).execute().data or []
        with self._connect() as conn:
            if employee_id:
                rows = conn.execute(
                    "SELECT * FROM feedback_records WHERE employee_id=? ORDER BY record_date DESC, created_at DESC",
                    (employee_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feedback_records ORDER BY record_date DESC, created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def list_recognition(self, employee_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.mode == "supabase":
            assert self.supabase is not None
            query = self.supabase.table("recognition_records").select("*")
            if employee_id:
                query = query.eq("employee_id", employee_id)
            return query.order("record_date", desc=True).order("created_at", desc=True).limit(10000).execute().data or []
        with self._connect() as conn:
            if employee_id:
                rows = conn.execute(
                    "SELECT * FROM recognition_records WHERE employee_id=? ORDER BY record_date DESC, created_at DESC",
                    (employee_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM recognition_records ORDER BY record_date DESC, created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def add_feedback(
        self,
        employee_id: str,
        record_date: str,
        feedback_type: str,
        content: str,
        note: Optional[str],
        created_by: Optional[str],
    ) -> None:
        row = {
            "id": str(uuid.uuid4()),
            "employee_id": employee_id,
            "record_date": record_date,
            "feedback_type": feedback_type,
            "content": content,
            "note": note,
            "created_by": created_by,
            "created_at": now_iso(),
        }
        if self.mode == "supabase":
            assert self.supabase is not None
            self.supabase.table("feedback_records").insert(row).execute()
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_records
                (id, employee_id, record_date, feedback_type, content, note, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row[k] for k in ["id", "employee_id", "record_date", "feedback_type", "content", "note", "created_by", "created_at"]),
            )
            conn.commit()

    def add_recognition(
        self,
        employee_id: str,
        record_date: str,
        content: str,
        note: Optional[str],
        created_by: Optional[str],
    ) -> None:
        row = {
            "id": str(uuid.uuid4()),
            "employee_id": employee_id,
            "record_date": record_date,
            "content": content,
            "note": note,
            "created_by": created_by,
            "created_at": now_iso(),
        }
        if self.mode == "supabase":
            assert self.supabase is not None
            self.supabase.table("recognition_records").insert(row).execute()
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recognition_records
                (id, employee_id, record_date, content, note, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row[k] for k in ["id", "employee_id", "record_date", "content", "note", "created_by", "created_at"]),
            )
            conn.commit()


@st.cache_resource
def get_db() -> Database:
    return Database()


# -----------------------------
# Export
# -----------------------------
def build_backup_xlsx(db: Database) -> bytes:
    employees = pd.DataFrame(db.list_employees())
    feedback = pd.DataFrame(db.list_feedback())
    recognition = pd.DataFrame(db.list_recognition())

    if not employees.empty and "raw_data" in employees.columns:
        employees["raw_data"] = employees["raw_data"].apply(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else x
        )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        employees.to_excel(writer, sheet_name="Employee Master", index=False)
        feedback.to_excel(writer, sheet_name="Feedback", index=False)
        recognition.to_excel(writer, sheet_name="Recognition", index=False)
    return output.getvalue()


# -----------------------------
# UI helpers
# -----------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
            .block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1450px;}
            .small-muted {color: #6b7280; font-size: .9rem;}
            .profile-title {margin-bottom: 0.2rem;}
            .record-meta {color: #6b7280; font-size: .83rem; margin-bottom: .35rem;}
            div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.22); padding: 12px 14px; border-radius: 12px;}
            div[data-testid="stExpander"] {border-radius: 12px;}
            .employee-cell {padding: .30rem .15rem; white-space: normal; overflow-wrap: anywhere;}
            .employee-number {padding: .30rem .15rem; text-align: right; font-variant-numeric: tabular-nums;}
            .employee-row-divider {height: 1px; background: rgba(128,128,128,.28); margin: .18rem 0 .28rem 0;}
            .employee-row-divider.subtle {background: rgba(128,128,128,.16); margin: .12rem 0 .16rem 0;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def dataframe_from(rows: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns or [])
    return pd.DataFrame(rows)


def employee_summary(db: Database) -> pd.DataFrame:
    emp = dataframe_from(db.list_employees(), EMPLOYEE_COLUMNS)
    if emp.empty:
        return emp

    fb = dataframe_from(db.list_feedback(), ["employee_id", "feedback_type"])
    rec = dataframe_from(db.list_recognition(), ["employee_id"])

    if fb.empty:
        fb_counts = pd.DataFrame(columns=["employee_id", "feedback_count", "warning_count"])
    else:
        fb_counts = fb.groupby("employee_id").size().rename("feedback_count").reset_index()
        warning = (
            fb.assign(is_warning=fb["feedback_type"].astype(str).str.contains("Warning", case=False, na=False))
            .groupby("employee_id")["is_warning"]
            .sum()
            .rename("warning_count")
            .reset_index()
        )
        fb_counts = fb_counts.merge(warning, on="employee_id", how="left")

    if rec.empty:
        rec_counts = pd.DataFrame(columns=["employee_id", "recognition_count"])
    else:
        rec_counts = rec.groupby("employee_id").size().rename("recognition_count").reset_index()

    out = emp.merge(fb_counts, on="employee_id", how="left").merge(rec_counts, on="employee_id", how="left")
    for c in ["feedback_count", "warning_count", "recognition_count"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    out["attendance_group"] = out["attendance_group"].fillna("未分组").replace("", "未分组")
    return out


def open_profile(employee_id: str) -> None:
    st.session_state["selected_employee_id"] = employee_id
    st.session_state["page"] = "Employees"


def render_employee_table(group_df: pd.DataFrame, key_suffix: str) -> None:
    """Render a fixed-width employee list without horizontal scrolling."""
    if group_df.empty:
        return

    # Streamlit's dataframe can introduce a horizontal scrollbar when column
    # minimum widths exceed the viewport. A row-based layout keeps all four
    # columns inside the current screen width while preserving clickable names.
    with st.container(border=True):
        header = st.columns([4.2, 2.2, 1.2, 1.4], gap="small", vertical_alignment="center")
        header[0].markdown("**Employee**")
        header[1].markdown("**User ID**")
        header[2].markdown("**Feedback**")
        header[3].markdown("**Recognition**")
        st.markdown("<div class='employee-row-divider'></div>", unsafe_allow_html=True)

        for row_idx, row in group_df.reset_index(drop=True).iterrows():
            employee_id = str(row.get("employee_id") or "")
            employee_name = clean_value(row.get("name")) or employee_id
            feedback_count = int(row.get("feedback_count") or 0)
            recognition_count = int(row.get("recognition_count") or 0)

            cols = st.columns([4.2, 2.2, 1.2, 1.4], gap="small", vertical_alignment="center")
            if cols[0].button(
                employee_name,
                key=f"employee_btn_{key_suffix}_{row_idx}",
                type="tertiary",
                use_container_width=True,
                help="点击员工姓名进入个人记录",
            ):
                open_profile(employee_id)
                st.rerun()

            cols[1].markdown(f"<div class='employee-cell'>{escape_html(employee_id)}</div>", unsafe_allow_html=True)
            cols[2].markdown(f"<div class='employee-number'>{feedback_count}</div>", unsafe_allow_html=True)
            cols[3].markdown(f"<div class='employee-number'>{recognition_count}</div>", unsafe_allow_html=True)

            if row_idx < len(group_df) - 1:
                st.markdown("<div class='employee-row-divider subtle'></div>", unsafe_allow_html=True)


def render_record_card(record: Dict[str, Any], kind: str) -> None:
    with st.container(border=True):
        if kind == "feedback":
            title = escape_html(record.get("feedback_type") or "Feedback")
        else:
            title = "Recognition"
        meta = format_date(record.get("record_date"))
        by = clean_value(record.get("created_by"))
        if by:
            meta += f" · Recorded by {escape_html(by)}"
        st.markdown(f"**{title}**")
        st.markdown(f"<div class='record-meta'>{meta}</div>", unsafe_allow_html=True)
        st.write(record.get("content") or "")
        if clean_value(record.get("note")):
            st.caption(f"Note: {record.get('note')}")


# -----------------------------
# Pages
# -----------------------------
def render_home(db: Database) -> None:
    st.title("Employee Feedback & Recognition")
    st.caption("按考勤组查看员工，点击员工姓名进入个人 Recognition / Feedback / Warning 记录。")

    summary = employee_summary(db)
    if summary.empty:
        st.info("还没有员工数据。请先到左侧 **Employee Master** 上传员工底表。")
        return

    search_col, status_col = st.columns([3, 1])
    with search_col:
        search = st.text_input(
            "Search",
            placeholder="模糊搜索姓名 / 用户编码 / ERP",
            label_visibility="collapsed",
        ).strip()
    with status_col:
        status_filter = st.selectbox("员工状态", ["在职", "全部", "离职"], label_visibility="collapsed")

    filtered = summary.copy()
    if status_filter != "全部":
        filtered = filtered[filtered["employment_status"].fillna("").astype(str) == status_filter]

    if search:
        q = search.lower()
        mask = pd.Series(False, index=filtered.index)
        for col in ["name", "employee_id", "erp"]:
            if col in filtered.columns:
                mask = mask | filtered[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        filtered = filtered[mask]

    total_col, fb_col, rec_col = st.columns(3)
    total_col.metric("Employees", len(filtered))
    fb_col.metric("Feedback", int(filtered["feedback_count"].sum()) if not filtered.empty else 0)
    rec_col.metric("Recognition", int(filtered["recognition_count"].sum()) if not filtered.empty else 0)

    if filtered.empty:
        st.warning("没有找到符合条件的员工。")
        return

    filtered = filtered.sort_values(
        ["attendance_group", "feedback_count", "recognition_count", "name"],
        ascending=[True, False, False, True],
        na_position="last",
    )

    if search:
        st.subheader(f"Search Results · {len(filtered)}")
        render_employee_table(filtered.reset_index(drop=True), "search")
        return

    groups = sorted(filtered["attendance_group"].dropna().astype(str).unique().tolist())
    for idx, group in enumerate(groups):
        group_df = filtered[filtered["attendance_group"].astype(str) == group].copy()
        group_df = group_df.sort_values(
            ["feedback_count", "recognition_count", "name"],
            ascending=[False, False, True],
            na_position="last",
        ).reset_index(drop=True)
        with st.expander(f"{group}  ·  {len(group_df)} employees", expanded=(idx < 2)):
            render_employee_table(group_df, f"group_{idx}")


def render_profile(db: Database, employee_id: str) -> None:
    employee = db.get_employee(employee_id)
    if not employee:
        st.error("找不到该员工。")
        st.session_state.pop("selected_employee_id", None)
        return

    if st.button("← Back to Employees", type="tertiary"):
        st.session_state.pop("selected_employee_id", None)
        st.rerun()

    st.markdown(f"## {employee.get('name') or employee_id}")
    st.caption(
        f"{employee_id}  ·  {employee.get('attendance_group') or '未分组'}"
        + (f"  ·  {employee.get('employment_status')}" if employee.get("employment_status") else "")
    )

    feedback = db.list_feedback(employee_id)
    recognition = db.list_recognition(employee_id)
    warning_count = sum("warning" in str(r.get("feedback_type", "")).lower() for r in feedback)

    m1, m2, m3 = st.columns(3)
    m1.metric("Feedback", len(feedback))
    m2.metric("Recognition", len(recognition))
    m3.metric("Warnings", warning_count)

    with st.expander("Employee Information"):
        info = {
            "User ID": employee.get("employee_id"),
            "ERP": employee.get("erp"),
            "Attendance Group": employee.get("attendance_group"),
            "Status": employee.get("employment_status"),
            "Account": employee.get("account_status"),
            "Department": employee.get("department"),
            "Job": employee.get("job"),
            "Employment Type": employee.get("employment_type"),
            "Vendor": employee.get("vendor"),
            "Hire Date": employee.get("hire_date"),
            "Termination Date": employee.get("termination_date"),
        }
        info_df = pd.DataFrame([(k, v or "—") for k, v in info.items()], columns=["Field", "Value"])
        st.dataframe(info_df, use_container_width=True, hide_index=True)

    st.divider()

    # Feedback / Warning first, full width.
    feedback_form_key = f"show_feedback_form_{employee_id}"
    if feedback_form_key not in st.session_state:
        st.session_state[feedback_form_key] = False

    head, add = st.columns([10, 1], gap="small", vertical_alignment="center")
    head.subheader("⚠️ Feedback / Warning")
    with add:
        button_label = "×" if st.session_state[feedback_form_key] else "＋"
        if st.button(button_label, key=f"toggle_feedback_{employee_id}", use_container_width=True):
            st.session_state[feedback_form_key] = not st.session_state[feedback_form_key]
            st.rerun()

    if st.session_state[feedback_form_key]:
        with st.container(border=True):
            st.markdown("#### Add Feedback / Warning")
            with st.form(f"add_feedback_{employee_id}", clear_on_submit=True):
                top1, top2, top3 = st.columns([1.2, 1.6, 1.4], gap="medium")
                with top1:
                    fb_date = st.date_input("Date", value=date.today())
                with top2:
                    fb_type = st.selectbox("Type", FEEDBACK_TYPES)
                with top3:
                    fb_by = st.text_input("Recorded by (optional)")

                fb_content = st.text_area(
                    "Feedback / Warning",
                    placeholder="写下记录内容…",
                    height=180,
                )
                fb_note = st.text_input("Note / Follow-up (optional)")

                save_col, cancel_col, spacer = st.columns([1.4, 1, 5], gap="small")
                with save_col:
                    submitted = st.form_submit_button(
                        "Save Feedback", type="primary", use_container_width=True
                    )
                with cancel_col:
                    cancel_feedback = st.form_submit_button("Cancel", use_container_width=True)

                if cancel_feedback:
                    st.session_state[feedback_form_key] = False
                    st.rerun()

                if submitted:
                    if not fb_content.strip():
                        st.error("Feedback 内容不能为空。")
                    else:
                        db.add_feedback(
                            employee_id,
                            fb_date.isoformat(),
                            fb_type,
                            fb_content.strip(),
                            fb_note.strip() or None,
                            fb_by.strip() or None,
                        )
                        st.session_state[feedback_form_key] = False
                        st.success("Feedback 已保存。")
                        st.rerun()

    if not feedback:
        st.caption("No feedback records yet.")
    for rec in feedback:
        render_record_card(rec, "feedback")

    st.divider()

    # Recognition below Feedback / Warning, also full width.
    recognition_form_key = f"show_recognition_form_{employee_id}"
    if recognition_form_key not in st.session_state:
        st.session_state[recognition_form_key] = False

    head, add = st.columns([10, 1], gap="small", vertical_alignment="center")
    head.subheader("🏆 Recognition")
    with add:
        button_label = "×" if st.session_state[recognition_form_key] else "＋"
        if st.button(button_label, key=f"toggle_recognition_{employee_id}", use_container_width=True):
            st.session_state[recognition_form_key] = not st.session_state[recognition_form_key]
            st.rerun()

    if st.session_state[recognition_form_key]:
        with st.container(border=True):
            st.markdown("#### Add Recognition")
            with st.form(f"add_recognition_{employee_id}", clear_on_submit=True):
                top1, top2 = st.columns([1.2, 2.8], gap="medium")
                with top1:
                    rec_date = st.date_input("Date", value=date.today())
                with top2:
                    rec_by = st.text_input("Recorded by (optional)")

                rec_content = st.text_area(
                    "Recognition",
                    placeholder="写下表扬内容…",
                    height=180,
                )
                rec_note = st.text_input("Note (optional)")

                save_col, cancel_col, spacer = st.columns([1.4, 1, 5], gap="small")
                with save_col:
                    submitted = st.form_submit_button(
                        "Save Recognition", type="primary", use_container_width=True
                    )
                with cancel_col:
                    cancel_recognition = st.form_submit_button("Cancel", use_container_width=True)

                if cancel_recognition:
                    st.session_state[recognition_form_key] = False
                    st.rerun()

                if submitted:
                    if not rec_content.strip():
                        st.error("Recognition 内容不能为空。")
                    else:
                        db.add_recognition(
                            employee_id,
                            rec_date.isoformat(),
                            rec_content.strip(),
                            rec_note.strip() or None,
                            rec_by.strip() or None,
                        )
                        st.session_state[recognition_form_key] = False
                        st.success("Recognition 已保存。")
                        st.rerun()

    if not recognition:
        st.caption("No recognition records yet.")
    for rec in recognition:
        render_record_card(rec, "recognition")


def render_master(db: Database) -> None:
    st.title("Employee Master")
    st.caption("上传员工底表后按“用户编码”更新/新增。未出现在新文件里的旧员工不会被删除。成绩/Score 字段会自动忽略。")

    current = dataframe_from(db.list_employees(), EMPLOYEE_COLUMNS)
    c1, c2 = st.columns(2)
    c1.metric("Saved Employees", len(current))
    if not current.empty and "employment_status" in current.columns:
        c2.metric("Active", int((current["employment_status"].fillna("").astype(str) == "在职").sum()))
    else:
        c2.metric("Active", 0)

    st.subheader("Upload / Update Employee Master")
    uploaded = st.file_uploader("Excel or CSV", type=["xlsx", "xls", "csv"])
    if uploaded is not None:
        raw_bytes = uploaded.getvalue()
        filename = uploaded.name.lower()
        try:
            if filename.endswith(".csv"):
                preview_df = pd.read_csv(io.BytesIO(raw_bytes), dtype=object)
                chosen_sheet = None
            else:
                excel = pd.ExcelFile(io.BytesIO(raw_bytes))
                # Your current master uses sheet "0", so prefer it when available.
                default_index = excel.sheet_names.index("0") if "0" in excel.sheet_names else 0
                chosen_sheet = st.selectbox("Sheet", excel.sheet_names, index=default_index)
                preview_df = pd.read_excel(io.BytesIO(raw_bytes), sheet_name=chosen_sheet, dtype=object)
        except Exception as exc:
            st.error(f"文件读取失败：{exc}")
            return

        rows, missing = dataframe_to_employee_rows(preview_df)
        if missing:
            st.error("缺少必要字段：" + "、".join(missing))
        else:
            existing = {r["employee_id"]: r for r in db.list_employees()}
            new_count = sum(r["employee_id"] not in existing for r in rows)
            update_count = len(rows) - new_count

            st.success(f"识别到 {len(rows)} 名员工：新增 {new_count}，更新/覆盖 {update_count}。")
            preview = pd.DataFrame(rows)[["employee_id", "erp", "name", "attendance_group", "employment_status"]].head(30)
            st.dataframe(preview, use_container_width=True, hide_index=True)
            if st.button("Save to Database", type="primary", use_container_width=True):
                db.upsert_employees(rows)
                st.success(f"已保存 {len(rows)} 名员工。历史 Feedback / Recognition 不受影响。")
                st.rerun()

    st.divider()
    st.subheader("Add One Employee")
    with st.form("single_employee_form", clear_on_submit=True):
        a, b, c = st.columns(3)
        employee_id = a.text_input("用户编码 / User ID *")
        name = b.text_input("姓名 / Name *")
        attendance_group = c.text_input("考勤组 / Attendance Group *")

        d, e, f = st.columns(3)
        erp = d.text_input("ERP")
        employment_status = e.selectbox("在职状态", ["在职", "离职", ""])
        account_status = f.selectbox("账号状态", ["启用", "禁用", ""])

        g, h, i = st.columns(3)
        department = g.text_input("部门")
        job = h.text_input("岗位")
        vendor = i.text_input("供应商")

        submitted = st.form_submit_button("Save Employee", type="primary")
        if submitted:
            if not employee_id.strip() or not name.strip() or not attendance_group.strip():
                st.error("用户编码、姓名、考勤组为必填。")
            else:
                raw = {
                    "用户编码": employee_id.strip(),
                    "ERP": erp.strip() or None,
                    "姓名": name.strip(),
                    "考勤组": attendance_group.strip(),
                    "在职状态": employment_status or None,
                    "账号状态": account_status or None,
                    "部门": department.strip() or None,
                    "岗位": job.strip() or None,
                    "供应商": vendor.strip() or None,
                }
                db.upsert_employees(
                    [
                        {
                            "employee_id": employee_id.strip(),
                            "erp": erp.strip() or None,
                            "name": name.strip(),
                            "attendance_group": attendance_group.strip(),
                            "employment_status": employment_status or None,
                            "account_status": account_status or None,
                            "department": department.strip() or None,
                            "job": job.strip() or None,
                            "employment_type": None,
                            "vendor": vendor.strip() or None,
                            "hire_date": None,
                            "termination_date": None,
                            "raw_data": raw,
                            "updated_at": now_iso(),
                        }
                    ]
                )
                st.success("员工已保存。")
                st.rerun()

    st.divider()
    st.subheader("Saved Employee Master")
    if current.empty:
        st.caption("No employee data yet.")
    else:
        show_cols = ["employee_id", "erp", "name", "attendance_group", "employment_status", "vendor", "updated_at"]
        st.dataframe(
            current[show_cols].sort_values(["attendance_group", "name"], na_position="last"),
            use_container_width=True,
            hide_index=True,
        )


def render_backup(db: Database) -> None:
    st.title("Backup & Export")
    st.caption("随时导出完整员工主档、Feedback/Warning、Recognition，作为独立备份。")

    employees = db.list_employees()
    feedback = db.list_feedback()
    recognition = db.list_recognition()

    c1, c2, c3 = st.columns(3)
    c1.metric("Employees", len(employees))
    c2.metric("Feedback / Warning", len(feedback))
    c3.metric("Recognition", len(recognition))

    backup = build_backup_xlsx(db)
    st.download_button(
        "Download Full Backup (.xlsx)",
        data=backup,
        file_name=f"employee_feedback_backup_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )

    status = db.status()
    if status.mode == "supabase":
        st.success("当前使用 Supabase 云端数据库。Streamlit 重新部署不会删除数据库中的记录。")
    else:
        st.warning(
            "当前是 SQLite 本地模式，适合本机测试。若部署到 Streamlit Community Cloud 并要求长期永久保存，"
            "请按照 README 配置 Supabase。"
        )


# -----------------------------
# App entry
# -----------------------------
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
    inject_css()
    db = get_db()

    if "page" not in st.session_state:
        st.session_state["page"] = "Employees"

    with st.sidebar:
        st.markdown("### 🗂️ Employee Records")
        nav = st.radio(
            "Navigation",
            ["Employees", "Employee Master", "Backup"],
            index=["Employees", "Employee Master", "Backup"].index(st.session_state["page"]),
            label_visibility="collapsed",
        )
        st.session_state["page"] = nav
        st.divider()
        status = db.status()
        if status.mode == "supabase":
            st.success("● Cloud DB connected")
            st.caption("Supabase · permanent storage")
        else:
            st.info("● Local DB")
            st.caption("SQLite · local testing")
            if st.session_state.get("db_connection_warning"):
                with st.expander("Supabase connection detail"):
                    st.code(st.session_state["db_connection_warning"])

    if nav == "Employees":
        selected = st.session_state.get("selected_employee_id")
        if selected:
            render_profile(db, selected)
        else:
            render_home(db)
    elif nav == "Employee Master":
        st.session_state.pop("selected_employee_id", None)
        render_master(db)
    else:
        st.session_state.pop("selected_employee_id", None)
        render_backup(db)


if __name__ == "__main__":
    main()
