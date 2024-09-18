import imaplib
import email
from email.header import decode_header
import re
from dateutil import parser as date_parser
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import requests
from bs4 import BeautifulSoup

def connect_to_inbox(email_address, password, imap_server, imap_port=993):
    imap = imaplib.IMAP4_SSL(imap_server, imap_port)
    imap.login(email_address, password)
    return imap

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
    url = "https://thekokoon.reserve-online.net/"
    
    params = {
        "checkin": check_in.strftime("%d/%m/%Y"),
        "checkout": check_out.strftime("%d/%m/%Y"),
        "adults": adults,
        "children": children
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        availability_data = []
        room_containers = soup.find_all('div', class_='room-container')
        
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
    except requests.RequestException as e:
        print(f"Error scraping website: {e}")
        return None

def send_email(to_address, subject, body):
    sender_email = os.environ['EMAIL_ADDRESS']
    sender_password = os.environ['EMAIL_PASSWORD']
    smtp_server = os.environ['SMTP_SERVER']
    smtp_port = int(os.environ.get('SMTP_PORT', 587))

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = to_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)

def send_autoresponse(to_address, reservation_info, availability_data, is_greek_email):
    if is_greek_email:
        subject = "Λήψη Αιτήματος Κράτησης και Διαθεσιμότητα"
        body = f"""
        Αγαπητέ Πελάτη,

        Σας ευχαριστούμε για το αίτημα κράτησης. Έχουμε λάβει τις ακόλουθες λεπτομέρειες:

        Άφιξη: {reservation_info.get('check_in', 'Δεν διευκρινίστηκε')}
        Αναχώρηση: {reservation_info.get('check_out', 'Δεν διευκρινίστηκε')}
        Ενήλικες: {reservation_info.get('adults', 'Δεν διευκρινίστηκε')}
        Παιδιά: {reservation_info.get('children', 'Δεν διευκρινίστηκε')}

        Διαθεσιμότητα και τιμές για τις ζητούμενες ημερομηνίες:
        """
        for room in availability_data:
            body += f"\nΤύπος Δωματίου: {room['room_type']}"
            body += f"\nΤιμή: {room['price']}"
            body += f"\nΔιαθεσιμότητα: {room['availability']}\n"

        body += """
        Θα επεξεργαστούμε το αίτημά σας και θα επικοινωνήσουμε σύντομα μαζί σας με επιβεβαίωση και τυχόν πρόσθετες πληροφορίες.

        Εάν έχετε οποιεσδήποτε ερωτήσεις, μη διστάσετε να επικοινωνήσετε μαζί μας.

        Με εκτίμηση,
        Η Ομάδα Κρατήσεων
        """
    else:
        subject = "Reservation Request Received and Availability"
        body = f"""
        Dear Guest,

        Thank you for your reservation request. We have received the following details:

        Check-in: {reservation_info.get('check_in', 'Not specified')}
        Check-out: {reservation_info.get('check_out', 'Not specified')}
        Adults: {reservation_info.get('adults', 'Not specified')}
        Children: {reservation_info.get('children', 'Not specified')}

        Availability and pricing for the requested dates:
        """
        for room in availability_data:
            body += f"\nRoom Type: {room['room_type']}"
            body += f"\nPrice: {room['price']}"
            body += f"\nAvailability: {room['availability']}\n"

        body += """
        We will process your request and get back to you shortly with confirmation and any additional information.

        If you have any questions, please don't hesitate to contact us.

        Best regards,
        The Reservation Team
        """
    
    send_email(to_address, subject, body)

def send_error_notification(original_email, parse_result):
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

def process_email(email_body, sender_address):
    is_greek_email = is_greek(email_body)
    reservation_info = parse_reservation_request(email_body)
    
    if 'check_in' in reservation_info and 'check_out' in reservation_info:
        print("Successfully parsed reservation:", reservation_info)
        
        availability_data = scrape_thekokoon_availability(
            reservation_info['check_in'],
            reservation_info['check_out'],
            reservation_info.get('adults', 2),
            reservation_info.get('children', 0)
        )
        
        if availability_data:
            send_autoresponse(sender_address, reservation_info, availability_data, is_greek_email)
        else:
            generic_subject = "Λήψη Αιτήματος Κράτησης" if is_greek_email else "Reservation Request Received"
            generic_body = ("Σας ευχαριστούμε για το αίτημα κράτησης. Θα επεξεργαστούμε το αίτημά σας και θα επικοινωνήσουμε σύντομα μαζί σας."
                            if is_greek_email else
                            "Thank you for your reservation request. We will process your request and get back to you shortly.")
            send_email(sender_address, generic_subject, generic_body)
    else:
        print("Failed to parse reservation. Sending error notification.")
        send_error_notification(email_body, reservation_info)
        generic_subject = "Λήψη Αιτήματος Κράτησης" if is_greek_email else "Reservation Request Received"
        generic_body = ("Σας ευχαριστούμε για το αίτημα κράτησης. Η ομάδα μας θα το εξετάσει και θα επικοινωνήσει σύντομα μαζί σας."
                        if is_greek_email else
                        "Thank you for your reservation request. Our team will review it and get back to you shortly.")
        send_email(sender_address, generic_subject, generic_body)

def main():
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']
    imap_server = os.environ['IMAP_SERVER']
    imap_port = int(os.environ.get('IMAP_PORT', 993))

    imap = connect_to_inbox(email_address, password, imap_server, imap_port)
    imap.select("INBOX")

    _, message_numbers = imap.search(None, "UNSEEN")
    for num in message_numbers[0].split():
        _, msg = imap.fetch(num, "(RFC822)")
        email_msg = email.message_from_bytes(msg[0][1])
        
        sender_address = email.utils.parseaddr(email_msg['From'])[1]
        email_body = get_email_content(email_msg)
        
        process_email(email_body, sender_address)

    imap.logout()

if __name__ == "__main__":
    main()
