import imaplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
from dateutil import parser as date_parser
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import socket
import sys

def connect_to_imap(email_address, password, imap_server, imap_port=993):
    print(f"Attempting to connect to IMAP server: {imap_server} on port {imap_port}")
    try:
        # First, try to resolve the hostname
        try:
            ip_address = socket.gethostbyname(imap_server)
            print(f"Resolved {imap_server} to IP: {ip_address}")
        except socket.gaierror as e:
            print(f"Failed to resolve hostname: {imap_server}. Error: {str(e)}")
            raise

        # Now try to establish the connection
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        print("SSL connection established")
        
        imap.login(email_address, password)
        print("Successfully logged in to IMAP server")
        return imap
    except imaplib.IMAP4.error as e:
        print(f"IMAP4 error: {str(e)}")
    except socket.error as e:
        print(f"Socket error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
    raise

def get_email_content(msg):
    subject = decode_header(msg["Subject"])[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode()
    else:
        return msg.get_payload(decode=True).decode()

def parse_reservation_request(email_body):
    # ... (keep the existing parse_reservation_request function) ...

def is_greek(text):
    return bool(re.search(r'[\u0370-\u03FF]', text))

def scrape_thekokoon_availability(check_in, check_out, adults, children):
    # ... (keep the existing scrape_thekokoon_availability function) ...

def send_email_via_imap(imap, to_address, subject, body):
    message = MIMEMultipart()
    message["From"] = os.environ['EMAIL_ADDRESS']
    message["To"] = to_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    imap.append('Sent', '', imaplib.Time2Internaldate(time.time()), message.as_string().encode('utf-8'))

def send_autoresponse(imap, to_address, reservation_info, availability_data, is_greek_email):
    # ... (keep the existing send_autoresponse function) ...

def send_error_notification(imap, original_email, parse_result):
    # ... (keep the existing send_error_notification function) ...

def process_email(imap, email_body, sender_address):
    # ... (keep the existing process_email function) ...

def main():
    print("Starting email processor script")
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']
    imap_server = os.environ['IMAP_SERVER']
    imap_port = int(os.environ.get('IMAP_PORT', 993))

    print(f"Email Address: {email_address}")
    print(f"IMAP Server: {imap_server}")
    print(f"IMAP Port: {imap_port}")

    try:
        imap = connect_to_imap(email_address, password, imap_server, imap_port)
        imap.select("INBOX")

        _, message_numbers = imap.search(None, "UNSEEN")
        for num in message_numbers[0].split():
            _, msg = imap.fetch(num, "(RFC822)")
            email_msg = email.message_from_bytes(msg[0][1])
            
            sender_address = email.utils.parseaddr(email_msg['From'])[1]
            email_body = get_email_content(email_msg)
            
            process_email(imap, email_body, sender_address)

        imap.logout()
        print("Email processing completed successfully")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
