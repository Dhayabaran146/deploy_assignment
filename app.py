import os
import re
from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import streamlit as st

# -------------------------------------------------------
# MAIN APP CONFIG
# -------------------------------------------------------
st.set_page_config(
    page_title="Assignment",
    page_icon="🚀",
    layout="wide"
)

# -------------------------------------------------------
# LOAD DATA
# -------------------------------------------------------
FILE_NAME = "dirty_employee_dataset_150_rows.xlsx"

try:
    df = pd.read_excel(FILE_NAME)
except Exception as e:
    st.error(f"Failed to load '{FILE_NAME}'. Error: {e}")
    st.stop()

# -------------------------------------------------------
# EMAIL FUNCTIONS
# -------------------------------------------------------
EMAIL_REGEX = re.compile(
    r"^(?=.{1,254}$)(?=.{1,64}@)"
    r"[A-Z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"(?:[A-Z0-9-]{1,63}\.)+[A-Z]{2,}$",
    re.IGNORECASE
)

def is_valid_email(x) -> bool:
    if pd.isna(x):
        return False
    return bool(EMAIL_REGEX.match(str(x).strip()))

def digits_only(x) -> str:
    if pd.isna(x):
        return ""
    return re.sub(r"\D", "", str(x))

def is_valid_phone_10(x) -> bool:
    d = digits_only(x)
    return len(d) == 10

# -------------------------------------------------------
# DATE FIX HELPERS
# -------------------------------------------------------
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _strip_ordinals(s: str) -> str:
    return re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)

def _normalize_separators(s: str) -> str:
    s = s.replace(",", " ").strip()
    s = re.sub(r"[./]", "-", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return s

def _excel_serial_to_ts(val):
    try:
        f = float(val)
        ts = pd.Timestamp("1899-12-30") + pd.to_timedelta(int(f), unit="D")
        if 1800 <= ts.year <= 2100:
            return ts
    except Exception:
        pass
    return None

def _try_parse_dt(s: str):
    if s is None:
        return None

    if isinstance(s, (pd.Timestamp, np.datetime64)):
        try:
            ts = pd.to_datetime(s, errors="coerce")
            return ts if pd.notna(ts) else None
        except Exception:
            return None

    if isinstance(s, (int, float)) and not pd.isna(s):
        ts = _excel_serial_to_ts(s)
        if ts is not None:
            return ts

    s0 = str(s).strip()
    if s0 == "":
        return None

    if re.fullmatch(r"^\d+(\.\d+)?$", s0):
        ts = _excel_serial_to_ts(s0)
        if ts is not None:
            return ts

    s1 = _strip_ordinals(s0)
    s1 = _normalize_separators(s1)

    for dayfirst in (False, True):
        try:
            ts = pd.to_datetime(s1, errors="coerce", dayfirst=dayfirst)
            if pd.notna(ts):
                return ts
        except Exception:
            pass

    candidates = [
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%B-%Y",
        "%b-%d-%Y", "%B-%d-%Y", "%d %b %Y", "%d %B %Y",
        "%b %d %Y", "%B %d %Y", "%d-%m-%y", "%m-%d-%y",
        "%d/%m/%y", "%m/%d/%y"
    ]

    for fmt in candidates:
        try:
            return pd.to_datetime(s1, format=fmt, errors="raise")
        except Exception:
            continue

    return None

def fix_date_format_force_series(series: pd.Series) -> pd.Series:
    def _fix(x):
        if pd.isna(x):
            return x
        ts = _try_parse_dt(x)
        return ts.strftime("%Y-%m-%d") if ts is not None else str(x).strip()

    return series.map(_fix).astype("object")

# -------------------------------------------------------
# GENDER / COUNTRY / SALARY
# -------------------------------------------------------
def normalize_gender(series: pd.Series) -> pd.Series:
    def _map(g):
        if pd.isna(g):
            return pd.NA
        s = str(g).strip().lower()
        if s in {"m", "male"}:
            return "Male"
        if s in {"f", "female"}:
            return "Female"
        if s in {"other", "others"}:
            return "Other"
        if s in {"prefer not to say", "pefer not to say"}:
            return "Prefer Not To Say"
        return str(g).strip().title()
    return series.map(_map)

def normalize_country(series: pd.Series) -> pd.Series:
    def _map(c):
        if pd.isna(c):
            return pd.NA
        s = str(c).strip().lower().replace(".", "")
        if s in {"us", "usa", "united states", "unitedstates"}:
            return "USA"
        if s in {"uk", "united kingdom", "unitedkingdom", "united kindgom"}:
            return "UK"
        if s in {"uae", "united arab emirates"}:
            return "UAE"
        if s in {"in", "india", "bharat"}:
            return "India"
        if s in {"eu", "european union"}:
            return "EU"
        cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-z\s-]", "", s)).strip()
        if not cleaned:
            return pd.NA
        return cleaned.title()
    return series.map(_map)

def clean_salary_series(series: pd.Series) -> pd.Series:
    s = series.astype("string")
    cleaned = s.str.replace(r"[^\d\.\-]", "", regex=True).str.strip()
    numeric = pd.to_numeric(cleaned, errors="coerce")
    return numeric

def to_excel_bytes(df_in: pd.DataFrame) -> BytesIO:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_in.to_excel(writer, index=False, sheet_name="cleaned")
    buffer.seek(0)
    return buffer

# -------------------------------------------------------
# CHATBOT HELPERS
# -------------------------------------------------------
def dataframe_schema_text(df_in: pd.DataFrame) -> str:
    lines = []
    for col in df_in.columns:
        lines.append(f"- {col} ({df_in[col].dtype})")
    return "\n".join(lines)

def safe_string(x):
    if pd.isna(x):
        return ""
    return str(x).strip()

def retrieve_relevant_rows(df_in: pd.DataFrame, question: str, top_k: int = 12) -> pd.DataFrame:
    q_words = set(re.findall(r"\w+", question.lower()))
    if not q_words:
        return df_in.head(top_k)

    score_list = []
    for _, row in df_in.iterrows():
        row_text = " ".join([safe_string(v).lower() for v in row.values])
        row_words = set(re.findall(r"\w+", row_text))
        score = len(q_words.intersection(row_words))
        score_list.append(score)

    temp = df_in.copy()
    temp["_score"] = score_list
    temp = temp.sort_values("_score", ascending=False)

    if temp["_score"].max() == 0:
        return df_in.head(top_k)

    return temp[temp["_score"] > 0].head(top_k).drop(columns=["_score"], errors="ignore")

def rows_to_text(df_in: pd.DataFrame) -> str:
    if df_in.empty:
        return "No matching rows found."
    records = df_in.fillna("").to_dict(orient="records")
    lines = []
    for i, rec in enumerate(records, start=1):
        lines.append(f"Row {i}: {rec}")
    return "\n".join(lines)

def try_direct_dataframe_answer(question: str, df_in: pd.DataFrame):
    q = question.lower().strip()

    try:
        if "how many employees" in q or "total employees" in q or "number of employees" in q:
            return f"Total employees: {len(df_in)}"

        if "average salary" in q:
            if "Salary" in df_in.columns:
                sal = pd.to_numeric(df_in["Salary"], errors="coerce")
                if sal.notna().sum() == 0:
                    return "I could not find valid salary values in the dataset."
                return f"Average salary: {sal.mean():.2f}"

        if "departments" in q or "list departments" in q:
            if "Department" in df_in.columns:
                vals = sorted(df_in["Department"].dropna().astype(str).str.strip().unique().tolist())
                return "Departments: " + ", ".join(vals)

        if "null phone" in q or "missing phone" in q:
            if "Phone" in df_in.columns:
                count = df_in["Phone"].isna().sum()
                return f"Rows with null phone values: {count}"

        if "null email" in q or "missing email" in q:
            if "Email" in df_in.columns:
                count = df_in["Email"].isna().sum()
                return f"Rows with null email values: {count}"

        if "invalid email" in q and "Email" in df_in.columns:
            count = (~df_in["Email"].apply(is_valid_email)).sum()
            return f"Invalid email count: {count}"

        if "invalid phone" in q and "Phone" in df_in.columns:
            count = (~df_in["Phone"].apply(is_valid_phone_10)).sum()
            return f"Invalid phone count: {count}"

    except Exception:
        pass

    return None

def ask_openrouter(api_key: str, question: str, df_in: pd.DataFrame) -> str:
    direct_answer = try_direct_dataframe_answer(question, df_in)
    if direct_answer:
        return direct_answer

    schema_text = dataframe_schema_text(df_in)
    relevant_rows = retrieve_relevant_rows(df_in, question, top_k=12)
    context_text = rows_to_text(relevant_rows)

    prompt = f"""
You are a data assistant for an employee Excel dataset.

Answer ONLY from the dataset context given below.
If the answer is not available in the context, say clearly:
"I could not find that in the dataset."

Dataset columns:
{schema_text}

Relevant dataset rows:
{context_text}

User question:
{question}

Rules:
- Be accurate.
- Do not invent values.
- Use only the dataset context.
- Keep the answer clear and concise.
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://dhayaeyassignment.streamlit.app",  
        "X-Title": "Employee Dataset Chatbot",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "You answer questions strictly from provided dataset context."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]

def apply_filters(data: pd.DataFrame,
                  dept_filter: list,
                  gender_filter: list,
                  country_filter: list,
                  status_filter: list) -> pd.DataFrame:
    out = data
    if dept_filter:
        out = out[out["Department"].isin(dept_filter)]
    if gender_filter:
        out = out[out["Gender"].isin(gender_filter)]
    if country_filter:
        out = out[out["Country"].isin(country_filter)]
    if status_filter:
        out = out[out["EmploymentStatus"].isin(status_filter)]
    return out

def simple_fix_dates(series: pd.Series) -> pd.Series:
    # Convert various messy strings to YYYY-MM-DD or NA
    s = series.astype("string").str.strip()
    # Remove ALL non-digit except / and -
    s = s.str.replace(r"[^0-9/\-]", "", regex=True)

    fixed = []
    for val in s:
        if pd.isna(val) or val == "":
            fixed.append(pd.NA)
            continue

        # Try direct pandas conversion (handles d/m/y, y-m-d, etc.)
        dt = pd.to_datetime(val, errors="coerce", dayfirst=True)

        # If still NaT, try compressed digits like 20240315
        if pd.isna(dt) and val.isdigit() and len(val) in [6, 7, 8]:
            # Try YYYYMMDD then DDMMYYYY fallback
            dt = pd.to_datetime(val, format="%Y%m%d", errors="coerce")
            if pd.isna(dt):
                dt = pd.to_datetime(val, dayfirst=True, errors="coerce")

        if pd.isna(dt):
            fixed.append(pd.NA)
        else:
            fixed.append(dt.strftime("%Y-%m-%d"))

    return pd.Series(fixed, dtype="object")

# -------------------------------------------------------
# SIDEBAR
# -------------------------------------------------------
st.sidebar.title("Options")
menu = st.sidebar.radio(
    "Choose an option:",
    ["Dataset", "Cleaned Dataset", "Visualization", "Chatbot"],
    index=0
)

# -------------------------------------------------------
# DATASET
# -------------------------------------------------------
if menu == "Dataset":
    st.subheader("📘 Dataset")
    st.dataframe(df, use_container_width=True)

# -------------------------------------------------------
# CLEANED DATASET
# -------------------------------------------------------
if menu == "Cleaned Dataset":
    st.title("🧹 Data Cleaning")

    email_col = "Email"
    phone_col = "Phone"
    hire_col = "HireDate"
    gender_col = "Gender"
    country_col = "Country"
    status_col = "EmploymentStatus"
    salary_col = "Salary"

    with st.expander("🧮 Null values"):
        null_counts = df.isnull().sum()
        result = null_counts.reset_index()
        total_nulls = df.isnull().sum().sum()
        st.markdown("**Total no of null values in each columns**")
        result.columns = ["Column", "Total Nulls"]
        st.dataframe(result, use_container_width=True, hide_index=True)
        st.write(f"Total no of null values: {total_nulls}")

    with st.expander("🧭 Duplicates"):
        dup_show = df.duplicated(keep=False)
        dup_full = df.duplicated(keep="first")

        c1, c2 = st.columns(2)
        c1.metric("Total rows", len(df))
        c2.metric("Exact duplicate rows", int(dup_full.sum()))

        st.markdown("**Preview of duplicate rows**")
        if dup_show.any():
            st.dataframe(df[dup_show], use_container_width=True, hide_index=True)

        if dup_full.any():
            st.success("Duplicate rows are removed (preview below)")

        df_dup = df[~df.duplicated(keep="first")].reset_index(drop=True)
        st.markdown(f"**Total rows(after removing duplicates): {len(df_dup)}**")
        st.dataframe(df_dup, use_container_width=True)

    with st.expander("📧📱 Email & Phone Validation"):
        work = df_dup.copy()
        work["_email_valid"] = work[email_col].apply(is_valid_email)
        work["_phone_digits"] = work[phone_col].apply(digits_only)
        work["_phone_valid"] = work[phone_col].apply(is_valid_phone_10)
        work["_all_valid"] = work["_email_valid"] & work["_phone_valid"]

        invalid_email_rows = work[~work["_email_valid"]].copy()
        invalid_phone_rows = work[~work["_phone_valid"]].copy()
        valid_rows = work[work["_all_valid"]].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Rows", len(work))
        c2.metric("Invalid Email", len(invalid_email_rows))
        c3.metric("Invalid Phone", len(invalid_phone_rows))
        c4.metric("Fully Valid", len(valid_rows))

        st.markdown("### 🔴 Rows with Invalid Email")
        st.dataframe(
            invalid_email_rows[["EmployeeID", "FullName", "Email"]]
            .reset_index(drop=True)
            .set_index(pd.Index(range(1, len(invalid_email_rows) + 1)))
        )

        st.markdown("### 🟠 Rows with Invalid Phone")
        st.dataframe(
            invalid_phone_rows[["EmployeeID", "FullName", "Phone"]]
            .reset_index(drop=True)
            .set_index(pd.Index(range(1, len(invalid_phone_rows) + 1)))
        )

        st.markdown("## 🧽 Cleaning: Set invalid Email/Phone to NULL")
        cleaned_email_phone = df_dup.copy()
        cleaned_email_phone.loc[~work["_email_valid"], email_col] = pd.NA
        cleaned_email_phone.loc[~work["_phone_valid"], phone_col] = pd.NA
        st.dataframe(cleaned_email_phone, use_container_width=True)

        df_after_email_phone = cleaned_email_phone

    with st.expander("📅 HireDate"):
        fmt = df_after_email_phone.copy()

        st.caption("Dates are converted to YYYY-MM-DD .")

        if hire_col in fmt.columns:
            orig = fmt[hire_col].copy()
            fixed = fix_date_format_force_series(orig)

            st.markdown("**Before vs After (HireDate)**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Before")
                st.dataframe(orig.to_frame(hire_col).head(15), use_container_width=True)
            with c2:
                st.markdown("After")
                st.dataframe(fixed.to_frame(hire_col).head(15), use_container_width=True)

            fmt[hire_col] = fixed

    with st.expander("🧱 Format Fix — Gender, Country & Employment Status"):
        if gender_col in fmt.columns:
            gender_formatted = normalize_gender(fmt[gender_col])
            st.markdown("**Before vs After (Gender)**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Before")
                st.dataframe(fmt[[gender_col]].head(15), use_container_width=True)
            with c2:
                st.markdown("After")
                tmp = fmt.copy()
                tmp[gender_col] = gender_formatted
                st.dataframe(tmp[[gender_col]].head(15), use_container_width=True)
            fmt[gender_col] = gender_formatted

        if country_col in fmt.columns:
            country_formatted = normalize_country(fmt[country_col])
            st.subheader("🌍 Country")
            st.markdown("**Before vs After (Country)**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Before")
                st.dataframe(fmt[[country_col]].head(15), use_container_width=True)
            with c2:
                st.markdown("After")
                tmp = fmt.copy()
                tmp[country_col] = country_formatted
                st.dataframe(tmp[[country_col]].head(15), use_container_width=True)
            fmt[country_col] = country_formatted

        if status_col in fmt.columns:
            st.subheader("💼 Employment Status")
            orig = fmt[status_col].astype("string")
            status_formatted = orig.str.title()

            st.markdown("**Before vs After (Employment Status)**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Before")
                st.dataframe(orig.to_frame(status_col).head(15), use_container_width=True)
            with c2:
                st.markdown("After")
                st.dataframe(status_formatted.to_frame(status_col).head(15), use_container_width=True)

            fmt[status_col] = status_formatted

        if salary_col in fmt.columns:
            st.subheader("💰 Salary")
            orig = fmt[salary_col].copy()
            cleaned_salary = clean_salary_series(orig)

            st.markdown("**Before vs After (Salary)**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Before")
                st.dataframe(orig.to_frame(salary_col).head(15), use_container_width=True)
            with c2:
                st.markdown("After (numeric)")
                st.dataframe(cleaned_salary.to_frame(salary_col).head(15), use_container_width=True)

            fmt[salary_col] = cleaned_salary

    with st.expander("📘 Final Dataset"):
        cleaned = fmt
        st.session_state["cleaned_df"] = cleaned.copy()

        st.markdown("### ✔️ Full Cleaned Dataset (after Format Fixes)")
        st.dataframe(cleaned, use_container_width=True)

        excel_bytes = to_excel_bytes(cleaned)
        st.download_button(
            label="⬇️ Download Cleaned Dataset (Excel)",
            data=excel_bytes,
            file_name="cleaned_dataset.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# -------------------------------------------------------
# VISUALIZATION (FILTERS AT TOP OF PAGE)
# -------------------------------------------------------
if menu == "Visualization":
    st.title("📊 Exploratory Visualizations")

    # Guard: require cleaned data
    if "cleaned_df" not in st.session_state or st.session_state["cleaned_df"] is None:
        st.warning("Please open **Cleaned Dataset** first to generate Visualization.")
        st.stop()

    base_df = st.session_state["cleaned_df"]

    # -------------------- FILTER BAR (TOP) --------------------
    st.subheader("🔍 Filters")
    with st.container():
        # Build choices from cleaned data (drop NA)
        dept_choices = sorted([x for x in base_df["Department"].dropna().unique().tolist()])
        gender_choices = sorted([x for x in base_df["Gender"].dropna().unique().tolist()])
        country_choices = sorted([x for x in base_df["Country"].dropna().unique().tolist()])
        status_choices = sorted([x for x in base_df["EmploymentStatus"].dropna().unique().tolist()])

        c1, c2 = st.columns(2)
        c3, c4 = st.columns(2)

        dept_filter = c1.multiselect("Department", options=dept_choices, default=[])
        gender_filter = c2.multiselect("Gender", options=gender_choices, default=[])
        country_filter = c3.multiselect("Country", options=country_choices, default=[])
        status_filter = c4.multiselect("Employment Status", options=status_choices, default=[])

        # Optional: clear filters button
        clear = st.button("Clear all filters")
        if clear:
            # Reset by rerunning with empty selections (Streamlit rerun handles this automatically)
            st.experimental_rerun()

    # Apply filters
    viz_df = apply_filters(
        base_df,
        dept_filter=dept_filter,
        gender_filter=gender_filter,
        country_filter=country_filter,
        status_filter=status_filter
    )

    # Resolve columns (from cleaned data)
    dept_col    = "Department"
    gender_col  = "Gender"
    status_col  = "EmploymentStatus"
    hire_col    = "HireDate"

    # Parse HireDate safely
    hire_parsed = pd.to_datetime(viz_df[hire_col], errors="coerce") if hire_col in viz_df.columns else None

    st.markdown("---")

    # Pre-compute aggregates
    dept_counts = (
        viz_df[dept_col].astype("string").str.strip().str.title().value_counts()
        if dept_col in viz_df.columns else pd.Series(dtype="int")
    )
    g_counts = (
        viz_df[gender_col].astype("string").str.strip().str.title().value_counts()
        if gender_col in viz_df.columns else pd.Series(dtype="int")
    )
    s_counts = (
        viz_df[status_col].astype("string").str.strip().str.title().value_counts()
        if status_col in viz_df.columns else pd.Series(dtype="int")
    )

    monthly = None
    if hire_col in viz_df.columns:
        tmp = viz_df.copy()
        tmp["ParsedDate"] = hire_parsed
        tmp = tmp.dropna(subset=["ParsedDate"]).set_index("ParsedDate")
        if not tmp.empty:
            monthly = tmp.resample("MS").size()

    # ---------------------- Row 1: Dept (Bar) | Gender (Pie) ----------------------
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🏢 Headcount by Department")
        if dept_counts.empty:
            st.info("No data to display for Department with current filters.")
        else:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.bar(dept_counts.index, dept_counts.values, color="#4e79a7")
            ax.set_xlabel("Department")
            ax.set_ylabel("Employees")
            ax.set_title("Headcount by Department")
            plt.xticks(rotation=45, ha="right")
            st.pyplot(fig)

    with col2:
        st.subheader("👤 Gender Distribution")
        if g_counts.empty:
            st.info("No data to display for Gender with current filters.")
        else:
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.pie(
                g_counts.values,
                labels=g_counts.index,
                autopct="%1.1f%%",
                startangle=90,
                colors=["#4e79a7", "#e15759", "#76b7b2", "#b07aa1"]
            )
            ax.axis("equal")
            st.pyplot(fig)

    # ---------------------- Row 2: Status (Bar) | Hiring Trend (Line) ----------------------
    col3, col4 = st.columns(2)

    with col3:
        st.subheader("💼 Employment Status Count")
        if s_counts.empty:
            st.info("No data to display for Employment Status with current filters.")
        else:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.barh(s_counts.index, s_counts.values, color="#59a14f")
            ax.set_xlabel("Employees")
            ax.set_ylabel("Employment Status")
            ax.set_title("Employees by Status")
            st.pyplot(fig)

    with col4:
        st.subheader("📈 Hiring Trend Over Time")
        if monthly is None or monthly.empty:
            st.info("No valid HireDate data to plot with current filters.")
        else:
            fig, ax = plt.subplots(figsize=(9, 4))
            ax.plot(monthly.index, monthly.values, marker="o", linewidth=2, color="#f28e2b")
            ax.set_xlabel("Year")
            ax.set_ylabel("New Hires")
            ax.set_title("Hiring Trend")
            ax.grid(True, linestyle="--", alpha=0.4)
            st.pyplot(fig)

# -------------------------------------------------------
# CHATBOT
# -------------------------------------------------------
if menu == "Chatbot":
    st.title("🤖 Excel Dataset Chatbot")

    st.info("Ask questions about the employee Excel dataset.")


    # default_api_key = os.getenv("OPENROUTER_API_KEY", "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")
    # api_key = "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"

    api_key = st.secrets.get("OPENROUTER_API_KEY", "")
    dataset_choice = st.radio(
        "Choose data source for chatbot:",
        ["Original Dataset", "Cleaned Dataset"],
        horizontal=True
    )

    if dataset_choice == "Cleaned Dataset" and "cleaned_df" in st.session_state and st.session_state["cleaned_df"] is not None:
        chat_df = st.session_state["cleaned_df"].copy()
    else:
        chat_df = df.copy()

    st.write(f"Rows available for chatbot: {len(chat_df)}")

    st.markdown("**Example questions**")
    st.write(
        "How many employees are there? | "
        "What is the average salary? | "
        "List departments | "
        "How many invalid emails are there? | "
        "Show employees from India"
    )

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    user_question = st.text_area("Ask your question")

    if st.button("Ask Chatbot"):
        if not api_key.strip():
            st.error("Please enter your OpenRouter API key.")
        elif not user_question.strip():
            st.error("Please enter a question.")
        else:
            try:
                with st.spinner("Generating answer..."):
                    answer = ask_openrouter(api_key.strip(), user_question.strip(), chat_df)

                st.session_state["chat_history"].append({
                    "question": user_question.strip(),
                    "answer": answer
                })
            except requests.exceptions.RequestException as e:
                st.error(f"API request failed: {e}")
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state["chat_history"]:
        st.markdown("### Chat History")
        for i, item in enumerate(reversed(st.session_state["chat_history"]), start=1):
            st.markdown(f"**Q{i}: {item['question']}**")
            st.write(item["answer"])
            st.markdown("---")
