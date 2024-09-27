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
from typing import List, Dict, Any, Optional
import unicodedata
import spacy
from spacy.matcher import Matcher
from datetime import datetime, timedelta
import re
from transliterate import detect_language as transliterate_detect_language, translit

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
###############################################################################################
def normalize_text(text: str) -> str:
    return text.lower()

def get_staff_email():
    return os.environ['STAFF_EMAIL']

def detect_language(text: str) -> str:
    lang = transliterate_detect_language(text)
    return 'el' if lang == 'el' else 'en'
###############################################################################################d

def parse_english_date(date_str: str) -> datetime.date:
    months = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    patterns = [
        r'(\d{1,2})\s*([a-z]{3,9})\s*(\d{2,4})?',  # 9 nov 24 or 9 november 2024
        r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?',    # 9/11 or 9/11/24
    ]
    for pattern in patterns:
        match = re.match(pattern, date_str)
        if match:
            day, month, year = match.groups()
            if month.isalpha():
                month = months[month[:3]]
            else:
                month = int(month)
            day = int(day)
            year = int(year) if year else datetime.now().year
            if year < 100:
                year += 2000
            return datetime(year, month, day).date()
    raise ValueError(f"Unable to parse date: {date_str}")

def parse_english_request(email_body: str) -> Dict[str, Any]:
    reservation_info = {}
    
    # Extract check-in and check-out dates
    check_in_match = re.search(r'check\s*in\s*:?\s*(.+)', email_body, re.IGNORECASE)
    check_out_match = re.search(r'check\s*out\s*:?\s*(.+)', email_body, re.IGNORECASE)
    
    if check_in_match:
        try:
            reservation_info['check_in'] = parse_english_date(check_in_match.group(1))
        except ValueError as e:
            logging.error(f"Failed to parse check-in date: {str(e)}")
    
    if check_out_match:
        try:
            reservation_info['check_out'] = parse_english_date(check_out_match.group(1))
        except ValueError as e:
            logging.error(f"Failed to parse check-out date: {str(e)}")
    
    # Extract number of nights
    nights_match = re.search(r'(\d+)\s*nights?', email_body, re.IGNORECASE)
    if nights_match:
        reservation_info['nights'] = int(nights_match.group(1))
    
    # Extract number of adults and children
    adults_match = re.search(r'(\d+)\s*(?:adults?|persons?|people|guests?)', email_body, re.IGNORECASE)
    children_match = re.search(r'(\d+)\s*(?:children|kids)', email_body, re.IGNORECASE)
    
    if adults_match:
        reservation_info['adults'] = int(adults_match.group(1))
    else:
        reservation_info['adults'] = 2  # Default to 2 adults if not specified
    
    if children_match:
        reservation_info['children'] = int(children_match.group(1))
    
    # Extract room type
    room_match = re.search(r'(?:room|accommodation):\s*(.+?)(?:\n|$)', email_body, re.IGNORECASE)
    if room_match:
        reservation_info['room_type'] = room_match.group(1).strip()
    
    return reservation_info
#################################################################d
def parse_greek_date(date_str: str) -> datetime.date:
    logging.debug(f"Attempting to parse date: {date_str}")
    greek_months = {
        'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαι': 5, 'ιουν': 6,
        'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12,
        'ιανουαριου': 1, 'φεβρουαριου': 2, 'μαρτιου': 3, 'απριλιου': 4, 'μαιου': 5, 'ιουνιου': 6,
        'ιουλιου': 7, 'αυγουστου': 8, 'σεπτεμβριου': 9, 'οκτωβριου': 10, 'νοεμβριου': 11, 'δεκεμβριου': 12
    }
    
    date_str = date_str.lower()
    for month, num in greek_months.items():
        if month in date_str:
            date_str = date_str.replace(month, str(num))
            break
    
    try:
        parsed_date = datetime.strptime(date_str, "%d %m %Y").date()
        logging.debug(f"Successfully parsed date: {parsed_date}")
        return parsed_date
    except ValueError:
        try:
            parsed_date = datetime.strptime(date_str, "%d %m").date().replace(year=datetime.now().year)
            logging.debug(f"Successfully parsed date without year: {parsed_date}")
            return parsed_date
        except ValueError:
            logging.error(f"Failed to parse date: {date_str}")
            raise ValueError(f"Unable to parse date: {date_str}")

def parse_format_1(email_body: str) -> Optional[Dict[str, Any]]:
    """Parse format: 'θελω 2 δωματια για 26 οκτωβριου για 3 νυχτες'"""
    pattern = r'(\d+)\s*(?:δωματια|δωμάτια).*?(\d+)\s*([α-ωίϊΐόάέύϋΰήώ]+).*?(\d+)\s*(?:νυχτες|νύχτες|βραδια|βράδια)'
    match = re.search(pattern, email_body, re.IGNORECASE)
    if match:
        rooms, day, month, nights = match.groups()
        try:
            check_in = parse_greek_date(f"{day} {month}")
            return {
                'check_in': check_in,
                'check_out': check_in + timedelta(days=int(nights)),
                'nights': int(nights),
                'adults': int(rooms) * 2,  # Assuming 2 adults per room
                'room_type': 'δωμάτιο' if int(rooms) == 1 else 'δωμάτια'
            }
        except ValueError:
            return None
    return None

def parse_format_2(email_body: str) -> Optional[Dict[str, Any]]:
    """Parse format: 'Εχετε δωμάτιο για 28/09 εως 30/09?'"""
    pattern = r'(?:για|από)\s*(\d{1,2}/\d{1,2}).*?(?:εως|έως|μέχρι)\s*(\d{1,2}/\d{1,2})'
    match = re.search(pattern, email_body, re.IGNORECASE)
    if match:
        check_in_str, check_out_str = match.groups()
        try:
            check_in = parse_greek_date(check_in_str)
            check_out = parse_greek_date(check_out_str)
            return {
                'check_in': check_in,
                'check_out': check_out,
                'nights': (check_out - check_in).days,
                'adults': 2,  # Default to 2 adults
                'room_type': 'δωμάτιο'
            }
        except ValueError:
            return None
    return None

def parse_format_3(email_body: str) -> Optional[Dict[str, Any]]:
    logging.info("Parsing email content:")
    logging.info(email_body)
    
    lines = [line.strip().lower() for line in email_body.split('\n') if line.strip()]
    logging.info("Processed lines:")
    for line in lines:
        logging.info(line)
    
    adults = children = check_in = check_out = None
    
    for line in lines:
        if 'άτομα' in line:
            adults_match = re.search(r'(\d+)\s*άτομα', line)
            if adults_match:
                adults = int(adults_match.group(1))
                logging.info(f"Extracted adults: {adults}")
        elif 'παιδιά' in line:
            children_match = re.search(r'(\d+)\s*παιδιά', line)
            if children_match:
                children = int(children_match.group(1))
                logging.info(f"Extracted children: {children}")
        elif 'από' in line:
            date_match = re.search(r'από\s+(.+)', line)
            if date_match:
                try:
                    check_in = parse_greek_date(date_match.group(1))
                    logging.info(f"Extracted check-in date: {check_in}")
                except ValueError as e:
                    logging.error(f"Error parsing check-in date: {str(e)}")
        elif 'εώς' in line or 'έως' in line:
            date_match = re.search(r'(?:εώς|έως)\s+(.+)', line)
            if date_match:
                try:
                    check_out = parse_greek_date(date_match.group(1))
                    logging.info(f"Extracted check-out date: {check_out}")
                except ValueError as e:
                    logging.error(f"Error parsing check-out date: {str(e)}")

    if adults is not None and check_in and check_out:
        result = {
            'adults': adults,
            'children': children if children is not None else 0,
            'check_in': check_in,
            'check_out': check_out,
            'nights': (check_out - check_in).days,
            'room_type': 'δωμάτιο'
        }
        logging.info(f"Successfully parsed reservation: {result}")
        return result
    else:
        logging.warning("Failed to extract all necessary information")
        return None

def parse_greek_request(email_body: str) -> Dict[str, Any]:
    logging.info("Starting to parse Greek reservation request")
    logging.info("Email content:")   
    parsing_functions = [parse_format_1, parse_format_2, parse_format_3]
    
    for i, func in enumerate(parsing_functions, 1):
        logging.debug(f"Attempting to parse with format {i}")
        result = func(email_body)
        if result:
            logging.info(f"Successfully parsed using format {i}")
            return result
    
    logging.warning("Failed to parse the email with any known format")
    return {'adults': 2, 'children': 0, 'room_type': 'δωμάτιο'}

#################################################################dds

def parse_reservation_request(email_body: str) -> Dict[str, Any]:
    logging.info("Parsing reservation request")
    
    normalized_text = normalize_text(email_body)
    language = detect_language(normalized_text)
    
    logging.info(f"Detected language: {language}")
    
    if language == 'el':
        reservation_info = parse_greek_request(normalized_text)
    else:
        reservation_info = parse_english_request(normalized_text)
    
    # Calculate check-out date if not provided
    if 'check_in' in reservation_info and 'check_out' not in reservation_info and 'nights' in reservation_info:
        reservation_info['check_out'] = reservation_info['check_in'] + timedelta(days=reservation_info['nights'])
        logging.info(f"Calculated check-out date: {reservation_info['check_out']}")
    
    logging.info(f"Final parsed reservation info: {reservation_info}")
    return reservation_info

#################################################################d
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


def parse_numeric_fields(reservation_info):
    for num_key in ['adults', 'children', 'nights']:
        if num_key in reservation_info:
            try:
                reservation_info[num_key] = int(reservation_info[num_key])
            except ValueError:
                logging.warning(f"Failed to parse {num_key} as integer")
                del reservation_info[num_key]
    
    if 'adults' not in reservation_info:
        reservation_info['adults'] = 2
    return reservation_info


    
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
                
                availability_data = []
                for i in range(len(room_names)):
                    try:
                        room_type = room_names[i].inner_text().strip()
                        price_texts = [price.inner_text().strip() for price in room_prices[i*2:i*2+2] if i*2+2 <= len(room_prices)]
                        
                        prices = []
                        for price_text in price_texts:
                            price_match = re.search(r'([\$€])([\d,]+(?:\.\d{2})?)', price_text)
                            if price_match:
                                price = float(price_match.group(2).replace(',', ''))
                                prices.append({
                                    f"price_{currency.lower()}": price,
                                    "cancellation_policy": "Non-refundable" if len(prices) == 0 else "Free Cancellation",
                                    "free_cancellation_date": calculate_free_cancellation_date(check_in) if len(prices) > 0 else None
                                })
                        
                        room_data = {
                            "room_type": room_type,
                            "prices": prices,
                            "availability": "Available" if prices else "Not Available"
                        }
                        
                        availability_data.append(room_data)
                        logging.info(f"Scraped data for room: {room_type}")
                        for price in prices:
                            logging.info(f"  {price['cancellation_policy']} Price: {price[f'price_{currency.lower()}']:.2f}")
                    except Exception as e:
                        logging.error(f"Error processing room {i + 1}:")
                        logging.error(str(e))
                
                all_availability_data[currency] = availability_data
                logging.info(f"Scraped availability data for {currency}: {availability_data}")
                
            except PlaywrightTimeoutError as e:
                logging.error(f"Timeout error for {currency}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error for {currency}: {type(e).__name__}: {e}")
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

def send_partial_info_response(staff_email: str, customer_email: str, reservation_info: Dict[str, Any], is_greek_email: bool, original_email) -> None:
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
    
    send_email_with_original(staff_email, subject, body, original_email)

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
        
        try:
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
        except Exception as e:
            logging.error(f"Error during web scraping: {str(e)}")
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

