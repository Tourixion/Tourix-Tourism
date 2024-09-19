import imaplib
import smtplib
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
import ssl
import sys
import time
from playwright.sync_api import sync_playwright

def connect_to_imap(email_address, password, imap_server, imap_port=993):
    print(f"Attempting to connect to IMAP server: {imap_server} on port {imap_port}")
    
    try:
        # Create SSL context
        context = ssl.create_default_context()

        # Create IMAP4 client
        print("Creating IMAP4_SSL client")
        imap = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=context)
        
        print("Attempting to log in")
        imap.login(email_address, password)
        print("Successfully logged in to IMAP server")
        return imap
    except socket.gaierror as e:
        print(f"Address-related error connecting to server: {e}")
    except socket.error as e:
        print(f"Connection error: {e}")
    except ssl.SSLError as e:
        print(f"SSL error: {e}")
    except imaplib.IMAP4.error as e:
        print(f"IMAP4 error: {e}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
    raise

def debug_dns(hostname):
    print(f"Attempting to resolve {hostname}")
    try:
        ip_address = socket.gethostbyname(hostname)
        print(f"Successfully resolved {hostname} to {ip_address}")
    except socket.gaierror as e:
        print(f"Failed to resolve {hostname}. Error: {e}")
    
    try:
        print(f"Attempting to get address info for {hostname}")
        addr_info = socket.getaddrinfo(hostname, None)
        print(f"Address info for {hostname}: {addr_info}")
    except socket.gaierror as e:
        print(f"Failed to get address info for {hostname}. Error: {e}")

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
    email_body = email_body.lower()
    patterns = {
        'check_in': r'(?:check[ -]?in|arrival|from|άφιξη|από)[\s:]+(.+?)(?:\n|$)',
        'check_out': r'(?:check[ -]?out|departure|to|until|till|αναχώρηση|μέχρι)[\s:]+(.+?)(?:\n|$)',
        'adults': r'(?:adults?|persons?|people|guests?|ενήλικες|άτομα)[\s:]+(\d+)',
        'children': r'(?:children|kids|παιδιά)[\s:]+(\d+)',
        'room_type': r'(?:room|accommodation|δωμάτιο|κατάλυμα)[\s:]+(.+?)(?:\n|$)'
    }
    
    reservation_info = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, email_body)
        if match:
            reservation_info[key] = match.group(1).strip()
    
    month_mapping = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαϊ': 5, 'μαι': 5, 'ιουν': 6,
        'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12,
        'ιανουάριος': 1, 'φεβρουάριος': 2, 'μάρτιος': 3, 'απρίλιος': 4, 'μάιος': 5,
        'ιούνιος': 6, 'ιούλιος': 7, 'αύγουστος': 8, 'σεπτέμβριος': 9,
        'οκτώβριος': 10, 'νοέμβριος': 11, 'δεκέμβριος': 12
    }

    def parse_custom_date(date_string):
        components = re.findall(r'\b\w+\b', date_string)
        day = month = year = None
        
        for comp in components:
            if comp.isdigit():
                if len(comp) == 4:
                    year = int(comp)
                elif int(comp) <= 31:
                    day = int(comp)
            elif comp in month_mapping:
                month = month_mapping[comp]
        
        if year is None:
            year = datetime.now().year
            if month and day:
                if datetime(year, month, day) < datetime.now():
                    year += 1
        
        if day and month and year:
            return datetime(year, month, day).date()
        else:
            return date_parser.parse(date_string, fuzzy=True).date()

    for date_key in ['check_in', 'check_out']:
        if date_key in reservation_info:
            try:
                reservation_info[date_key] = parse_custom_date(reservation_info[date_key])
            except ValueError:
                del reservation_info[date_key]

    if 'check_in' in reservation_info and 'check_out' not in reservation_info:
        reservation_info['check_out'] = reservation_info['check_in'] + timedelta(days=1)

    for num_key in ['adults', 'children']:
        if num_key in reservation_info:
            reservation_info[num_key] = int(reservation_info[num_key])

    if 'adults' not in reservation_info:
        reservation_info['adults'] = 2

    return reservation_info

def is_greek(text):
    return bool(re.search(r'[\u0370-\u03FF]', text))

def scrape_thekokoon_availability(check_in, check_out, adults, children):
    url = "https://thekokoonvolos.reserve-online.net/"
    
    print(f"Attempting to scrape availability data from {url}")
    print(f"Parameters: Check-in: {check_in}, Check-out: {check_out}, Adults: {adults}, Children: {children}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(url)
            print(f"Navigated to {url}")
            
            # Fill in the form
            page.fill("#checkin", check_in.strftime("%d/%m/%Y"))
            page.fill("#checkout", check_out.strftime("%d/%m/%Y"))
            page.select_option("#adults", str(adults))
            page.select_option("#children", str(children))
            
            # Submit the form
            page.click("button[type='submit']")
            
            # Wait for results to load
            page.wait_for_selector(".room-item")
            
            # Extract data
            availability_data = []
            room_items = page.query_selector_all(".room-item")
            print(f"Found {len(room_items)} room items")
            
            for room in room_items:
                room_type = room.query_selector(".room-name").inner_text()
                price = room.query_selector(".price").inner_text()
                availability = "Available"  # Assuming it's available if listed
                
                availability_data.append({
                    "room_type": room_type,
                    "price": price,
                    "availability": availability
                })
                print(f"Scraped data for room: {room_type}")
            
            print(f"Scraped availability data: {availability_data}")
            return availability_data
        
        except Exception as e:
            print(f"Error scraping website: {e}")
            return None
        
        finally:
            browser.close()

def send_email(to_address, subject, body):
    smtp_server = "mail.kokoonvolos.gr"
    smtp_port = 465  # SSL port
    sender_email = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = to_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, password)
            server.send_message(message)
        print(f"Email sent successfully to {to_address}")
    except Exception as e:
        print(f"Failed to send email to {to_address}. Error: {str(e)}")
        raise

def send_autoresponse(imap, to_address, reservation_info, availability_data, is_greek_email):
    if is_greek_email:
        subject = "Απάντηση στο Αίτημα Κράτησης"
        body = f"""
        Αγαπητέ πελάτη,

        Σας ευχαριστούμε για το ενδιαφέρον σας στο Kokoon Volos. Έχουμε λάβει το αίτημά σας για κράτηση με τις ακόλουθες λεπτομέρειες:

        Ημερομηνία άφιξης: {reservation_info['check_in']}
        Ημερομηνία αναχώρησης: {reservation_info['check_out']}
        Αριθμός ενηλίκων: {reservation_info['adults']}
        Αριθμός παιδιών: {reservation_info.get('children', 'Δεν διευκρινίστηκε')}

        Με βάση το αίτημά σας, έχουμε τις ακόλουθες διαθέσιμες επιλογές:

        """
        for room in availability_data:
            body += f"""
            Τύπος δωματίου: {room['room_type']}
            Τιμή: {room['price']}
            Διαθεσιμότητα: {room['availability']}
            
            """
        
        body += """
        Παρακαλούμε σημειώστε ότι αυτές οι πληροφορίες βασίζονται στην τρέχουσα διαθεσιμότητα και μπορεί να αλλάξουν.

        Εάν επιθυμείτε να προχωρήσετε με την κράτηση ή έχετε περαιτέρω ερωτήσεις, παρακαλούμε μη διστάσετε να επικοινωνήσετε μαζί μας.

        Με εκτίμηση,
        Η ομάδα του Kokoon Volos
        """
    else:
        subject = "Response to Your Reservation Request"
        body = f"""
        Dear guest,

        Thank you for your interest in Kokoon Volos. We have received your reservation request with the following details:

        Check-in date: {reservation_info['check_in']}
        Check-out date: {reservation_info['check_out']}
        Number of adults: {reservation_info['adults']}
        Number of children: {reservation_info.get('children', 'Not specified')}

        Based on your request, we have the following available options:

        """
        for room in availability_data:
            body += f"""
            Room type: {room['room_type']}
            Price: {room['price']}
            Availability: {room['availability']}
            
            """
        
        body += """
        Please note that this information is based on current availability and may change.

        If you wish to proceed with the booking or have any further questions, please don't hesitate to contact us.

        Best regards,
        The Kokoon Volos Team
        """

    send_email(to_address, subject, body)
    
def send_error_notification(imap, original_email, parse_result):
    recipient_email = os.environ['ERROR_NOTIFICATION_EMAIL']
    subject = "Parsing Error: Reservation Request"
    body = f"""
    A reservation request email could not be parsed correctly.

    Original Email:
    {original_email}

    Parsed Result:
    {parse_result}

    Please review and process this request manually.
    """
    
    send_email(recipient_email, subject, body)
    
def process_email(imap, email_body, sender_address):
    print("Starting to process email")
    is_greek_email = is_greek(email_body)
    print(f"Email language: {'Greek' if is_greek_email else 'English'}")
    
    reservation_info = parse_reservation_request(email_body)
    print(f"Parsed reservation info: {reservation_info}")
    
    if 'check_in' in reservation_info and 'check_out' in reservation_info:
        print("Reservation dates found, proceeding to web scraping")
        
        try:
            availability_data = scrape_thekokoon_availability(
                reservation_info['check_in'],
                reservation_info['check_out'],
                reservation_info.get('adults', 2),
                reservation_info.get('children', 0)
            )
            print(f"Web scraping result: {availability_data}")
        
            if availability_data:
                print("Availability data found, sending detailed response")
                send_autoresponse(imap, sender_address, reservation_info, availability_data, is_greek_email)
            else:
                print("No availability data found, sending generic response")
                generic_subject = "Λήψη Αιτήματος Κράτησης" if is_greek_email else "Reservation Request Received"
                generic_body = ("Σας ευχαριστούμε για το αίτημα κράτησης. Θα επεξεργαστούμε το αίτημά σας και θα επικοινωνήσουμε σύντομα μαζί σας."
                                if is_greek_email else
                                "Thank you for your reservation request. We will process your request and get back to you shortly.")
                send_email(sender_address, generic_subject, generic_body)
        except Exception as e:
            print(f"Error during web scraping: {str(e)}")
            send_error_notification(imap, email_body, f"Web scraping failed: {str(e)}")
            generic_subject = "Λήψη Αιτήματος Κράτησης" if is_greek_email else "Reservation Request Received"
            generic_body = ("Σας ευχαριστούμε για το αίτημα κράτησης. Η ομάδα μας θα το εξετάσει και θα επικοινωνήσει σύντομα μαζί σας."
                            if is_greek_email else
                            "Thank you for your reservation request. Our team will review it and get back to you shortly.")
            send_email(sender_address, generic_subject, generic_body)
    else:
        print("Failed to parse reservation dates. Sending error notification.")
        send_error_notification(imap, email_body, reservation_info)
        generic_subject = "Λήψη Αιτήματος Κράτησης" if is_greek_email else "Reservation Request Received"
        generic_body = ("Σας ευχαριστούμε για το αίτημα κράτησης. Η ομάδα μας θα το εξετάσει και θα επικοινωνήσει σύντομα μαζί σας."
                        if is_greek_email else
                        "Thank you for your reservation request. Our team will review it and get back to you shortly.")
        send_email(sender_address, generic_subject, generic_body)

    print("Email processing completed")

def main():
    print("Starting email processor script")
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']
    imap_server = 'mail.kokoonvolos.gr'
    imap_port = 993

    print(f"Email Address: {email_address}")
    print(f"IMAP Server: {imap_server}")
    print(f"IMAP Port: {imap_port}")

    try:
        imap = connect_to_imap(email_address, password, imap_server, imap_port)
        imap.select("INBOX")

        _, message_numbers = imap.search(None, "UNSEEN")
        if not message_numbers[0]:
            print("No new messages found.")
        else:
            for num in message_numbers[0].split():
                print(f"Processing message number: {num}")
                _, msg = imap.fetch(num, "(RFC822)")
                email_msg = email.message_from_bytes(msg[0][1])
                
                sender_address = email.utils.parseaddr(email_msg['From'])[1]
                print(f"Sender: {sender_address}")
                
                email_body = get_email_content(email_msg)
                print("Email body retrieved")
                
                process_email(imap, email_body, sender_address)  # Updated this line
                print(f"Finished processing message number: {num}")

        imap.logout()
        print("Email processing completed successfully")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise

if __name__ == "__main__":
    main()
