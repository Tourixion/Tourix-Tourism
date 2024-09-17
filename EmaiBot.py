import imaplib
import email
from email.header import decode_header
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# Email handling functions
def connect_to_inbox(email_address, password, imap_server="imap.gmail.com"):
    imap = imaplib.IMAP4_SSL(imap_server)
    imap.login(email_address, password)
    return imap

def get_latest_emails(imap, num_emails=5):
    imap.select("INBOX")
    _, message_numbers = imap.search(None, "ALL")
    latest_emails = message_numbers[0].split()[-num_emails:]
    
    emails = []
    for num in latest_emails:
        _, msg = imap.fetch(num, "(RFC822)")
        emails.append(email.message_from_bytes(msg[0][1]))
    
    return emails

def parse_email_content(email_message):
    subject = decode_header(email_message["Subject"])[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    body = ""
    if email_message.is_multipart():
        for part in email_message.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode()
    else:
        body = email_message.get_payload(decode=True).decode()
    
    return subject, body

def parse_reservation_request(email_body):
    patterns = {
        'check_in': r'Check-in:\s*(\d{4}-\d{2}-\d{2})',
        'check_out': r'Check-out:\s*(\d{4}-\d{2}-\d{2})',
        'adults': r'Adults:\s*(\d+)',
        'children': r'Children:\s*(\d+)',
        'room_type': r'Room type:\s*(.+)'
    }
    
    reservation_info = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, email_body)
        if match:
            reservation_info[key] = match.group(1)
    
    for date_key in ['check_in', 'check_out']:
        if date_key in reservation_info:
            reservation_info[date_key] = datetime.strptime(reservation_info[date_key], '%Y-%m-%d')
    
    for num_key in ['adults', 'children']:
        if num_key in reservation_info:
            reservation_info[num_key] = int(reservation_info[num_key])
    
    return reservation_info

# Scraping function
def scrape_thekokoon_availability(check_in, check_out, adults=2, children=0):
    url = "https://thekokoon.reserve-online.net/"
    
    params = {
        "checkin": check_in.strftime("%d/%m/%Y"),
        "checkout": check_out.strftime("%d/%m/%Y"),
        "adults": adults,
        "children": children
    }
    
    response = requests.get(url, params=params)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    availability_data = []
    room_containers = soup.find_all('div', class_='room-container')  # Adjust class name as needed
    
    for room in room_containers:
        room_type = room.find('h2', class_='room-type').text.strip()
        price = room.find('span', class_='price').text.strip()
        availability = room.find('span', class_='availability').text.strip()
        
        availability_data.append({
            "room_type": room_type,
            "price": price,
            "availability": availability
        })
    
    return availability_data

# Availability checking function
def check_availability(reservation_info):
    availability_data = scrape_thekokoon_availability(
        check_in=reservation_info['check_in'],
        check_out=reservation_info['check_out'],
        adults=reservation_info['adults'],
        children=reservation_info.get('children', 0)
    )
    
    if 'room_type' in reservation_info:
        availability_data = [room for room in availability_data if room['room_type'].lower() == reservation_info['room_type'].lower()]
    
    return availability_data

# Email sending function
def send_availability_email(to_address, reservation_info, availability_data):
    sender_email = os.environ['EMAIL_ADDRESS']
    sender_password = os.environ['EMAIL_PASSWORD']

    subject = f"Availability for {reservation_info['check_in'].strftime('%Y-%m-%d')} to {reservation_info['check_out'].strftime('%Y-%m-%d')}"
    
    body = f"Dear Guest,\n\nHere's the availability for your requested dates:\n\n"
    for room in availability_data:
        body += f"Room Type: {room['room_type']}\n"
        body += f"Price: {room['price']}\n"
        body += f"Availability: {room['availability']}\n\n"
    
    body += "Thank you for your interest in THEKOKOON. Please let us know if you have any questions.\n\nBest regards,\nTHEKOKOON Team"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = to_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)

# Main function to be called by GitHub Actions
def main():
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']

    imap = connect_to_inbox(email_address, password)
    emails = get_latest_emails(imap)
    
    for email_message in emails:
        subject, body = parse_email_content(email_message)
        reservation_info = parse_reservation_request(body)
        
        if reservation_info:  # If it's a valid reservation request
            availability_data = check_availability(reservation_info)
            send_availability_email(email_message["From"], reservation_info, availability_data)
    
    imap.logout()

if __name__ == "__main__":
    main()
