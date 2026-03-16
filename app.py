import streamlit as st

import pandas as pd

import numpy as np

import re

import matplotlib.pyplot as plt

from io import BytesIO

 

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

 

df = pd.read_excel("dirty_employee_dataset_150_rows.xlsx")




 

# -------------------------------------------------------

# email functions

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

 

# ----------------------------- DATE FIX (NO NULLING) -----------------------------

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

 

def _strip_ordinals(s: str) -> str:

    # 1st -> 1, 2nd -> 2, 3rd -> 3, 4th -> 4

    return re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)

 

def _normalize_separators(s: str) -> str:

    s = s.replace(",", " ").strip()

    s = re.sub(r"[./]", "-", s)         # . or / -> -

    s = re.sub(r"\s+", " ", s)          # multiple spaces -> single

    s = re.sub(r"\s*-\s*", "-", s)      # normalize spaces around -

    return s

 

def _excel_serial_to_ts(val):

    """Excel serial date (days since 1899-12-30) -> Timestamp; else return None."""

    try:

        f = float(val)

        ts = pd.Timestamp("1899-12-30") + pd.to_timedelta(int(f), unit="D")

        if 1800 <= ts.year <= 2100:

            return ts

    except Exception:

        pass

    return None

 

def _try_parse_dt(s: str):

    """Try multiple parsing strategies; return Timestamp or None."""

    if s is None:

        return None

    if isinstance(s, (pd.Timestamp, np.datetime64)):

        try:

            ts = pd.to_datetime(s, errors="coerce")

            return ts if pd.notna(ts) else None

        except Exception:

            return None

 

    # Excel serials (if numeric)

    if isinstance(s, (int, float)) and not pd.isna(s):

        ts = _excel_serial_to_ts(s)

        if ts is not None:

            return ts

 

    # As string

    s0 = str(s).strip()

    if s0 == "":

        return None

 

    # If pure numeric-as-string (possible serial)

    if re.fullmatch(r"^\d+(\.\d+)?$", s0):

        ts = _excel_serial_to_ts(s0)

        if ts is not None:

            return ts

 

    # Clean string

    s1 = _strip_ordinals(s0)

    s1 = _normalize_separators(s1)

 

    # Try month-first then day-first

    for dayfirst in (False, True):

        try:

            ts = pd.to_datetime(s1, errors="coerce", dayfirst=dayfirst)

            if pd.notna(ts):

                return ts

        except Exception:

            pass

 

    # Try a set of explicit common formats

    candidates = [

        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",

        "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%B-%Y",

        "%b-%d-%Y", "%B-%d-%Y", "%d %b %Y", "%d %B %Y",

        "%b %d %Y", "%B %d %Y", "%d-%m-%y", "%m-%d-%y", "%d/%m/%y", "%m/%d/%y",

    ]

    for fmt in candidates:

        try:

            return pd.to_datetime(s1, format=fmt, errors="raise")

        except Exception:

            continue

 

    return None

 

def fix_date_format_force_series(series: pd.Series) -> pd.Series:

    """

    Force-fix: return YYYY-MM-DD if parseable; otherwise KEEP ORIGINAL value.

    (No nulling for invalid formats.)

    """

    def _fix(x):

        if pd.isna(x):

            return x  # preserve genuine NaN

        ts = _try_parse_dt(x)

        return ts.strftime("%Y-%m-%d") if ts is not None else str(x).strip()

 

    return series.map(_fix).astype("object")

 

# ----------------------------- GENDER / COUNTRY -----------------------------

def normalize_gender(series: pd.Series) -> pd.Series:

    """Format-oriented: map common variants & title-case; unknowns remain title-cased."""

    def _map(g):

        if pd.isna(g): return pd.NA

        s = str(g).strip().lower()

        if s in {"m", "male"}: return "Male"

        if s in {"f", "female"}: return "Female"

        if s in {"other", "others"}: return "Other"

        if s in {"prefer not to say"}:

            return "Prefer Not To Say"

    return series.map(_map)

 

def normalize_country(series: pd.Series) -> pd.Series:

    """Format-oriented: map common variants & smart title-case/acronyms."""

    def _map(c):

        if pd.isna(c): return pd.NA

        s = str(c).strip().lower().replace(".", "")

        if s in {"us", "usa","united states", "unitedstates"}:

            return "USA"

        if s in {"uk", "united kingdom", "unitedkingdom","united kindgom"}:

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

        # return smart_title_case_country(cleaned)

    return series.map(_map)

 

def clean_salary_series(series: pd.Series) -> pd.Series:

    """

    Remove currency symbols, commas and other non-numeric chars (keep digits).

    Convert to float.

    """

    s = series.astype("string")

 

    # Remove everything except digits, dot and minus

    cleaned = s.str.replace(r"[^\d\.\-]", "", regex=True).str.strip()

 

    # Convert to float

    def to_float(v):

        return float(v) if pd.notna(v) else pd.NA

 

    numeric = cleaned.map(to_float)

    return numeric

 

def to_excel_bytes(df_in: pd.DataFrame) -> BytesIO:

    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        df_in.to_excel(writer, index=False, sheet_name="cleaned")

    buffer.seek(0)

    return buffer

#...........

 

# -------------------------------------------------------

# SIDEBAR

# -------------------------------------------------------

st.sidebar.title("Options")

menu = st.sidebar.radio(

    "Choose an option:",

    ["Dataset", "Cleaned Dataset", "Visualization"],

    index=0

)

 

if menu=="Dataset":

    st.subheader("📘 Dataset")

    st.dataframe(df, use_container_width=True)

 

# -------------------------------------------------------

# CLEANED DATASET BUTTON (MAIN)

# -------------------------------------------------------

if menu=="Cleaned Dataset":

    st.title("🧹 Data Cleaning")

 

    email_col = "Email"

    phone_col = "Phone"

    hire_col = "HireDate"

    gender_col = "Gender"

    country_col = "Country"

    status_col = "EmploymentStatus"

    salary_col = "Salary"

 

    # ---------------------------------------------------

    # Expander 1: Total number of null values

    # ---------------------------------------------------

    with st.expander("🧮 Null values"):

        null_counts = df.isnull().sum()

        result = null_counts.reset_index()

        total_nulls = df.isnull().sum().sum()

        st.markdown("**Total no of null values in each columns**")

        result.columns = ["Column", "Total Nulls"]

        st.dataframe(result, use_container_width=True, hide_index=True)

        st.write(f"Total no of null values: {total_nulls}")

 

    # ---------------------------------------------------

    # Expander 2: Duplicates & Inconsistencies

    # ---------------------------------------------------

    with st.expander("🧭 Duplicates"):

        dup_show=df.duplicated(keep=False)

        dup_full = df.duplicated(keep="first")

        c1,c2=st.columns(2)

        c1.metric("Total rows",len(df))

        c2.metric("Exact duplicate rows",dup_full.sum())

        st.markdown("**Preview of duplicate rows**")

        if dup_show.any():

            st.dataframe(df[dup_show], use_container_width=True,hide_index=True)

 

        # Demo dedup by EmployeeID (non-destructive to original df shown above)

        if dup_full.any():

            st.success("Duplicate rows are removed (preview below)")

        df_dup=df[~df.duplicated(keep="first")].reset_index(drop=True)

        st.markdown(f"**Total rows(after removing duplicates):{len(df_dup)}**")

        st.dataframe(df_dup, use_container_width=True)

 

    # ---------------------------------------------------

    # Expander 3: Email & Phone Validation (fixed rules)

    # ---------------------------------------------------

    with st.expander("📧📱 Email & Phone Validation (fixed rules)"):

        work = df_dup.copy()

        work["_email_valid"] = work[email_col].apply(is_valid_email)

        work["_phone_digits"] = work[phone_col].apply(digits_only)

        work["_phone_valid"] = work[phone_col].apply(is_valid_phone_10)

        work["_all_valid"] = work["_email_valid"] & work["_phone_valid"]

 

        invalid_email_rows = work[~work["_email_valid"]].copy()

        invalid_phone_rows = work[~work["_phone_valid"]].copy()

        valid_rows = work[work["_all_valid"]].copy()

        # Summary

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Total Rows", len(work))

        c2.metric("Invalid Email", len(invalid_email_rows))

        c3.metric("Invalid Phone", len(invalid_phone_rows))

        c4.metric("Fully Valid", len(valid_rows))

 

        # Show Invalid Rows

        st.markdown("### 🔴 Rows with **Invalid Email**")

        st.dataframe(

            invalid_email_rows[["EmployeeID","FullName","Email"]].reset_index(drop=True).set_index(pd.Index(range(1, len(invalid_email_rows) + 1)))

        )

 

        st.markdown("### 🟠 Rows with **Invalid Phone**")

        st.dataframe(

            invalid_phone_rows[["EmployeeID","FullName","Phone"]].reset_index(drop=True).set_index(pd.Index(range(1, len(invalid_phone_rows) + 1)))

        )

 

        # Clean invalids (null the cells)

        st.markdown("## 🧽 Cleaning: Set invalid Email/Phone to NULL")

        cleaned_email_phone = df_dup.copy()

        cleaned_email_phone.loc[~work["_email_valid"], email_col] = pd.NA

        cleaned_email_phone.loc[~work["_phone_valid"], phone_col] = pd.NA

        st.dataframe(cleaned_email_phone, use_container_width=True)

        # We will carry forward this cleaned version into the next expander

        df_after_email_phone = cleaned_email_phone

 

    # ---------------------------------------------------

    # Expander 4: Format Fix & Validation — Dates, Gender, Country, Employment Status, Salary

    # ---------------------------------------------------

    with st.expander("📅 HireDate"):

        fmt = df_after_email_phone.copy()

 

        st.caption("Dates are force-converted to YYYY-MM-DD where possible (unparseable values stay unchanged). Other fields are format-normalized.")

 

        # ---------- HireDate ----------

        if hire_col:

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

        # ---------- Gender ----------

    with st.expander("🧱 Format Fix —Gender, Country & Employment Status"):

        if gender_col:

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

        fmt[gender_col]=gender_formatted

 

        # ---------- Country ----------

        if country_col:

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

        fmt[country_col]=country_formatted

 

        # ---------- Employment Status (format-only) ----------

        if status_col:

            st.subheader("💼 Employment Status")

            orig = fmt[status_col].copy()

            status_formatted = orig.str.title()

 

            st.markdown("**Before vs After (Employment Status)**")

            c1, c2 = st.columns(2)

            with c1:

                st.markdown("Before")

                st.dataframe(orig.to_frame(status_col).head(15), use_container_width=True)

            with c2:

                st.markdown("After")

                st.dataframe(status_formatted.to_frame(status_col).head(15), use_container_width=True)

 

            # Apply formatted status (no nulling)

            fmt[status_col] = status_formatted

 

        # ---------- Salary (symbol removal + numeric) ----------

        if salary_col:

            st.subheader("💰 Salary")

            orig = fmt[salary_col].copy()

            cleaned_salary = clean_salary_series(orig)

 

            st.markdown("**Before vs After (Salary)**")

            c1, c2 = st.columns(2)

            with c1:

                st.markdown("Before")

                st.dataframe(orig.to_frame(salary_col).head(15), use_container_width=True)

            with c2:

                st.markdown("After (numeric)**")

                st.dataframe(cleaned_salary.to_frame(salary_col).head(15), use_container_width=True)

 

            # Apply cleaned numeric salary

            fmt[salary_col] = cleaned_salary

    with st.expander("📘 Final Dataset"):

 

        # Final dataset after format fixes

        cleaned = fmt

        st.session_state["cleaned_df"] = cleaned.copy()

        st.markdown("### ✔️ Full Cleaned Dataset (after Format Fixes)")

        st.dataframe(cleaned, use_container_width=True)

 

        # Download button

        excel_bytes = to_excel_bytes(cleaned)

        st.download_button(

            label="⬇️ Download Cleaned Dataset (Excel)",

            data=excel_bytes,

            file_name="cleaned_dataset.xlsx",

            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        )

 

# -------------------------------------------------------

# VISUALIZATION BUTTON — 4 GRAPHS IN COLUMNS (CLEANED DATA ONLY)

# -------------------------------------------------------

if menu == "Visualization":

    st.title("📊 Exploratory Visualizations")

 

    # Guard: require cleaned data

    if "cleaned_df" not in st.session_state or st.session_state["cleaned_df"] is None:

        st.warning("Please open **Cleaned Dataset** first to generate Visualization.")

        st.stop()

 

    viz_df = st.session_state["cleaned_df"].copy()

 

    # Resolve columns (from cleaned data)

    dept_col    = "Department"

    gender_col  = "Gender"

    status_col  = "EmploymentStatus"

    hire_col    = "HireDate"

 

    # Parse HireDate safely

    hire_parsed = pd.to_datetime(viz_df[hire_col], errors="coerce") if hire_col else None

 

    st.markdown("---")

 

    # Pre-compute aggregates (so we can reuse in columns)

    dept_counts = (

        viz_df[dept_col].astype("string").str.strip().str.title().value_counts()

        if dept_col else pd.Series(dtype="int")

    )

 

    g_counts = (

        viz_df[gender_col].astype("string").str.strip().str.title().value_counts()

        if gender_col else pd.Series(dtype="int")

    )

 

    s_counts = (

        viz_df[status_col].astype("string").str.strip().str.title().value_counts()

        if status_col else pd.Series(dtype="int")

    )

 

    monthly = None

    if hire_col:

        tmp = viz_df.copy()

        tmp["ParsedDate"] = hire_parsed

        tmp = tmp.dropna(subset=["ParsedDate"]).set_index("ParsedDate")

        if not tmp.empty:

            monthly = tmp.resample("MS").size()

 

    # ---------------------- Row 1: Dept (Bar) | Gender (Pie) ----------------------

    col1, col2 = st.columns(2)

 

    with col1:

        st.subheader("🏢 Headcount by Department")

        fig, ax = plt.subplots(figsize=(7, 4))

        ax.bar(dept_counts.index, dept_counts.values, color="#4e79a7")

        ax.set_xlabel("Department")

        ax.set_ylabel("Employees")

        ax.set_title("Headcount by Department")

        plt.xticks(rotation=45, ha="right")

        st.pyplot(fig)

 

    with col2:

        st.subheader("👤 Gender Distribution")

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

        fig, ax = plt.subplots(figsize=(7, 4))

        ax.barh(s_counts.index, s_counts.values, color="#59a14f")

        ax.set_xlabel("Employment Status")

        ax.set_ylabel("Employees")

        ax.set_title("Employees by Status")

        plt.xticks(rotation=45, ha="right")

        st.pyplot(fig)

 

    with col4:

        st.subheader("📈 Hiring Trend Over Time")

        fig, ax = plt.subplots(figsize=(9, 4))

        ax.plot(monthly.index, monthly.values, marker="o", linewidth=2, color="#f28e2b")

        ax.set_xlabel("Year")

        ax.set_ylabel("New Hires")

        ax.set_title("Hiring Trend")

        ax.grid(True, linestyle="--", alpha=0.4)

        st.pyplot(fig)
