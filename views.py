"""UI views for the Insourcing Calculator Streamlit app."""
from __future__ import annotations

import copy
import json
from datetime import datetime
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
from auth import (
    authenticate,
    change_password,
    create_user,
    set_user_active,
    set_user_role,
)
from calculator import run_calculation
from session_store import create_session, delete_session
# added
from storage import (
    delete_project,
    delete_experimental_project,
    delete_user,
    get_projects_for_user,
    load_assumptions,
    load_audit_log,
    load_experimental_projects,
    load_users,
    save_assumptions,
    save_project,
    save_experimental_project,
    get_experimental_projects_for_user
)

LOCATIONS = ["USA", "W-Europe", "E-Europe", "India", "Mexico"]
WORKFORCE_TYPES = ["CW", "FTE"]
WORKFORCE_LABELS = {"CW": "Contract Worker", "FTE": "Full-Time Employee"}

# NOTE: save_experimental_project is imported from storage.py above.
# Do NOT redefine it here — a local redefinition previously shadowed the
# import, causing saved experimental projects to be written to the wrong
# path (or fail silently) and never show up under "Saved Experimental
# Projects".

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_timestamp(timestamp):
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    return dt.strftime("%d-%B-%Y at %H:%M")
                except:
                    pass
            return timestamp

def _fmt(x, digits=3, suffix=""):
    """Format number for display with specified decimal places without rounding during calculation"""
    if isinstance(x, (int, float)):
        return f"{x:,.{digits}f}{suffix}"
    return ""


def _year_row(title, data, pct=False):
    row = [title]
    for y in range(0, 6):
        k = f"Year{y}"
        cw, fte = data[k]["CW"], data[k]["FTE"]
        if pct:
            row.append(f"{cw:.2f}%" if isinstance(cw, (int, float)) else "")
            row.append(f"{fte:.2f}%" if isinstance(fte, (int, float)) else "")
        else:
            row.append(f"{cw:.2f}" if isinstance(cw, (int, float)) else "")
            row.append(f"{fte:.2f}" if isinstance(fte, (int, float)) else "")
    return row


def _normalize_view_selection(view: str) -> str:
    """Normalize view selection values so comparisons are robust."""
    return (view or "").strip().lower()


def _merge_particulars_header(html: str) -> str:
    """Post-process pandas MultiIndex HTML to merge the PARTICULARS header cell across two rows."""
    import re
    # Add rowspan=2 to the PARTICULARS header cell
    html = html.replace('<th>PARTICULARS</th>', '<th rowspan="2" class="particulars-th">PARTICULARS</th>', 1)
    # Remove the empty first cell in the second header row (the one below PARTICULARS)
    html = re.sub(r'(</tr>\s*<tr[^>]*>)\s*<th[^>]*>\s*</th>', r'\1', html, count=1)
    return html


def _cohort_rows(title, data):
    rows = []
    for cn in range(1, 6):
        row = [f"{title} {cn}"]
        for y in range(0, 6):
            k = f"Year{y}"
            ck = f"Cohort_{cn}"
            cw, fte = data[ck][k]["CW"], data[ck][k]["FTE"]
            row.append(f"{cw:.3f}" if cw != "" and isinstance(cw, (int, float)) else "")
            row.append(f"{fte:.3f}" if fte != "" and isinstance(fte, (int, float)) else "")
        rows.append(row)
    return rows


def _assumptions_diff(current: dict, defaults: dict) -> list[str]:
    """Returns list of dot-paths where current differs from defaults."""
    diffs = []

    def cmp(cur, dfl, path=""):
        if isinstance(cur, dict) and isinstance(dfl, dict):
            keys = set(cur.keys()) | set(dfl.keys())
            for k in keys:
                cmp(cur.get(k), dfl.get(k), f"{path}.{k}" if path else k)
        else:
            try:
                same = float(cur) == float(dfl) if cur is not None and dfl is not None else cur == dfl
            except (TypeError, ValueError):
                same = cur == dfl
            if not same:
                diffs.append(path)

    cmp(current, defaults)
    return diffs


def _load_logo_html(size_px: int = 64) -> str:
    """Return an <img> tag embedding the Carrier logo as base64.

    Uses the official Carrier logo PNG if present, else falls back to the
    original SVG wordmark.
    """
    import base64
    import os
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    png = os.path.join(base, "carrier_logo.png")
    svg = os.path.join(base, "carrier_logo.svg")
    if os.path.exists(png):
        with open(png, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{b64}" alt="Carrier" style="height:{size_px}px;width:auto;display:block;" />'
    if os.path.exists(svg):
        with open(svg, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------

def render_login():
    st.markdown('<div class="hero">', unsafe_allow_html=True)
    col_l, col_r = st.columns([0.8, 1.2])
    with col_l:
        st.markdown('<div class="hero-copy">', unsafe_allow_html=True)
        st.markdown(f'<div class="brand-lockup">{_load_logo_html(size_px=88)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="eyebrow">WORKFORCE ANALYTICS · INSOURCING</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-title-login">INSOURCING PLAYBOOK </div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="hero-sub">Model 5 year workforce transitions across different countries. Use standard assumptions or create experimental scenarios. Project annual and cumulative savings in headcount and cost.</p>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    with col_r:
        st.markdown('<div class="auth-title">Sign In</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-sub">Use your Carrier Workforce Account</div>', unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", key="login_email", placeholder="you@carrier.com")
            password = st.text_input("Password", type="password", key="login_password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
            if submitted:
                user, err = authenticate(email, password)
                if user:
                    st.session_state.user = user
                    st.session_state.page = "dashboard"
                    # Create persistent session token
                    token = create_session(user)
                    st.session_state.session_token = token
                    st.query_params["t"] = token
                    st.rerun()
                else:
                    st.error(err or "Invalid email or password.")

        st.caption("Access is restricted. If you need access, please contact an Administrator.")

       

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar():
    user = st.session_state.user

    with st.sidebar:
        # Brand + user info block at top
        st.markdown(
            f'''
            <div class="side-brand-block">
                <div class="side-brand-logo">{_load_logo_html(size_px=45)}</div>
                <div class="side-user-info">
                    <div class="uname">{user["name"]}</div>
                    <div class="urole">{user["role"]}</div>
                </div>
            </div>
            <div class="side-brand-gap"></div>
            ''',
            unsafe_allow_html=True,
        )

        # Navigation
        nav = [
            ("dashboard", "Saved Projects"),
            ("new_project", "New Calculation"),
            ("experimental_projects", "Saved Experimental Projects"),
        ]

        if user["role"] == "Administrator":
            nav.append(("assumptions", "Edit Assumptions"))
            nav.append(("access", "Access Control"))

        for key, label in nav:
            active = st.session_state.page == key

            if st.button(
                label,
                key=f"nav_{key}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state.page = key
                st.rerun()

        st.markdown(
            '<div class="sidebar-spacer"></div>',
            unsafe_allow_html=True
        )

        # Sign Out
        if st.button(
            "Sign Out",
            key="nav_logout",
            use_container_width=True
        ):
            token = st.session_state.get("session_token")

            if token:
                delete_session(token)

            st.query_params.clear()

            for k in list(st.session_state.keys()):
                del st.session_state[k]

            st.rerun()
# def render_sidebar():
#     user = st.session_state.user
#     with st.sidebar:
#         # Brand + user info block at top
#         st.markdown(
#             f'''
#             <div class="side-brand-block">
#                 <div class="side-brand-logo">{_load_logo_html(size_px=45)}</div>
#                 <div class="side-user-info">
#                     <div class="uname">{user["name"]}</div>
#                     <div class="urole">{user["role"]}</div>
#                 </div>
#             </div>
#             <div class="side-brand-gap"></div>
#             ''',
#             unsafe_allow_html=True,
#         )

#         nav = [
#             ("dashboard", "Saved Projects"),
#             ("new_project", "New Calculation"),
#             ("experimental_projects", "Saved Experimental Projects"),
#         ]
#         if user["role"] == "Administrator":
#             nav.append(("assumptions", "Edit Assumptions"))
#             nav.append(("access", "Access Control"))

#         for key, label in nav:
#             active = st.session_state.page == key
#             if st.button(label, key=f"nav_{key}", use_container_width=True,
#                          type="primary" if active else "secondary"):
#                 st.session_state.page = key
#                 st.rerun()


#         st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)

#         if st.button("Sign Out", key="nav_logout", use_container_width=True):
#             # Clean up persistent session
#             token = st.session_state.get("session_token")
#             if token:
#                 delete_session(token)
#             st.query_params.clear()
#             for k in list(st.session_state.keys()):
#                 del st.session_state[k]
#             st.rerun()


# ---------------------------------------------------------------------------
# Dashboard (Landing) — project history + summary
# ---------------------------------------------------------------------------

def render_dashboard():
    user = st.session_state.user
    all_projects = get_projects_for_user(user["email"], user["role"])
    all_experimental_projects = get_experimental_projects_for_user(user["email"], user["role"])
    all_projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    all_experimental_projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)

    st.markdown('<div class="page-header">', unsafe_allow_html=True)

    st.markdown(f'<h1 class="page-title">Welcome back, {user["name"].split()[0]}</h1>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Admin: per-user filter
    projects = all_projects
    if user["role"] == "Administrator" and all_projects:
        # Create mapping of names to emails
        all_users = load_users()
        name_to_email = {u.get("name", u["email"]): u["email"] for u in all_users}
        
        # Get unique owner names
        owner_emails = {p.get("owner", "?") for p in all_projects}
        owner_names = []
        for email in owner_emails:
            # Find the name for this email
            user_obj = next((u for u in all_users if u["email"] == email), None)
            if user_obj:
                owner_names.append(user_obj.get("name", email))
            # else:
            #     owner_names.append(email)
        owner_names = sorted(owner_names)
        
        filter_col, cta_col = st.columns([2, 1])
        with filter_col:
            sel = st.selectbox(
                "Filter by Owner",
                ["All Users"] + owner_names,
                key="admin_owner_filter",
            )
            if sel != "All Users":
                # Convert name back to email for filtering
                selected_email = name_to_email.get(sel, sel)
                projects = [p for p in all_projects if p.get("owner") == selected_email]
        with cta_col:
            st.markdown('<div style="height:25px"></div>', unsafe_allow_html=True)
            if st.button("＋  Start New Calculation", use_container_width=True, type="primary", key="cta_new"):
                st.session_state.page = "new_project"
                st.rerun()
    else:
        # top_l, top_r = st.columns([3, 1])
        # with top_r:
        if st.button("＋  Start New Calculation", use_container_width=True, type="primary", key="cta_new"):
            st.session_state.page = "new_project"
            st.rerun()

    if not projects:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-icon">◔</div>'
            '<h3>No projects yet</h3>'
            '<p>Save your first calculation to see history and cumulative savings here.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # KPI row across (filtered) projects
    # Calculate cumulative scenario saving (sum of Year 5 cumulative gains)
    cumulative_scenario_saving = sum(
        (p["result"]["cumulative_gain"]["Year5"].get(p["inputs"]["new_workforce"], 0) or 0) 
        for p in projects
    )
    
    # Calculate average cumulative savings (average of Year 5 cumulative gains)
    avg_cumulative_savings = cumulative_scenario_saving / len(projects) if projects else 0
    
    # Calculate average annual savings (average of Years 1-5 annual gains across all projects)
    total_annual_gains = 0
    count_annual_gains = 0
    for p in projects:
        new_wf = p["inputs"]["new_workforce"]
        for year in range(1, 6):
            year_key = f"Year{year}"
            gain = p["result"]["annual_gain_or_loss"][year_key].get(new_wf, 0)
            if isinstance(gain, (int, float)):
                total_annual_gains += gain
                count_annual_gains += 1
    avg_annual_savings = total_annual_gains / count_annual_gains if count_annual_gains > 0 else 0
    
    unique_users = len({p.get("owner", "?") for p in projects})
    
    if user["role"] == "Administrator":
        k1, k2, k3, k4 = st.columns([0.9, 1.2, 1, 1.2])
        with k1:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Total Projects</div><div class="kpi-val">{len(projects)}</div></div>',unsafe_allow_html=True,)
        with k2:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Cumulative Savings </div><div class="kpi-val">$ {cumulative_scenario_saving:.3f} M</div></div>',unsafe_allow_html=True,)
        with k3:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Average Savings </div><div class="kpi-val">$ {avg_cumulative_savings:.3f} M</div></div>',unsafe_allow_html=True,)
        with k4:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Average Annual Savings </div><div class="kpi-val">$ {avg_annual_savings:.3f} M</div></div>',unsafe_allow_html=True,)

    else:
        k1, k2, k3 = st.columns(3)
        with k1:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Total Projects</div><div class="kpi-val">{len(projects)}</div></div>',unsafe_allow_html=True,)
        with k2:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Cumulative Savings</div><div class="kpi-val">$ {cumulative_scenario_saving:.3f} M</div></div>',unsafe_allow_html=True,)
        with k3:
            st.markdown(f'<div class="kpi"><div class="kpi-lbl">Average Savings ($M)</div><div class="kpi-val">$ {avg_cumulative_savings:.3f} M</div></div>',unsafe_allow_html=True,)
    # ==========================================================
    # Scenario Type Selector
    # ==========================================================

    st.markdown('<div class="section-title">SAVED SCENARIOS</div>', unsafe_allow_html=True)
    for p in projects:
        r = p["result"]
        new_wf = p["inputs"]["new_workforce"]
        curr_wf = p["inputs"]["curr_workforce"]
        total_cum = r["total_5yr_cumulative"][new_wf]
        buildout = r["buildout_pmo_cost"]
        
        # Calculate average annual target savings for this project
        annual_gains = [r["annual_gain_or_loss"][f"Year{y}"][new_wf] for y in range(1, 6)]
        annual_gains_valid = [g for g in annual_gains if isinstance(g, (int, float))]
        avg_annual_target = sum(annual_gains_valid) / len(annual_gains_valid) if annual_gains_valid else 0
        
        cls = "delta-pos" if avg_annual_target >= 0 else "delta-neg"

        def _fv(v, d=3):
            return f"{v:,.{d}f}" if isinstance(v, (int, float)) else "—"

        row_defs = [
            ("Cumulative Gain ($M)",
             [r["cumulative_gain"][f"Year{y}"][new_wf] for y in range(1, 6)]),
        ]
        rows_html = "".join(
            f"<tr><td class='lbl'>{lbl}</td>"
            + "".join(f"<td>{_fv(v)}</td>" for v in vals) + "</tr>"
            for lbl, vals in row_defs
        )
        timestamp = p.get("updated_at", "")
        timestamp =format_timestamp(timestamp)
        # created = format_timestamp(p.get("created_at", ""))
        if p["inputs"]["capacity_check"] == "Yes":
            capacity_text = f'<span style="white-space: normal;">This scenario evaluates the transition of <b>{p["inputs"]["num_people"]}</b> <b>{WORKFORCE_LABELS.get(curr_wf, curr_wf)}s</b> from <b>{p["inputs"]["curr_location"]}</b> to <b>{p["inputs"]["new_location"]}</b> as <b>{WORKFORCE_LABELS.get(new_wf, new_wf)}s</b>. The target office in {p["inputs"]["new_location"]} <b>has</b> the required infrastructure capacity to support this transition.</span>'
        else:
            capacity_text = f'<span style="white-space: normal;">This scenario evaluates the transition of <b>{p["inputs"]["num_people"]}</b> <b>{WORKFORCE_LABELS.get(curr_wf, curr_wf)}s</b> from <b>{p["inputs"]["curr_location"]}</b> to <b>{p["inputs"]["new_location"]}</b> as <b>{WORKFORCE_LABELS.get(new_wf, new_wf)}s</b>. The target office in {p["inputs"]["new_location"]} <b>does not have</b> the required infrastructure capacity for this transition.</span>'
        st.markdown(
            f'''
            <div class="proj-card">
              <div class="proj-header">
                <div class="proj-header-left">
                  <div class="proj-name">{p["name"]}</div>
                    <div class="proj-meta">
                        {capacity_text}
                    </div>
                </div>
                <div class="proj-total">
                  <div class="pt-lbl">Average Annual Target Savings</div>
                  <div class="pt-val {cls}">$ {avg_annual_target:.3f} M</div>
                </div>
              </div>
              <table class="mini-table">
                <thead><tr><th>Metric</th><th>Year 1</th><th>Year 2</th><th>Year 3</th><th>Year 4</th><th>Year 5</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
              <div class="proj-inline-info">
                    <div>Buildout & PMO (One Time): <b>$ {buildout:.3f} M</b></div>
                    <div>Saved: <b>{timestamp}</b></div>
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

        # Buttons for View Details and Delete - inline with the buildout info
        b1, b2 = st.columns([ 1, 1])
        with b1:
            if st.button(
                "View Details",
                key=f"view_{p['id']}",
                use_container_width=True
            ):
                st.session_state.viewing_project = p["id"]
                st.session_state.page = "view_project"
                st.rerun()

        with b2:
            if st.button(
                "Delete",
                key=f"del_{p['id']}",
                use_container_width=True
            ):
                delete_project(
                    p["id"],
                    None if user["role"] == "Administrator" else user["email"]
                )
                st.rerun()
        
        # Bottom separator between project cards
        st.markdown('<div class="proj-card-sep"></div>', unsafe_allow_html=True)





# ---------------------------------------------------------------------------
# View saved project details
# ---------------------------------------------------------------------------

def render_view_project():
    pid = st.session_state.get("viewing_project")
    user = st.session_state.user
    projects = get_projects_for_user(user["email"], user["role"])
    p = next((x for x in projects if x["id"] == pid), None)
    if not p:
        st.warning("Project not found.")
        # if st.button("Back to dashboard"):
        #     st.session_state.page = "dashboard"
        #     st.rerun()
        return

    # if st.button("Back to dashboard"):
    #     st.session_state.page = "dashboard"
    #     st.rerun()

    # st.markdown(f'<div class="eyebrow">PROJECT</div>', unsafe_allow_html=True)
    st.markdown(f'<h1 class="page-title">{p["name"]}</h1>', unsafe_allow_html=True)
    st.caption(f'Last updated {p.get("updated_at","")[:19].replace("T"," ")}')

    _render_result_tables(p["result"], p["inputs"])

def delete_user(user_name):
    users = load_users()
    original_count = len(users)
    users = [u for u in users if u.get("name") != user_name]
    if len(users) == original_count:
        return False, "User not found."
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)
    return True, "User revoked successfully."
# ---------------------------------------------------------------------------
# New Calculation page
# ---------------------------------------------------------------------------

def render_new_project():
    user = st.session_state.user
    admin_defaults = load_assumptions()   # persisted admin defaults

    # Session storage for the in-progress assumptions
    if "wa_assumptions" not in st.session_state:
        st.session_state.wa_assumptions = copy.deepcopy(admin_defaults)

    # st.markdown('<div class="eyebrow">NEW MODEL</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Build a Calculation</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-sub">Enter a project name, configure the workforce transition inputs, and optionally modify assumptions in Experimental Mode. Only calculations generated using administrator-approved default assumptions can be saved by business users.</p>',
        unsafe_allow_html=True,
    )

    # Top row
    
    project_col, toggle_col, assum_col = st.columns([2, 1.1, 2], vertical_alignment="center")

    with project_col:
        st.markdown('<div class="setup-col project-col">', unsafe_allow_html=True)
        project_name = st.text_input("PROJECT NAME",key="np_name",placeholder="e.g. FY26 Q1 India Ops Transition")
        st.markdown('</div>', unsafe_allow_html=True)

    with toggle_col:
        st.markdown('<div style="height:25px">', unsafe_allow_html=True)
        experimental = st.toggle("Experimental mode",value=st.session_state.get("np_experimental", False),key="np_experimental")
        st.markdown('</div>', unsafe_allow_html=True)
    with assum_col:
        if experimental:
            st.markdown(
                """
                <div class="setup-col assum-col notice warn" style="margin-top:10px;">
                    This output uses the custom assumptions provided by the Administrator. The results cannot be saved.
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="setup-col assum-col notice ok" style="margin-top:10px;">
                    This output uses the default assumptions provided by the Administrator.
                    The results can be saved.
                </div>
                """,
                unsafe_allow_html=True,
            )

    c1, c2, c3, c4, c5, c6 = st.columns([1, 1.3, 1.3, 1, 1, 1])
    with c1:
        num_people = st.number_input("People", min_value=1, value=100, step=1, key="np_people")
    with c2:
        curr_workforce = st.selectbox("Current Workforce", WORKFORCE_TYPES, key="np_cwf")
    with c3:
        curr_location = st.selectbox("Current Location", LOCATIONS, key="np_cloc")
    with c4:
        new_workforce = st.selectbox("New Workforce", WORKFORCE_TYPES, index=1, key="np_nwf")
    with c5:
        new_location = st.selectbox("New Location", LOCATIONS, index=3, key="np_nloc")
    with c6:
        capacity_check = st.selectbox("Capacity", ["Yes", "No"], index=1, key="np_cap")

    # --- Assumption editor (experimental)
    
    # working_assumptions = copy.deepcopy(admin_defaults)
    # --- Assumption editor (experimental)
    working_assumptions = copy.deepcopy(admin_defaults)

    if experimental:
        st.markdown(
            '<div class="card-title standalone warn">Experimental Assumptions '
            '<span class="badge-warn">Experimental Run</span></div>',
            unsafe_allow_html=True,
        )

        working_assumptions = _render_assumption_editor(
            st.session_state.wa_assumptions,
            key_prefix="exp"
        )

        st.session_state.wa_assumptions = working_assumptions


    # --- Calculate / Save
    # --- Calculate / Save
    calc_col, save_col = st.columns([1, 1])

    with calc_col:
        if st.button(
            "Calculate",
            type="primary",
            key="btn_calc",
            use_container_width=True
        ):
            inputs = {
                "num_people": num_people,
                "curr_workforce": curr_workforce,
                "curr_location": curr_location,
                "new_workforce": new_workforce,
                "new_location": new_location,
                "capacity_check": capacity_check,
            }

            try:
                result = run_calculation(
                    working_assumptions,
                    inputs
                )

                st.session_state.np_last_result = result
                st.session_state.np_last_inputs = copy.deepcopy(inputs)

                # IMPORTANT: save a snapshot of assumptions used
                st.session_state.np_last_assumptions = copy.deepcopy(
                    working_assumptions
                )

            except Exception as e:
                st.error(f"Calculation failed: {e}")

    with save_col:
        result = st.session_state.get("np_last_result")

        if result:
            inputs = st.session_state.get("np_last_inputs", {})

            used_assumptions = st.session_state.get(
                "np_last_assumptions",
                copy.deepcopy(admin_defaults)
            )

            diffs = _assumptions_diff(
                used_assumptions,
                admin_defaults
            )

            is_experimental_result = len(diffs) > 0

            can_save = bool(project_name.strip())

            if st.button(
                "💾 Save Project",
                key="btn_save",
                type="primary",
                use_container_width=True,
                disabled=not can_save
            ):
                p = {
                    "name": project_name.strip(),
                    "owner": user["email"],
                    "owner_role": user["role"],
                    "inputs": copy.deepcopy(inputs),
                    "result": copy.deepcopy(result),
                    "used_experimental_assumptions": is_experimental_result,
                    "project_type": (
                        "Experimental"
                        if is_experimental_result
                        else "Standard"
                    ),
                    "assumptions_snapshot": (
                        copy.deepcopy(used_assumptions)
                        if is_experimental_result
                        else None
                    ),
                }

                if is_experimental_result:
                    save_experimental_project(p)
                    st.success(
                        f"Experimental project '{project_name}' saved."
                    )
                else:
                    save_project(p)
                    st.success(
                        f"Project '{project_name}' saved."
                    )

                st.session_state.pop("np_last_result", None)
                st.session_state.page = "dashboard"
                st.rerun()

    # --- Results
    if st.session_state.get("np_last_result"):

        result = st.session_state.np_last_result
        inputs = st.session_state.np_last_inputs

        used_assumptions = st.session_state.get(
            "np_last_assumptions",
            copy.deepcopy(admin_defaults)
        )

        diffs = _assumptions_diff(
            used_assumptions,
            admin_defaults
        )

        is_experimental_result = len(diffs) > 0

        st.markdown(
            '<div class="section-title">Results</div>',
            unsafe_allow_html=True
        )

        if is_experimental_result:
            st.markdown(
                f'<div class="notice warn">'
                f'This result uses <b>{len(diffs)}</b> '
                f'experimental assumption override(s). '
                f'The project will be saved as an '
                f'<b>Experimental Project</b>.'
                f'</div>',
                unsafe_allow_html=True,
            )

        _render_result_tables(result, inputs)
    # calc_col, save_col = st.columns([1, 1])

    # with calc_col:
    #     if st.button("Calculate", type="primary", key="btn_calc", use_container_width=True):
    #         inputs = {
    #             "num_people": num_people,
    #             "curr_workforce": curr_workforce,
    #             "curr_location": curr_location,
    #             "new_workforce": new_workforce,
    #             "new_location": new_location,
    #             "capacity_check": capacity_check,
    #         }

    #         try:
    #             result = run_calculation( working_assumptions, inputs)
    #             st.session_state.np_last_result = result
    #             st.session_state.np_last_inputs = inputs
    #             st.session_state.np_last_assumptions = working_assumptions

    #         except Exception as e:
    #             st.error(f"Calculation failed: {e}")


    # with save_col:
    #     result = st.session_state.get("np_last_result")
    #     if result:
    #         inputs = st.session_state.get("np_last_inputs", {})
    #         used_assumptions = st.session_state.get("np_last_assumptions",admin_defaults)
    #         diffs = _assumptions_diff(used_assumptions,admin_defaults)
    #         is_experimental_result = len(diffs) > 0
    #         can_save = bool(project_name.strip())
    #         if st.button(" Save Project",key="btn_save", type="primary",use_container_width=True,disabled=not can_save):
    #             p = {
    #                 "name": project_name.strip(),
    #                 "owner": user["email"],
    #                 "owner_role": user["role"],
    #                 "inputs": inputs,
    #                 "result": result,
    #                 "used_experimental_assumptions": is_experimental_result,
    #                 "project_type": ("Experimental" if is_experimental_result else "Standard"),
    #                 "assumptions_snapshot": (copy.deepcopy(used_assumptions) if is_experimental_result else None),
    #             }

    #             if is_experimental_result:
    #                 save_experimental_project(p)
    #                 st.success(f"Experimental project '{project_name}' saved.")
    #             else:
    #                 save_project(p)
    #                 st.success(
    #                     f"Project '{project_name}' saved."
    #                 )

    #             st.session_state.pop("np_last_result", None)
    #             st.session_state.page = "dashboard"
    #             st.rerun()


    # # --- Results
    # if st.session_state.get("np_last_result"):

    #     result = st.session_state.np_last_result
    #     inputs = st.session_state.np_last_inputs
    #     used_assumptions = st.session_state.np_last_assumptions

    #     diffs = _assumptions_diff(
    #         used_assumptions,
    #         admin_defaults
    #     )

    #     is_experimental_result = len(diffs) > 0

    #     st.markdown(
    #         '<div class="section-title">Results</div>',
    #         unsafe_allow_html=True
    #     )

    #     if is_experimental_result:
    #         st.markdown(
    #             f'<div class="notice warn">'
    #             f'This result uses <b>{len(diffs)}</b> '
    #             f'experimental assumption override(s). '
    #             f'The project will be saved as an '
    #             f'<b>Experimental Project</b>.'
    #             f'</div>',
    #             unsafe_allow_html=True,
    #         )

    #     _render_result_tables(result, inputs)
    # if experimental:
    #     st.markdown(
    #         '<div class="card-title standalone warn">Experimental Assumptions '
    #         '<span class="badge-warn">Experimental Run · Cannot Be Saved</span></div>',
    #         unsafe_allow_html=True,
    #     )
    #     working_assumptions = _render_assumption_editor(
    #         st.session_state.wa_assumptions, key_prefix="exp"
    #     )
    #     st.session_state.wa_assumptions = working_assumptions

    # # --- Calculate / Save
    # calc_col, save_col = st.columns([1, 1])
    # with calc_col:
    #     if st.button("Calculate", type="primary", key="btn_calc", use_container_width=True):
    #         inputs = {
    #             "num_people": num_people, "curr_workforce": curr_workforce,
    #             "curr_location": curr_location, "new_workforce": new_workforce,
    #             "new_location": new_location, "capacity_check": capacity_check,
    #         }
    #         try:
    #             result = run_calculation(working_assumptions, inputs)
    #             st.session_state.np_last_result = result
    #             st.session_state.np_last_inputs = inputs
    #             st.session_state.np_last_assumptions = working_assumptions
    #         except Exception as e:
    #             st.error(f"Calculation failed: {e}")

    # with save_col:
    #     result = st.session_state.get("np_last_result")
    #     if result:
    #         inputs = st.session_state.get("np_last_inputs", {})
    #         used_assumptions = st.session_state.get("np_last_assumptions", admin_defaults)
    #         diffs = _assumptions_diff(used_assumptions, admin_defaults)
    #         is_experimental_result = len(diffs) > 0
    #         can_save = (not is_experimental_result) or user["role"] == "Administrator"
    #         can_save = can_save and bool(project_name.strip())
    #         if st.button("💾  Save project", key="btn_save",
    #                      type="primary", use_container_width=True, disabled=not can_save):
    #             p = {
    #                 "name": project_name.strip(),
    #                 "owner": user["email"],
    #                 "owner_role": user["role"],
    #                 "inputs": inputs,
    #                 "result": result,
    #                 "used_experimental_assumptions": is_experimental_result,
    #                 "assumptions_snapshot": used_assumptions if is_experimental_result else None,
    #             }
    #             save_project(p)
    #             st.success(f"Project '{project_name}' saved.")
    #             st.session_state.pop("np_last_result", None)
    #             st.session_state.page = "dashboard"
    #             st.rerun()

    # # --- Results
    # if st.session_state.get("np_last_result"):
    #     result = st.session_state.np_last_result
    #     inputs = st.session_state.np_last_inputs
    #     used_assumptions = st.session_state.np_last_assumptions

    #     diffs = _assumptions_diff(used_assumptions, admin_defaults)
    #     is_experimental_result = len(diffs) > 0

    #     st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)

    #     if is_experimental_result:
    #         st.markdown(
    #             f'<div class="notice warn">This result uses <b>{len(diffs)}</b> '
    #             f'experimental assumption override(s). '
    #             + ('Admins may still save.' if user["role"] == "Administrator"
    #                else 'Business users cannot save experimental results.')
    #             + '</div>',
    #             unsafe_allow_html=True,
    #         )
    #     _render_result_tables(result, inputs)





import pandas as pd
from numbers import Number

def table_to_html(df):
    html = "<table>"
    # Header row 1
    html += "<thead>"
    html += "<tr>"
    for col in df.columns.get_level_values(0):
        html += f"<th>{col}</th>"
    html += "</tr>"
    # Header row 2
    html += "<tr>"
    for col in df.columns.get_level_values(1):
        html += f"<th>{col}</th>"
    html += "</tr>"
    html += "</thead>"
    html += "<tbody>"
    for _, row in df.iterrows():
        html += "<tr>"
        for i, value in enumerate(row):
            if i == 0:
                cls = "first-col"
            elif value == "":
                cls = "txt"
            elif isinstance(value, Number):
                cls = "num"
            else:
                cls = "txt"
            html += f'<td class="{cls}">{value}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    return html


# ---------------------------------------------------------------------------
# Result tables rendering (shared)
# ---------------------------------------------------------------------------

def _render_result_tables(r: dict, inputs: dict):
    curr_wf = inputs["curr_workforce"]
    new_wf = inputs["new_workforce"]
    num_people = inputs["num_people"]

    # Frontend columns - use short forms CW and FTE inside the table
    
    frontend_columns = pd.MultiIndex.from_tuples(
        [("PARTICULARS", "")] + 
        [(f"Year {y}", t) for y in range(1, 6) for t in ("CW", "FTE")]
    )


    def add_row(rows, title, fn):
        row = [title]
        for y in range(1, 6):
            cw, fte = fn(f"Year{y}")
            row.extend([cw, fte])
        rows.append(row)

    def safe_div(n, d):
        return n / d if d else 0

    tpc = r["total_post_cycle"]
    curr_ac = r["curr_estimated_annual_cost"]
    new_ac = r["new_estimated_annual_cost"]
    gain = r["annual_gain_or_loss"]
    cum = r["cumulative_gain"]

    fe_rows = []
    add_row(fe_rows, "Number of People in Current Workforce",
        lambda y: (int(num_people), "") if curr_wf == "CW" else ("", int(num_people)))

    add_row(fe_rows, "Location of Current Workforce",
            lambda y: (inputs["curr_location"], "") if curr_wf == "CW" else ("", inputs["curr_location"]))

    add_row(fe_rows, "Recommended Number of People in New Workforce",
            lambda y: (round(tpc[y]["CW"]), "") if new_wf == "CW" else ("", round(tpc[y]["FTE"])))

    add_row(fe_rows, "Location of New Workforce",
            lambda y: (inputs["new_location"], "") if new_wf == "CW" else ("", inputs["new_location"]))

    add_row(fe_rows, "Target Ratio",
            lambda y: (f"{round(safe_div(tpc[y]['CW'], num_people),3)}", "") if new_wf == "CW"
            else ("", f"{round(safe_div(tpc[y]['FTE'], num_people),3)}"))

    add_row(fe_rows, "Inverse Target Ratio",
            lambda y: (f"{round(safe_div(num_people, tpc[y]['CW']),3)}", "") if new_wf == "CW"
            else ("", f"{round(safe_div(num_people, tpc[y]['FTE']),3)}"))

    add_row(fe_rows, "Current Estimated Annual Cost ($M)",
            lambda y: (f"{round(curr_ac[y]['CW'],3)}", "") if curr_wf == "CW"
            else ("", f"{round(curr_ac[y]['FTE'],3)}"))

    add_row(fe_rows, "New Estimated Annual Cost ($M)",
            lambda y: (f"{round(new_ac[y]['CW'],3)}", "") if new_wf == "CW"
            else ("", f"{round(new_ac[y]['FTE'],3)}"))

    add_row(fe_rows, "Estimated Annual Gain or Loss ($M)",
            lambda y: (f"{round(gain[y]['CW'],3)}", "") if new_wf == "CW"
            else ("", f"{round(gain[y]['FTE'],3)}"))

    add_row(fe_rows, "Buildout and Project Management Office Cost (One-Time) ($M)",
            lambda y: (f"{round(r['buildout_pmo_cost'],3)}", "") if y == "Year1" else ("", ""))

    add_row(fe_rows, "Cumulative Gain ($M)",
            lambda y: (f"{round(cum[y]['CW'],3)}", "") if new_wf == "CW"
            else ("", f"{round(cum[y]['FTE'],3)}"))
    df_fe = pd.DataFrame(fe_rows, columns=frontend_columns)

    view = st.selectbox("", ["Summary", "Backend (Detailed)", "Assumptions Used"], key="view_sel")
    view_key = _normalize_view_selection(view)
    
    # st.write("view =", view)
    # st.write("view_key =", view_key)

    if view_key == "summary":
        html_out = _merge_particulars_header(df_fe.to_html(index=False))
        st.markdown(f'<div class="frontend-table">{html_out}</div>',unsafe_allow_html=True)

        # Show total 5-year cumulative gain
        # t = r["total_5yr_cumulative"]
        # st.markdown(
        #     f'<div class="total-strip">'
        #     f'Total 5-year Cumulative Gain ({new_wf}): '
        #     f'${t[new_wf]:.3f} M</div>',
        #     unsafe_allow_html=True,
        # )

    elif view_key == "backend (detailed)":
        be_columns = pd.MultiIndex.from_tuples([("PARTICULARS","")] +
            [(f"Year {y}", t) for y in range(0, 6) for t in ("CW", "FTE")])
        be_rows = []
        be_rows.append(_year_row("Working Hours Per Day", r["working_hrs_pd"]))
        be_rows.append(_year_row("Productive Hours Per Day", r["productive_hrs_pd"]))
        be_rows.append(_year_row("Structural Productivity Gain", r["structural_gain"], pct=True))
        be_rows.append(_year_row("Artificial Intelligence and Automation Gain", r["automation_gain"], pct=True))
        be_rows.append(_year_row("Annual Experience Gain Percentage", r["experience_gain"], pct=True))
        be_rows.append(_year_row("Retention Rate Percentage", r["retention"], pct=True))

        be_rows.extend(_cohort_rows("Capability Density by Cohort", r["capability_density"]))
        be_rows.extend(_cohort_rows("Pre-Cycle Cohort", r["pre_cycle"]))

        be_rows.append(_year_row("Total Pre-Cycle Cohort", r["total_pre_cycle"]))

        be_rows.append(_year_row("Backfill Through Automation", r["backfill_by_automation"]))
        be_rows.append(_year_row("Cumulative Backfill Through Automation", r["cumulative_backfill_by_automation"]))

        be_rows.append(_year_row("Gross Backfill Through Workforce", r["backfill_gross"]))
        be_rows.append(_year_row("Net Backfill Through Workforce", r["backfill_net"]))

        be_rows.extend(_cohort_rows("Pre-Cycle Effective Cohort", r["pre_cycle_effective"]))

        be_rows.append(_year_row("Total Pre-Cycle Effective Cohort", r["total_pre_cycle_effective"]))

        be_rows.extend(_cohort_rows("Post-Cycle Cohort", r["post_cycle"]))

        be_rows.append(_year_row("Total Post-Cycle Cohort", r["total_post_cycle"]))

        be_rows.append(_year_row("Previous Hourly Personnel Cost (Including Overhead)", r["curr_hourly_person_cost"]))
        be_rows.append(_year_row("Previous Hourly Management Overhead Cost", r["curr_hourly_mgmt_cost"]))
        be_rows.append(_year_row("Previous Profit Percentage", r["curr_profit_percentage"]))
        be_rows.append(_year_row("Previous Profit Margin", r["curr_profit_margin"]))
        be_rows.append(_year_row("Previous Hourly Cost per Person (Including Profit)", r["curr_hourly_cost_per_person"]))
        be_rows.append(_year_row("Previous Layoff Risk Percentage", r["curr_layoff_risk"]))
        be_rows.append(_year_row("Previous Layoff Cost Percentage", r["curr_layoff_payoff"]))
        be_rows.append(_year_row("Previous Layoff Cost per Hour", r["curr_layoff_cost_perhour"]))
        be_rows.append(_year_row("Previous Fully Loaded Hourly Cost", r["curr_fully_loaded"]))

        be_rows.append(_year_row("New Hourly Personnel Cost (Including Overhead)", r["new_hourly_person_cost"]))
        be_rows.append(_year_row("New Hourly Management Overhead Cost", r["new_hourly_mgmt_cost"]))
        be_rows.append(_year_row("New Profit Percentage", r["new_profit_percentage"]))
        be_rows.append(_year_row("New Profit Margin", r["new_profit_margin"]))
        be_rows.append(_year_row("New Hourly Cost per Person (Including Profit)", r["new_hourly_cost_per_person"]))
        be_rows.append(_year_row("New Layoff Risk Percentage", r["new_layoff_risk"]))
        be_rows.append(_year_row("New Layoff Cost Percentage", r["new_layoff_payoff"]))
        be_rows.append(_year_row("New Layoff Cost per Hour", r["new_layoff_cost_perhour"]))
        be_rows.append(_year_row("New Fully Loaded Hourly Cost", r["new_fully_loaded"]))
        df_be = pd.DataFrame(be_rows, columns=be_columns)
        html_be = _merge_particulars_header(df_be.to_html(index=False))
        st.markdown(f'<div class="backend-table">{html_be}</div>', unsafe_allow_html=True)
        # st.markdown(f'<div class="backend-table">{table_to_html(df_be)}</div>', unsafe_allow_html=True)
    else:  # Assumptions
        used = st.session_state.get("np_last_assumptions") or load_assumptions()
        st.json(used)


# ---------------------------------------------------------------------------
# Assumption editor widget
# ---------------------------------------------------------------------------

def _fmt_assumption_val(v):
    """Format assumption value for display: keep integers without decimal."""
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:g}"
    return str(v)


def _render_assumption_editor(assumptions: dict, key_prefix: str) -> dict:
    """Editable table for global + per-country assumptions. Returns updated dict."""
    updated = copy.deepcopy(assumptions)

    tabs = st.tabs(["Global", "Country"])
    with tabs[0]:
        globals_ = {k: v for k, v in assumptions.items() if k != "Country Assumptions"}
        # Convert values to strings for left-aligned display
        df = pd.DataFrame(
            [(k, _fmt_assumption_val(v)) for k, v in globals_.items()],
            columns=["Assumption", "Value"]
        )
        edited = st.data_editor(
            df,
            hide_index=True,
            key=f"{key_prefix}_global_editor",
            use_container_width=True,
            column_config={
                "Assumption": st.column_config.TextColumn("Assumption", disabled=True),
                "Value": st.column_config.TextColumn("Value"),
            },
        )
        for _, row in edited.iterrows():
            try:
                updated[row["Assumption"]] = float(row["Value"])
            except (TypeError, ValueError):
                updated[row["Assumption"]] = row["Value"]

    with tabs[1]:
        countries = list(assumptions["Country Assumptions"].keys())
        selected = st.selectbox("Country", countries, key=f"{key_prefix}_country_sel")
        c_dict = assumptions["Country Assumptions"][selected]
        # Convert values to strings for left-aligned display
        df_c = pd.DataFrame(
            [(k, _fmt_assumption_val(v)) for k, v in c_dict.items()],
            columns=["Assumption", "Value"]
        )
        edited_c = st.data_editor(
            df_c,
            hide_index=True,
            key=f"{key_prefix}_country_editor",
            use_container_width=True,
            column_config={
                "Assumption": st.column_config.TextColumn("Assumption", disabled=True),
                "Value": st.column_config.TextColumn("Value"),
            },
        )
        for _, row in edited_c.iterrows():
            v = row["Value"]
            if v is None or (isinstance(v, str) and not v.strip()):
                updated["Country Assumptions"][selected][row["Assumption"]] = None
            else:
                try:
                    updated["Country Assumptions"][selected][row["Assumption"]] = float(v)
                except (TypeError, ValueError):
                    updated["Country Assumptions"][selected][row["Assumption"]] = v

    return updated


# ---------------------------------------------------------------------------
# Admin: Edit assumptions permanently
# ---------------------------------------------------------------------------

def render_admin_assumptions():
    # st.markdown('<div class="eyebrow">ADMIN · GOVERNANCE</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Default Assumptions</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-sub">These values are used by every business user\'s '
        'default (saveable) calculation. Overriding them here changes the standard '
        'model for the entire team.</p>',
        unsafe_allow_html=True,
    )

    current = load_assumptions()
    if "admin_working" not in st.session_state:
        st.session_state.admin_working = copy.deepcopy(current)

    st.session_state.admin_working = _render_assumption_editor(
        st.session_state.admin_working, key_prefix="Administrator"
    )

    st.markdown('<div class="section-title">Save changes</div>', unsafe_allow_html=True)
    note = st.text_input(
        "",
        key="admin_change_note",
        placeholder="Change note (optional — will be recorded in the audit log)",
    )
    # c1, c2, c3 = st.columns([1, 1, 3])
    # with c1:
    #     if st.button("💾  Save as default", type="primary", use_container_width=True,
    #                  key="admin_save_assumptions"):
    #         actor = st.session_state.user["email"]
    #         changes = save_assumptions(
    #             st.session_state.admin_working, actor_email=actor, note=note
    #         )
    #         if changes:
    #             st.success(f"Saved. {len(changes)} change(s) recorded in the audit log.")
    #             st.session_state.pop("admin_change_note", None)
    #         else:
    #             st.info("No changes detected — nothing was saved.")
    # with c2:
    #     if st.button("↻  Discard edits", use_container_width=True, key="admin_discard"):
    #         st.session_state.admin_working = copy.deepcopy(load_assumptions())
    #         st.rerun()
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("💾  Save as default", type="primary", use_container_width=True,
                     key="admin_save_assumptions"):
            actor = st.session_state.user["email"]
            changes = save_assumptions(
                st.session_state.admin_working, actor_email=actor, note=note
            )
            if changes:
                st.success(f"Saved. {len(changes)} change(s) recorded in the audit log.")
                st.session_state.pop("admin_change_note", None)
            else:
                st.info("No changes detected — nothing was saved.")
    with c2:
        if st.button("↻  Discard edits", use_container_width=True, key="admin_discard"):
            st.session_state.admin_working = copy.deepcopy(load_assumptions())
            st.rerun()



    # --- Audit log
    st.markdown('<div class="section-title">Audit log</div>', unsafe_allow_html=True)
    log = list(reversed(load_audit_log()))  # newest first
    if not log:
        st.caption("No changes recorded yet.")
        return

    for entry in log[:50]:
        ts = format_timestamp(entry.get("timestamp", ""))
        actor = entry.get("actor", "?")
        note_txt = entry.get("note") or ""
        n_ch = entry.get("num_changes", len(entry.get("changes", [])))
        with st.expander(
            f"{ts}  •  {actor}  •  {n_ch} change(s)"
            + (f"  •  “{note_txt}”" if note_txt else "")
        ):
            df = pd.DataFrame(entry.get("changes", []))
            if not df.empty:
                st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Admin: Access Control (allowlist)
# ---------------------------------------------------------------------------

def render_access_control():
    # st.markdown('<div class="eyebrow">ADMIN · ACCESS CONTROL</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Access Control</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-sub">Only emails on this allowlist can sign in. When Carrier SSO '
        'is wired in later, the SSO callback will use this exact same list — pre-add users '
        'and their role here and they will be auto-provisioned on first SSO login.</p>',
        unsafe_allow_html=True,
    )

    users = load_users()
    me = st.session_state.user["email"].lower()

    # --- Current allowlist
    st.markdown('<div class="section-title">Authorized Users</div>', unsafe_allow_html=True)
    df = pd.DataFrame([
        {
            "Email": u["email"],
            "Name": u.get("name", ""),
            "Role": u.get("role", ""),
            "Active": "Yes" if u.get("is_active", True) else "No",
            "SSO Ready": "Yes" if u.get("sso_ready", False) else "No",
            "Created": format_timestamp(u.get("created_at", "")),
            "Last SSO Login": format_timestamp(u.get("last_sso_login", "")),
        }
        for u in users
    ])

    st.markdown(f'<div class="auth-users-table">{df.to_html(index=False, classes="users-table")}</div>',unsafe_allow_html=True)
    # st.dataframe(df, hide_index=True, use_container_width=True)

    # --- Add user
    # --- Add user
    st.markdown('<div class="section-title">Grant USER Access</div>', unsafe_allow_html=True)
    with st.form("grant_access_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1.5, 1.3, 0.9])
        with c1:
            n_name = st.text_input("Full name")
            
        with c2:
            n_email = st.text_input("Email", placeholder="user@carrier.com")
        with c3:
            n_role = st.selectbox("Role", ["Business", "Administrator"], index=0, help="Business users can run and save calculations. Admins can also edit assumptions and manage users.")
        if st.form_submit_button("＋ Grant Access", type="primary", use_container_width=True):
            ok, msg = create_user(n_email, n_name, "Carrier@123" ,n_role)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()

    # # --- Manage existing users
    if not users:
        return
    st.markdown('<div class="section-title">Manage Users</div>', unsafe_allow_html=True)
    if "show_edit_user" not in st.session_state:
        st.session_state.show_edit_user = False
    with st.container(border=True):
        # Row 1
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            target = st.selectbox(
                "Select User",
                [u["name"] for u in users],
                key="ac_target"
            )
        target_user = next(
            (u for u in users if u["name"] == target),
            None
        )

        if target_user:

            with c2:
                st.text_input(
                    "Email",
                    value=target_user.get("email", ""),
                    disabled=True
                )

            with c3:
                st.text_input(
                    "Role",
                    value=target_user.get("role", ""),
                    disabled=True
                )

            # Row 2
            d1, d2 = st.columns([1, 1])

            with d1:
                if st.button(
                    "Update User Details",
                    use_container_width=True,
                    key="update_user_btn"
                ):
                    st.session_state.show_edit_user = True

            with d2:
                if st.button(
                    "Revoke User",
                    use_container_width=True,
                    key="revoke_user_btn"
                ):
                    ok, msg = delete_user(target_user["name"])
                    (st.success if ok else st.error)(msg)

                    if ok:
                        st.rerun()

            if st.session_state.show_edit_user:

                e1, e2, e3 = st.columns([1, 1, 1])

                with e1:
                    st.text_input(
                        "Edit Name",
                        value="",
                        key="edit_name"
                    )

                with e2:
                    st.text_input(
                        "Edit Email",
                        value="",
                        key="edit_email"
                    )

                with e3:
                    st.selectbox(
                        "Edit Role",
                        ["Business", "Administrator"],
                        index=0 if target_user.get("role") == "Business" else 1,
                        key="edit_role"
                    )

                if st.button("Save User",use_container_width=True,key="save_user_btn"):

                    users = load_users()
                    for u in users:
                        if u["email"] == target_user["email"]:

                            u["name"] = st.session_state.edit_name
                            u["email"] = st.session_state.edit_email
                            u["role"] = st.session_state.edit_role

                            break

                    with open(USERS_FILE, "w") as f:
                        json.dump(users, f, indent=2)

                    st.success("User updated successfully.")
                    st.rerun()



    st.caption(
        "ⓘ Delete is intentionally omitted — deactivating a user preserves the audit trail "
        "and saved projects. Access can be restored at any time."
    )
   