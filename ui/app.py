"""Streamlit UI for ExpenseFlow: submit expenses, list them, and view spending insights."""

import os

import httpx
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

STATUS_LABELS = {
    "pending": "\U0001F7E1 Pending",
    "approved": "\U0001F7E2 Approved",
    "rejected": "\U0001F534 Rejected",
}


def _get(path: str) -> httpx.Response | None:
    """GET a path from the API, returning None (and showing a friendly error) on connection failure."""
    try:
        return httpx.get(f"{API_BASE}{path}", timeout=10.0)
    except httpx.RequestError:
        st.error(f"Could not reach the ExpenseFlow API at {API_BASE}. Is the server running?")
        return None


def _post(path: str, payload: dict) -> httpx.Response | None:
    """POST a JSON payload to the API, returning None (and showing a friendly error) on connection failure."""
    try:
        return httpx.post(f"{API_BASE}{path}", json=payload, timeout=10.0)
    except httpx.RequestError:
        st.error(f"Could not reach the ExpenseFlow API at {API_BASE}. Is the server running?")
        return None


def _patch(path: str, payload: dict) -> httpx.Response | None:
    """PATCH a JSON payload to the API, returning None (and showing a friendly error) on connection failure."""
    try:
        return httpx.patch(f"{API_BASE}{path}", json=payload, timeout=10.0)
    except httpx.RequestError:
        st.error(f"Could not reach the ExpenseFlow API at {API_BASE}. Is the server running?")
        return None


def _format_minor(amount_minor: int, currency: str) -> str:
    """Format an integer minor-unit amount as a two-decimal rupee-style string for display."""
    symbol = "₹" if currency == "INR" else f"{currency} "
    return f"{symbol}{amount_minor / 100:,.2f}"


st.set_page_config(page_title="ExpenseFlow", page_icon="\U0001F4B8")
st.title("ExpenseFlow")
st.caption("Submit expenses, track their status, and see spending insights.")

if "submitting" not in st.session_state:
    st.session_state.submitting = False
if "pending_payload" not in st.session_state:
    st.session_state.pending_payload = None

st.header("Submit a new expense")
with st.form("new_expense_form", clear_on_submit=True):
    description = st.text_input("Description")
    amount = st.number_input("Amount", min_value=0.01, step=0.01, format="%.2f")
    currency = st.text_input("Currency", value="INR", max_chars=3)
    category = st.text_input("Category")
    submitted_by = st.text_input("Submitted by")
    submitted = st.form_submit_button(
        "Submitting..." if st.session_state.submitting else "Submit expense",
        disabled=st.session_state.submitting,
    )

if submitted:
    st.session_state.pending_payload = {
        "description": description,
        "amount_minor": round(amount * 100),
        "currency": currency,
        "category": category,
        "submitted_by": submitted_by,
    }
    st.session_state.submitting = True
    st.rerun()

if st.session_state.submitting:
    response = _post("/expenses", st.session_state.pending_payload)
    st.session_state.submitting = False
    st.session_state.pending_payload = None
    if response is not None:
        if response.status_code == 201:
            st.success("Expense submitted.")
        else:
            st.error(f"Failed to submit expense ({response.status_code}): {response.text}")
    st.rerun()

if "deciding" not in st.session_state:
    st.session_state.deciding = False
if "pending_decision" not in st.session_state:
    st.session_state.pending_decision = None

expenses_response = _get("/expenses")
expenses = []
if expenses_response is not None:
    if expenses_response.status_code == 200:
        expenses = expenses_response.json()
    else:
        st.error(f"Failed to load expenses ({expenses_response.status_code}): {expenses_response.text}")

if st.session_state.deciding:
    decision = st.session_state.pending_decision
    decision_response = _patch(
        f"/expenses/{decision['expense_id']}/status",
        {
            "status": decision["status"],
            "decided_by": decision["decided_by"],
            "comment": decision["comment"],
        },
    )
    st.session_state.deciding = False
    st.session_state.pending_decision = None
    if decision_response is not None:
        if decision_response.status_code == 200:
            st.success(f"Expense {decision['status']}.")
        else:
            st.error(f"Failed to update expense ({decision_response.status_code}): {decision_response.text}")
    st.rerun()

st.header("Existing expenses")
if expenses:
    COLUMN_WIDTHS = [0.5, 1.6, 1, 1, 1, 1.1, 1.1, 1.2, 1, 1.2, 2]
    headers = [
        "ID", "Description", "Category", "Amount", "Amount (base)",
        "Status", "Submitted by", "Created at", "Decided by", "Decided at",
        "Comment / Action",
    ]
    for col, label in zip(st.columns(COLUMN_WIDTHS), headers):
        col.markdown(f"**{label}**")
    st.divider()

    for expense in expenses:
        row = st.columns(COLUMN_WIDTHS)
        row[0].write(expense["id"])
        row[1].write(expense["description"])
        row[2].write(expense["category"])
        row[3].write(_format_minor(expense["amount_minor"], expense["currency"]))
        row[4].write(_format_minor(expense["amount_base_minor"], "INR"))
        row[5].write(STATUS_LABELS.get(expense["status"], expense["status"].title()))
        row[6].write(expense["submitted_by"])
        row[7].write(expense["created_at"])
        row[8].write(expense["decided_by"] or "—")
        row[9].write(expense["decided_at"] or "—")

        action_col = row[10]
        if expense["status"] == "pending":
            decided_by = action_col.text_input(
                "Decided by",
                key=f"decided_by_{expense['id']}",
                label_visibility="collapsed",
                placeholder="Decided by (your name or email)",
            )
            comment = action_col.text_area(
                "Comment",
                key=f"comment_{expense['id']}",
                height=68,
                label_visibility="collapsed",
                placeholder="Comment",
            )
            approve_clicked = action_col.button(
                "Approve",
                key=f"approve_{expense['id']}",
                disabled=st.session_state.deciding,
                use_container_width=True,
            )
            reject_clicked = action_col.button(
                "Reject",
                key=f"reject_{expense['id']}",
                disabled=st.session_state.deciding,
                use_container_width=True,
            )
            if approve_clicked or reject_clicked:
                if not decided_by.strip():
                    st.error("Enter who is deciding before approving or rejecting.")
                else:
                    st.session_state.pending_decision = {
                        "expense_id": expense["id"],
                        "status": "approved" if approve_clicked else "rejected",
                        "decided_by": decided_by,
                        "comment": comment or None,
                    }
                    st.session_state.deciding = True
                    st.rerun()
        else:
            action_col.write(expense["comment"] or "—")
        st.divider()
else:
    st.info("No expenses yet.")

st.header("Spending insights")
if st.button("Generate insights"):
    insights_response = _get("/reports/insights")
    if insights_response is not None:
        if insights_response.status_code == 200:
            insight = insights_response.json().get("insight", {})
            summary = insight.get("summary", "")
            bullets = insight.get("bullets", [])
            st.write(summary)
            for bullet in bullets:
                st.markdown(f"- {bullet}")
        else:
            st.error(f"Failed to generate insights ({insights_response.status_code}): {insights_response.text}")
