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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import traceback
import logging
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def get_staff_email():
    return os.environ['STAFF_EMAIL']

def calculate_free_cancellation_date(check_in_date):
    if isinstance(check_in_date, str):
        check_in_date = datetime.strptime(check_in_date, "%Y-%m-%d").date()
    
    free_cancellation_date = check_in_date - timedelta(days=20)
    
    if check_in_date.month == 11:
        if check_in_date.day == 9:
            free_cancellation_date = datetime(check_in_date.year, 10, 20).date()
        elif check_in_date.day == 10:
            free_cancellation_date = datetime(check_in_date.year, 10, 21).date()
    
    return free_cancellation_date

def connect_to_imap(email_address, password, imap_server, imap_port=993):
    logging.info(f"Attempting to connect to IMAP server: {imap_server} on port {imap_port}")
    
    try:
        context = ssl.create_default_context()
        logging.info("Creating IMAP4_SSL client")
        imap = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=context)
        
        logging.info("Attempting to log in")
        imap.login(email_address, password)
        logging.info("Successfully logged in to IMAP server")
        return imap
    except Exception as e:
        logging.error(f"Unexpected error: {type(e).__name__}: {e}")
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
    email_body = email_body.lower()
    reservation_info = {}

    # Define patterns for various information
    patterns = {
        'check_in': [
            r'(?:check[ -]?in|arrival|from|άφιξη|από)[\s:]+(.+?)(?:\n|$)',
            r'(?:από|from)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)',
            r'(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)\s+(?:έως|μέχρι|to|till)',
        ],
        'check_out': [
            r'(?:check[ -]?out|departure|to|until|till|αναχώρηση|μέχρι)[\s:]+(.+?)(?:\n|$)',
            r'(?:έως|μέχρι|to|till)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)',
        ],
        'adults': [
            r'(?:adults?|persons?|people|guests?|ενήλικες|άτομα)[\s:]+(\d+)',
            r'(\d+)\s+(?:adults?|persons?|people|guests?|ενήλικες|άτομα)',
        ],
        'children': [
            r'(?:children|kids|παιδιά)[\s:]+(\d+)',
            r'(\d+)\s+(?:children|kids|παιδιά)',
        ],
        'room_type': [
            r'(?:room|accommodation|δωμάτιο|κατάλυμα)[\s:]+(.+?)(?:\n|$)',
        ],
    }

    # Try to match each pattern
    for key, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, email_body)
            if match:
                reservation_info[key] = match.group(1).strip()
                break

    # Special handling for date range
    date_range_patterns = [
        r'(για|for)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)\s+(?:εως|έως|to|till)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)',
        r'(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)\s+(?:εως|έως|to|till)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)',
    ]
    for pattern in date_range_patterns:
        match = re.search(pattern, email_body)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                reservation_info['check_in'] = groups[-2]
                reservation_info['check_out'] = groups[-1]
            break

    # Parse dates
    for date_key in ['check_in', 'check_out']:
        if date_key in reservation_info:
            try:
                reservation_info[date_key] = parse_custom_date(reservation_info[date_key])
            except ValueError as e:
                logging.warning(f"Failed to parse {date_key} date: {str(e)}")
                del reservation_info[date_key]

    # Set check_out to next day if only check_in is provided
    if 'check_in' in reservation_info and 'check_out' not in reservation_info:
        reservation_info['check_out'] = reservation_info['check_in'] + timedelta(days=1)

    # Convert adults and children to integers
    for num_key in ['adults', 'children']:
        if num_key in reservation_info:
            try:
                reservation_info[num_key] = int(reservation_info[num_key])
            except ValueError:
                logging.warning(f"Failed to parse {num_key} as integer")
                del reservation_info[num_key]

    # Set default adults if not specified
    if 'adults' not in reservation_info:
        reservation_info['adults'] = 2

    return reservation_info

def parse_custom_date(date_string):
    # Try to parse various date formats
    date_formats = [
        r'(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?',  # DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
        r'(\d{1,2})\s+([α-ωa-z]+)(?:\s+(\d{2,4}))?',    # DD Month YYYY
        r'([α-ωa-z]+)\s+(\d{1,2})(?:,?\s+(\d{2,4}))?',  # Month DD, YYYY
    ]

    for date_format in date_formats:
        match = re.search(date_format, date_string, re.IGNORECASE)
        if match:
            day, month, year = match.groups()
            
            # Handle month names
            if month.isalpha():
                month = month.lower()
                if month in month_mapping:
                    month = month_mapping[month]
                else:
                    raise ValueError(f"Unknown month: {month}")
            
            # Convert to integers
            day = int(day)
            month = int(month)
            year = int(year) if year else datetime.now().year

            # Handle two-digit years
            if len(str(year)) == 2:
                year += 2000 if year < 50 else 1900

            # Validate date
            try:
                return datetime(year, month, day).date()
            except ValueError as e:
                raise ValueError(f"Invalid date: {date_string}. Error: {str(e)}")

    # If no format matches, try dateutil parser as a fallback
    try:
        return date_parser.parse(date_string, fuzzy=True).date()
    except ValueError:
        raise ValueError(f"Unable to parse date: {date_string}")

def is_greek(text):
    return bool(re.search(r'[\u0370-\u03FF]', text))

def scrape_thekokoon_availability(check_in, check_out, adults, children):
    base_url = f"https://thekokoonvolos.reserve-online.net/?checkin={check_in.strftime('%Y-%m-%d')}&rooms=1&nights={(check_out - check_in).days}&adults={adults}&src=107"
    if children > 0:
        base_url += f"&children={children}"
    
    currencies = ['EUR', 'USD']
    all_availability_data = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for currency in currencies:
            url = f"{base_url}&currency={currency}"
            logging.info(f"Attempting to scrape availability data for {currency} from {url}")
            
            try:
                page = browser.new_page()
                page.set_default_timeout(60000)  # Increase timeout to 60 seconds
                
                logging.info(f"Navigating to {url}")
                response = page.goto(url)
                logging.info(f"Navigation complete. Status: {response.status}")
                
                logging.info("Waiting for page to load completely")
                page.wait_for_load_state('networkidle')
                
                logging.info("Checking for room name and price elements")
                room_names = page.query_selector_all('td.name')
                room_prices = page.query_selector_all('td.price')
                
                logging.info(f"Found {len(room_names)} room names and {len(room_prices)} room prices")
                
                if not room_names or not room_prices or len(room_prices) != len(room_names) * 2:
                    logging.warning("Unexpected number of room names or prices. Dumping page content:")
                    logging.warning(page.content())
                    continue
                
                availability_data = []
                for i in range(0, len(room_names)):
                    try:
                        room_type = room_names[i].inner_text().strip()
                        price1_text = room_prices[i*2].inner_text().strip()
                        price2_text = room_prices[i*2 + 1].inner_text().strip()
                        
                        price1_match = re.search(r'([\$€])([\d,]+(?:\.\d{2})?)', price1_text)
                        price2_match = re.search(r'([\$€])([\d,]+(?:\.\d{2})?)', price2_text)
                        
                        if price1_match and price2_match:
                            price1 = float(price1_match.group(2).replace(',', ''))
                            price2 = float(price2_match.group(2).replace(',', ''))
                            
                            free_cancellation_date = calculate_free_cancellation_date(check_in)
                            
                            room_data = {
                                "room_type": room_type,
                                "prices": [
                                    {
                                        f"price_{currency.lower()}": price1,
                                        "cancellation_policy": "Non-refundable",
                                        "free_cancellation_date": None
                                    },
                                    {
                                        f"price_{currency.lower()}": price2,
                                        "cancellation_policy": "Free Cancellation",
                                        "free_cancellation_date": free_cancellation_date
                                    }
                                ],
                                "availability": "Available"
                            }
                            
                            availability_data.append(room_data)
                            logging.info(f"Scraped data for room: {room_type}")
                            logging.info(f"  Non-refundable Price: {price1_match.group(1)}{price1:.2f}")
                            logging.info(f"  Free Cancellation Price: {price2_match.group(1)}{price2:.2f}")
                        else:
                            logging.warning(f"Could not extract prices for room: {room_type}")
                    except Exception as e:
                        logging.error(f"Error processing room {i + 1}:")
                        logging.error(traceback.format_exc())
                
                all_availability_data[currency] = availability_data
                logging.info(f"Scraped availability data for {currency}: {availability_data}")
                
            except PlaywrightTimeoutError as e:
                logging.error(f"Timeout error for {currency}: {e}")
                logging.error("Page content at time of error:")
                logging.error(page.content())
            except Exception as e:
                logging.error(f"Unexpected error for {currency}: {type(e).__name__}: {e}")
                logging.error("Traceback:")
                logging.error(traceback.format_exc())
                logging.error("Page content at time of error:")
                logging.error(page.content())
            finally:
                page.close()
        
        browser.close()
    
    return all_availability_data

def send_email(to_address: str, subject: str, body: str) -> None:
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
        logging.info(f"Email sent successfully to {to_address}")
    except Exception as e:
        logging.error(f"Failed to send email to {to_address}. Error: {str(e)}")
        raise


def send_autoresponse(staff_email: str, customer_email: str, reservation_info: Dict[str, Any], availability_data: Dict[str, List[Dict[str, Any]]], is_greek_email: bool, original_email) -> None:
    if is_greek_email:
        subject = f"Νέο Αίτημα Κράτησης - {customer_email}"
        body = f"""
        Λήφθηκε νέο αίτημα κράτησης από {customer_email}.

        Λεπτομέρειες κράτησης:
        Ημερομηνία άφιξης: {reservation_info['check_in']}
        Ημερομηνία αναχώρησης: {reservation_info['check_out']}
        Αριθμός ενηλίκων: {reservation_info['adults']}
        Αριθμός παιδιών: {reservation_info.get('children', 'Δεν διευκρινίστηκε')}

        Διαθέσιμες επιλογές:
        """
    else:
        subject = f"New Reservation Request - {customer_email}"
        body = f"""
        A new reservation request has been received from {customer_email}.

        Reservation details:
        Check-in date: {reservation_info['check_in']}
        Check-out date: {reservation_info['check_out']}
        Number of adults: {reservation_info['adults']}
        Number of children: {reservation_info.get('children', 'Not specified')}

        Available options:
        """
    
    for currency, rooms in availability_data.items():
        body += f"\nPrices in {currency}:\n"
        for room in rooms:
            body += f"\nRoom type: {room['room_type']}\n"
            body += f"Availability: {room['availability']}\n"
            for price_option in room['prices']:
                body += f"  Price: {price_option[f'price_{currency.lower()}']:.2f} {currency}\n"
                body += f"  Cancellation policy: {price_option['cancellation_policy']}\n"
                if price_option['free_cancellation_date']:
                    body += f"  Free cancellation until: {price_option['free_cancellation_date'].strftime('%d/%m/%Y')}\n"
    
    body += "\nPlease process this request and respond to the customer as appropriate."

    send_email_with_original(staff_email, subject, body, original_email)

def send_email_with_original(to_address: str, subject: str, body: str, original_email) -> None:
    smtp_server = "mail.kokoonvolos.gr"
    smtp_port = 465  # SSL port
    sender_email = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = to_address
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    # Attach the original email
    message.attach(MIMEText("\n\n--- Original Message ---\n", "plain", "utf-8"))
    if original_email.is_multipart():
        for part in original_email.walk():
            if part.get_content_type() == "text/plain":
                message.attach(MIMEText(part.get_payload(decode=True).decode(), "plain", "utf-8"))
                break
    else:
        message.attach(MIMEText(original_email.get_payload(decode=True).decode(), "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, password)
            server.send_message(message)
        logging.info(f"Email sent successfully to {to_address}")
    except Exception as e:
        logging.error(f"Failed to send email to {to_address}. Error: {str(e)}")
        raise

def send_partial_info_response(staff_email: str, customer_email: str, reservation_info: Dict[str, Any], is_greek_email: bool) -> None:
    if is_greek_email:
        subject = f"Νέο Αίτημα Κράτησης (Μερικές Πληροφορίες) - {customer_email}"
        body = f"""
        Λήφθηκε νέο αίτημα κράτησης από {customer_email}, αλλά δεν ήταν δυνατή η παροχή πλήρων πληροφοριών διαθεσιμότητας.

        Λεπτομέρειες κράτησης:
        Ημερομηνία άφιξης: {reservation_info['check_in']}
        Ημερομηνία αναχώρησης: {reservation_info['check_out']}
        Αριθμός ενηλίκων: {reservation_info.get('adults', 'Δεν διευκρινίστηκε')}
        Αριθμός παιδιών: {reservation_info.get('children', 'Δεν διευκρινίστηκε')}

        Παρακαλώ επεξεργαστείτε αυτό το αίτημα χειροκίνητα και επικοινωνήστε με τον πελάτη το συντομότερο δυνατό.
        """
    else:
        subject = f"New Reservation Request (Partial Information) - {customer_email}"
        body = f"""
        A new reservation request has been received from {customer_email}, but full availability information could not be provided.

        Reservation details:
        Check-in date: {reservation_info['check_in']}
        Check-out date: {reservation_info['check_out']}
        Number of adults: {reservation_info.get('adults', 'Not specified')}
        Number of children: {reservation_info.get('children', 'Not specified')}

        Please process this request manually and contact the customer as soon as possible.
        """
    
    send_email(staff_email, subject, body)

def send_error_notification(email_body: str, reservation_info: Dict[str, Any], original_email) -> None:
    staff_email = get_staff_email()
    subject = "Error Processing Reservation Request"
    body = f"""
    An error occurred while processing a reservation request. The system was unable to parse the reservation dates.

    Parsed reservation info:
    {reservation_info}

    Original email body:
    {email_body}

    Please review this request manually and respond to the customer as appropriate.
    """
    send_email_with_original(staff_email, subject, body, original_email)

def process_email(email_msg, sender_address: str) -> None:
    logging.info("Starting to process email")
    email_body = get_email_content(email_msg)
    is_greek_email = is_greek(email_body)
    logging.info(f"Email language: {'Greek' if is_greek_email else 'English'}")
    
    reservation_info = parse_reservation_request(email_body)
    logging.info(f"Parsed reservation info: {reservation_info}")
    
    staff_email = get_staff_email()
    
    if 'check_in' in reservation_info and 'check_out' in reservation_info:
        logging.info("Reservation dates found, proceeding to web scraping")
        
        availability_data = scrape_thekokoon_availability(
            reservation_info['check_in'],
            reservation_info['check_out'],
            reservation_info.get('adults', 2),
            reservation_info.get('children', 0)
        )
        logging.info(f"Web scraping result: {availability_data}")
        
        if availability_data:
            logging.info("Availability data found, sending detailed response to staff")
            send_autoresponse(staff_email, sender_address, reservation_info, availability_data, is_greek_email, email_msg)
        else:
            logging.info("No availability data found, sending partial information response to staff")
            send_partial_info_response(staff_email, sender_address, reservation_info, is_greek_email, email_msg)
    else:
        logging.warning("Failed to parse reservation dates. Sending error notification to staff.")
        send_error_notification(email_body, reservation_info, email_msg)
    
    logging.info("Email processing completed")
    
def main():
    logging.info("Starting email processor script")
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']
    imap_server = 'mail.kokoonvolos.gr'
    imap_port = 993

    logging.info(f"Email Address: {email_address}")
    logging.info(f"IMAP Server: {imap_server}")
    logging.info(f"IMAP Port: {imap_port}")

    try:
        imap = connect_to_imap(email_address, password, imap_server, imap_port)
        imap.select("INBOX")

        _, message_numbers = imap.search(None, "UNSEEN")
        if not message_numbers[0]:
            logging.info("No new messages found.")
        else:
            for num in message_numbers[0].split():
                logging.info(f"Processing message number: {num}")
                _, msg = imap.fetch(num, "(RFC822)")
                email_msg = email.message_from_bytes(msg[0][1])
                
                sender_address = email.utils.parseaddr(email_msg['From'])[1]
                logging.info(f"Sender: {sender_address}")
                
                email_body = get_email_content(email_msg)
                logging.info("Email body retrieved")
                
                process_email(email_msg, sender_address)
                logging.info(f"Finished processing message number: {num}")

        imap.logout()
        logging.info("Email processing completed successfully")
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        logging.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    main()

