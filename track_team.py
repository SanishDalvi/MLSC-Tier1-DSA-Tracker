import csv
from datetime import datetime, time
import email.message
import json
import os
import re
import smtplib
import urllib.request
from zoneinfo import ZoneInfo

MEMBERS_CSV = "members.csv"
SCHEDULE_CSV = "schedule.csv"
HISTORY_CSV = "daily_history.csv"
GRAPHQL_URL = "https://leetcode.com/graphql"

USER_DATA_QUERY = """
query getUserData($username: String!) {
  matchedUser(username: $username) {
    submitStats {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
  recentAcSubmissionList(username: $username, limit: 35) {
    title
    timestamp
  }
}
"""


def load_members_from_csv(filename):
  members = {}
  if not os.path.exists(filename):
    print(f"Error: {filename} not found.")
    return members

  with open(filename, mode="r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      name = row.get("Name", "").strip()
      handle = row.get("Handle", "").strip()
      email_addr = row.get("Email", "").strip()
      if name and handle:
        members[name] = {"handle": handle, "email": email_addr}
  return members


def generate_leetcode_link(problem_name):
  clean_title = (
      problem_name.replace("(revisit)", "")
      .replace("(Hard)", "")
      .strip()
      .lower()
  )
  clean_title = re.sub(r"[^\w\s-]", "", clean_title)
  slug = re.sub(r"[-\s]+", "-", clean_title).strip("-")
  return f"[{problem_name}](https://leetcode.com/problems/{slug}/)"


def load_schedule_from_csv(filename):
  schedule = {}
  if not os.path.exists(filename):
    return schedule

  with open(filename, mode="r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      date_key = row["Date"].strip()
      occasion = row["Occasion"].strip()
      problems_raw = row["Problems"].strip()

      if problems_raw.upper() == "HOLIDAY":
        schedule[date_key] = {"type": "holiday", "occasion": occasion}
      else:
        problems = [p.strip() for p in problems_raw.split(";") if p.strip()]
        schedule[date_key] = {
            "type": "practice",
            "occasion": occasion,
            "problems": problems,
        }
  return schedule


def fetch_leetcode_data(username):
  payload = json.dumps(
      {"query": USER_DATA_QUERY, "variables": {"username": username}}
  )
  req = urllib.request.Request(
      GRAPHQL_URL,
      data=payload.encode("utf-8"),
      headers={
          "Content-Type": "application/json",
          "User-Agent": "Mozilla/5.0",
          "Referer": "https://leetcode.com",
      },
  )
  try:
    with urllib.request.urlopen(req, timeout=10) as response:
      data = json.loads(response.read().decode())
      matched = data.get("data", {}).get("matchedUser")
      total_all_time = 0
      if matched and "submitStats" in matched:
        for item in matched["submitStats"]["acSubmissionNum"]:
          if item["difficulty"] == "All":
            total_all_time = item["count"]

      submissions = data.get("data", {}).get("recentAcSubmissionList", [])
      return total_all_time, submissions
  except Exception:
    return 0, []


def send_reminder_email(
    to_email, member_name, assigned_problems, occasion_name
):
  sender_email = os.environ.get("SENDER_EMAIL")
  sender_password = os.environ.get("SENDER_PASSWORD")

  if not sender_email or not sender_password or not to_email:
    return

  msg = email.message.EmailMessage()
  msg["Subject"] = (
      f"🚨 DSA Drive Reminder: 0 Problems Solved Today ({occasion_name})"
  )
  msg["From"] = sender_email
  msg["To"] = to_email

  problems_list = "\n".join([f"• {p}" for p in assigned_problems])
  msg.set_content(f"""Hi {member_name},

Our DSA drive tracker noticed that you haven't solved any problems yet today on LeetCode for {occasion_name}.

Today's Assigned Problems:
{problems_list}

Remember: Consistency is key! Aim to finish before midnight.

- MLSC DSA Drive Bot
""")

  try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
      server.login(sender_email, sender_password)
      server.send_message(msg)
      print(f"Sent reminder email to {member_name} ({to_email})")
  except Exception as e:
    print(f"Failed to send email to {to_email}: {e}")


def update_history_csv(target_date_str, occasion, daily_counts, members_list):
  headers = ["Date", "Occasion"] + members_list
  rows = []
  date_found = False

  if os.path.exists(HISTORY_CSV):
    with open(HISTORY_CSV, mode="r", encoding="utf-8") as f:
      reader = csv.DictReader(f)
      for r in reader:
        if r.get("Date") == target_date_str:
          date_found = True
          r["Occasion"] = occasion
          for name in members_list:
            r[name] = str(daily_counts.get(name, 0))
        rows.append(r)

  if not date_found:
    new_row = {"Date": target_date_str, "Occasion": occasion}
    for name in members_list:
      new_row[name] = str(daily_counts.get(name, 0))
    rows.append(new_row)

  with open(HISTORY_CSV, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    for r in rows:
      writer.writerow({h: r.get(h, "0") for h in headers})


# Load Members & Schedule from CSV files
members = load_members_from_csv(MEMBERS_CSV)
schedule = load_schedule_from_csv(SCHEDULE_CSV)

# IST Time Setup
ist_tz = ZoneInfo("Asia/Kolkata")
now_ist = datetime.now(ist_tz)
midnight_ist = datetime.combine(now_ist.date(), time.min, tzinfo=ist_tz)
midnight_epoch = int(midnight_ist.timestamp())

today_str = now_ist.strftime("%d-%m")
today_display = now_ist.strftime("%d %b %Y, %I:%M %p IST")

today_entry = schedule.get(today_str, None)
is_holiday = False
occasion_name = ""
assigned_problems = []

if today_entry is None or today_entry["type"] == "holiday":
  is_holiday = True
  occasion_name = today_entry["occasion"] if today_entry else "Rest Day"
else:
  occasion_name = today_entry["occasion"]
  assigned_problems = today_entry["problems"]

is_9pm_ist = now_ist.hour == 21

member_stats = []
daily_counts_for_csv = {}

for name, info in members.items():
  handle = info["handle"]
  member_email = info.get("email", "")
  total_all_time, submissions = fetch_leetcode_data(handle)

  solved_today_titles = set()
  for sub in submissions:
    sub_time = int(sub.get("timestamp", 0))
    if sub_time >= midnight_epoch and "title" in sub:
      solved_today_titles.add(sub["title"].strip().lower())

  total_solved_today = len(solved_today_titles)
  daily_counts_for_csv[name] = total_solved_today

  if not is_holiday and assigned_problems:
    assigned_match_count = 0
    for prob in assigned_problems:
      clean_prob = (
          prob.replace(" (revisit)", "")
          .replace(" (Hard)", "")
          .strip()
          .lower()
      )
      if clean_prob in solved_today_titles:
        assigned_match_count += 1

    total_assigned = len(assigned_problems)
    if assigned_match_count == total_assigned:
      status = f"✅ {assigned_match_count}/{total_assigned} (Complete)"
    elif assigned_match_count > 0:
      status = f"⚠️ {assigned_match_count}/{total_assigned} (Partial)"
    else:
      status = f"❌ 0/{total_assigned} (Pending)"

    if is_9pm_ist and total_solved_today == 0:
      send_reminder_email(member_email, name, assigned_problems, occasion_name)
  else:
    status = f"🌴 {occasion_name}"

  member_stats.append({
      "name": name,
      "handle": handle,
      "total_all_time": total_all_time,
      "total_today": total_solved_today,
      "today_status": status,
  })

# Record daily snapshot into history CSV
update_history_csv(
    today_str, occasion_name, daily_counts_for_csv, list(members.keys())
)

# Leaderboard construction
member_stats.sort(key=lambda x: x["total_all_time"], reverse=True)

leaderboard_rows = []
for rank, member in enumerate(member_stats, 1):
  profile_link = (
      f"[{member['handle']}](https://leetcode.com/{member['handle']})"
  )
  leaderboard_rows.append(
      f"| #{rank} | **{member['name']}** | {profile_link} |"
      f" {member['total_today']} | {member['today_status']} |"
      f" {member['total_all_time']} |"
  )

if is_holiday:
  schedule_header = (
      f"### 🌴 Rest / Holiday Day ({occasion_name})\nNo mandatory problems"
      " scheduled for today."
  )
else:
  formatted_links = [
      f"- {generate_leetcode_link(p)}" for p in assigned_problems
  ]
  schedule_header = (
      f"### 📅 Assigned Problems for {occasion_name} ({today_str}):\n"
      + "\n".join(formatted_links)
  )

readme_content = f"""# 🚀 MLSC Tier 2 DSA Tracker

> **Last Updated:** {today_display} (Auto-syncs every 2 hours)

{schedule_header}

---

### 🏆 Team Leaderboard
| Rank | Member | LeetCode Profile | Solved Today | Drive Status | Total All-Time Solved |
| :---: | :--- | :--- | :---: | :--- | :---: |
""" + "\n".join(leaderboard_rows)

with open("README.md", "w", encoding="utf-8") as f:
  f.write(readme_content)
