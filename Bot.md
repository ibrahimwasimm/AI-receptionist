# Dental Clinic AI Bot — Build Instructions

---

## Your Confirmed Stack

- WhatsApp Cloud API — messaging (already tested)
- Claude API (Anthropic) — AI brain
- Google Calendar API — appointment scheduling
- Supabase — patient database (already set up)
- FastAPI (Python) — backend server

---

## What Version 1 Does

Receives a WhatsApp message from a patient, looks up their record in Supabase,
checks open slots on Google Calendar, replies naturally via Claude, and books
the appointment directly into Google Calendar.

---

## Project Files to Create

You need exactly these files in your project folder:

- main.py — FastAPI entry point, registers the two webhook routes
- database.py — Supabase connection and patient lookup function
- gcal.py — Google Calendar: check free slots and create booking events
- agent.py — Claude logic: builds the prompt, calls the API, parses the reply
- whatsapp.py — Receives incoming WhatsApp messages and sends replies
- run_auth.py — One-time script to authorize Google Calendar access
- .env — All your secret keys, never committed to git
- .gitignore — Excludes .env, token.json, credentials.json from git
- requirements.txt — All Python packages

---

## Step 1 — Python Environment

Create a virtual environment in your project folder and activate it.
Then install all packages from requirements.txt using pip.

Packages you need:
fastapi, uvicorn, python-dotenv, anthropic, httpx, supabase,
google-auth, google-auth-oauthlib, google-api-python-client

---

## Step 2 — Fill in Your .env File

You need these variables:

- ANTHROPIC_API_KEY — from console.anthropic.com
- SUPABASE_URL — from your Supabase project Settings → API → Project URL
- SUPABASE_KEY — from Supabase Settings → API → anon public key
- WHATSAPP_TOKEN — from Meta for Developers → your app → WhatsApp → API Setup → Access Token
- WHATSAPP_PHONE_ID — from the same page, Phone Number ID field
- VERIFY_TOKEN — make up any word yourself, you will type this same word in Meta dashboard later
- CLINIC_NAME — your clinic name as you want the bot to say it
- TIMEZONE — Asia/Karachi

---

## Step 3 — Check Your Supabase Patient Table

Since your table already exists, confirm it has these columns before proceeding:

- id — primary key
- name — text
- phone — text, must be unique
- last_proc — text, nullable (stores last dental procedure)
- notes — text, nullable
- created_at — timestamp

One critical thing: WhatsApp sends phone numbers without the plus sign.
For example 923001234567 not +923001234567.
Make sure all phone numbers in your Supabase table are stored the same way,
otherwise the patient lookup will fail silently.

---

## Step 4 — Google Calendar Authorization

Go to console.cloud.google.com and create a new project.
Enable the Google Calendar API under APIs and Services.
Set up the OAuth consent screen as External and add your own Gmail as a test user.
Create an OAuth Client ID with application type Desktop App.
Download the JSON file and rename it to credentials.json.
Place it in your project folder.

Now run run_auth.py once from your terminal.
A browser window will open — log in with your own Google account and approve access.
This generates token.json automatically. You do not need to run this again
unless the token expires.

Before testing, manually add a few fake events to your Google Calendar
over the next few days. This simulates a partially booked clinic schedule
so you can verify the bot correctly skips those times.

---

## Step 5 — Understanding How Each File Works

**database.py**
Connects to Supabase using your URL and key from .env.
Contains one function that takes a phone number and returns the matching
patient record from your patients table. Returns None if not found.

**gcal.py**
Contains two functions.
First function checks your Google Calendar for free slots over the next 7 days
during clinic hours (9am to 5pm) and returns up to 10 available times as plain text.
Second function creates a calendar event when a booking is confirmed,
using the patient name and phone in the event description.

**agent.py**
Contains the core Claude logic.
Calls database.py to get the patient record.
Calls gcal.py to get open slots.
Builds a system prompt that includes the patient context and available slots.
Sends the patient message to Claude and gets a reply.
Scans the reply for a hidden booking tag that Claude adds when confirming.
If found, calls gcal.py to create the event, then removes the tag before
sending the reply to the patient.

**whatsapp.py**
Contains two route handlers.
First handles the GET verification request that Meta sends once when you
set up the webhook — it confirms your server is real.
Second handles POST requests that Meta sends every time a patient messages.
It extracts the phone number and message text, passes them to agent.py,
then sends Claude's reply back to the patient via the WhatsApp Cloud API.

**main.py**
Starts the FastAPI app and registers both webhook routes from whatsapp.py.
Both routes use the same path /webhook — GET for verification, POST for messages.

---

## Step 6 — How the Booking Tag Works

Claude never touches your database or calendar directly.
Here is the logic behind the scenes:

When Claude decides to confirm a booking it adds a hidden tag at the end
of its reply in this format: BOOK:2025-04-20:10:00

Your agent.py scans every reply for this tag using a simple pattern match.
If found it extracts the date and time, calls the calendar booking function,
then strips the tag so the patient never sees it.

If the booking fails for any reason, the bot tells the patient that slot
was just taken and asks them to pick another time.

---

## Step 7 — Run Locally

Start your server with uvicorn on port 8000.
Open a second terminal and start ngrok pointed at port 8000.
Copy the ngrok HTTPS URL — you will need it in the next step.

---

## Step 8 — Connect WhatsApp Webhook in Meta Dashboard

Go to Meta for Developers and open your app.
Go to WhatsApp → Configuration → Webhook → Edit.
Paste your ngrok URL followed by /webhook as the Callback URL.
Type the same VERIFY_TOKEN you put in your .env file.
Click Verify and Save.
You should see a verification success message and your terminal will log it.
Then subscribe to the messages webhook field.

---

## Step 9 — Add a Test Patient in Supabase

Go to your Supabase Table Editor and insert one row into the patients table.
Use your own name and your own WhatsApp number as the phone.
Remember no plus sign on the phone number.
Add a fake last procedure like Cleaning for testing.

---

## Step 10 — Test the Full Flow

Send a WhatsApp message to your test number saying you want to book an appointment.
The bot should reply with available slots pulled from your Google Calendar.
Reply choosing a specific slot.
The bot should confirm and a new event should appear on your Google Calendar instantly.

---

## Common Problems and Fixes

Webhook verification fails — your VERIFY_TOKEN in .env does not exactly match
what you typed in the Meta dashboard. They must be identical.

Patient not found — phone number in Supabase has a plus sign but WhatsApp sends
it without one, or vice versa. Fix the format in your Supabase table.

No slots returned — either your Google Calendar is completely empty for the next
7 days, or your clinic hours in gcal.py need adjusting.

token.json not found — you have not run run_auth.py yet.

Token expired — delete token.json and run run_auth.py again.

ngrok URL changed — every time you restart ngrok you get a new URL.
Update the webhook URL in Meta dashboard each time.

Meta keeps retrying the webhook — your /webhook POST endpoint must always
return a 200 response. If your server crashes Meta will keep sending the same
message repeatedly.

---

## Customization Notes

To change clinic hours edit the slot generation loop in gcal.py.
Default is 9am to 5pm, one hour per slot.

To change how many slots Claude sees at once, change the limit at the end
of the get_open_slots function. Default is 10.

To change the bot's tone or how it handles conversations, edit the system
prompt inside the build_system_prompt function in agent.py.

---

## Phase 2 — Switching to Brother's Account Later

When your testing is complete and everything works, only four things change.

First, get new credentials.json from a Google Cloud project under your brother's Gmail.
Delete your token.json. Run run_auth.py again and log in with his Gmail this time.
The new token.json will point to his calendar.

Second, register the clinic's real WhatsApp Business number in Meta for Developers.
Update WHATSAPP_TOKEN and WHATSAPP_PHONE_ID in .env with the new values.

Third, update CLINIC_NAME in .env to the real clinic name.

Fourth, add real patients to the Supabase patients table.

Every Python file stays exactly the same. Nothing else changes.