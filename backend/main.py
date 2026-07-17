from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# Allow requests from other origins (CORS configuration)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Define the data structure expected from the HTML contact form
class ContactForm(BaseModel):
    name: str
    business_name: str
    email: str
    phone: str
    message: str

# 2. Create the POST endpoint to receive data
@app.post("/api/contact")
async def submit_contact_form(form_data: ContactForm):
    # 3. Print the incoming data to the server console (VS Code terminal)
    print("\n=== NEW CONTACT FORM SUBMISSION ===")
    print(f"Name: {form_data.name}")
    print(f"Business: {form_data.business_name}")
    print(f"Email: {form_data.email}")
    print(f"Phone: {form_data.phone}")
    print(f"Message: {form_data.message}")
    print("===================================\n")
    
    # 4. Return a successful JSON response to the frontend
    return {"status": "success", "message": "Form submitted successfully!"}