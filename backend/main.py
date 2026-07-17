from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "contacts.db"

def init_db():
    # Initialize database and create table if it doesn't exist
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            business_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class ContactForm(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    business_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr 
    phone: str = Field(..., pattern=r'^\+?1?\d{9,15}$') 
    message: str = Field(..., min_length=10, max_length=3000)

# Function to send email notifications
def send_email_notification(form_data: ContactForm):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not sender or not password:
        print("[-] Email credentials are not configured.")
        return

    # Format the email
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = f"New website inquiry from {form_data.business_name}"

    body = f"""
    A new inquiry has been submitted on the website!
    
    Name: {form_data.name}
    Business: {form_data.business_name}
    Email: {form_data.email}
    Phone: {form_data.phone}
    
    Message:
    {form_data.message}
    """
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        # Connect to the Gmail server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print("[+] Email notification sent successfully via Gmail!")
    except Exception as e:
        print(f"[-] Error sending email: {e}")

# Note the added background_tasks parameter
@app.post("/api/contact")
async def submit_contact_form(form_data: ContactForm, background_tasks: BackgroundTasks):
    
    # 1. Save to the SQLite database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO contacts (name, business_name, email, phone, message)
        VALUES (?, ?, ?, ?, ?)
    ''', (form_data.name, form_data.business_name, form_data.email, form_data.phone, form_data.message))
    conn.commit()
    conn.close()

    print(f"\n[+] New inquiry saved to DB from: {form_data.name}\n")
    
    # 2. Pass the email sending task to the background
    background_tasks.add_task(send_email_notification, form_data)
    
    return {"status": "success", "message": "Form submitted successfully"}