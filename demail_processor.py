import os
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, date
import time
import traceback

import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
import ssl

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from dateutil import parser as date_parser
import dateparser
from transliterate import detect_language as transliterate_detect_language

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set up Open Router API key
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")

if not OPEN_ROUTER_API_KEY:
    logger.error("OPEN_ROUTER_API_KEY is not set in the environment variables")
    raise ValueError("OPEN_ROUTER_API_KEY is missing")

OPEN_ROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

def normalize_text(text: str) -> str:
    logger.debug(f"Normalizing text: {text[:50]}...")
    return text.lower()

def get_staff_email():
    staff_email = os.environ['STAFF_EMAIL']
    logger.info(f"Retrieved staff email: {staff_email}")
    return staff_email

def detect_language(text: str) -> str:
    lang = transliterate_detect_language(text)
    logger.info(f"Detected language: {'Greek' if lang == 'el' else 'English'}")
    return 'el' if lang == 'el' else 'en'

def clean_email_body(email_body: str) -> str:
    logger.info("Cleaning email body")
    email_body = re.sub(r'---------- Forwarded message ---------\n.*?\n\n', '', email_body, flags=re.DOTALL)
    email_body = re.sub(r'^(From|Date|Subject|To):.*$', '', email_body, flags=re.MULTILINE)
    email_body = re.sub(r'^[A-Za-z-]+:\s.*$', '', email_body, flags=re.MULTILINE)
    email_body = re.sub(r'\n\s*\n', '\n\n', email_body)
    email_body = email_body.strip()
    logger.info(f"Cleaned email body (first 100 chars): {email_body[:100]}...")
    return email_body


def post_process_reservation_info(reservation_info: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Post-processing reservation info")
    try:
        if 'check_in' in reservation_info and isinstance(reservation_info['check_in'], date):
            check_in = reservation_info['check_in']
            logger.info(f"Check-in date: {check_in}")
            
            if 'check_out' in reservation_info and isinstance(reservation_info['check_out'], date):
                check_out = reservation_info['check_out']
                logger.info(f"Check-out date: {check_out}")
                nights = (check_out - check_in).days
                reservation_info['nights'] = nights
                logger.info(f"Calculated number of nights: {nights}")
            
            elif 'nights' in reservation_info and isinstance(reservation_info['nights'], int):
                nights = reservation_info['nights']
                check_out = check_in + timedelta(days=nights)
                reservation_info['check_out'] = check_out
                logger.info(f"Calculated check-out date: {check_out}")
            
            else:
                logger.warning("Check-out date not found. Assuming 1 night stay.")
                reservation_info['check_out'] = check_in + timedelta(days=1)
                reservation_info['nights'] = 1
        
        else:
            logger.error("Check-in date not found or invalid in reservation info")
            reservation_info['error'] = "Missing or invalid check-in date"
        
        # Additional validation
        if 'check_in' in reservation_info and 'check_out' in reservation_info:
            if reservation_info['check_out'] <= reservation_info['check_in']:
                logger.error("Check-out date is not after check-in date. This is invalid.")
                reservation_info['error'] = "Invalid date range: Check-out must be after check-in."
        
        logger.info(f"Post-processed reservation info: {reservation_info}")
    
    except Exception as e:
        logger.error(f"Error in post-processing reservation info: {str(e)}")
        reservation_info['error'] = f"Error in processing: {str(e)}"
    
    return reservation_info


































def parse_standardized_content(standardized_content: str) -> Dict[str, Any]:
    logger.info("Parsing standardized content")
    reservation_info = {}
    for line in standardized_content.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            if value and value != '[]':
                if key in ['check_in', 'check_out']:
                    try:
                        # Parse the date string to a date object
                        reservation_info[key] = datetime.strptime(value, "%Y-%m-%d").date()
                        logger.info(f"Parsed {key}: {reservation_info[key]}")
                    except ValueError:
                        logger.warning(f"Failed to parse date for {key}: {value}")
                        reservation_info[key] = value
                elif key in ['adults', 'children']:
                    try:
                        reservation_info[key] = int(value)
                        logger.info(f"Parsed {key}: {reservation_info[key]}")
                    except ValueError:
                        logger.warning(f"Failed to parse integer for {key}: {value}")
                        reservation_info[key] = value
                else:
                    reservation_info[key] = value
    logger.info(f"Parsed reservation info: {reservation_info}")
    return reservation_info
    
def send_to_ai_model(prompt: str, max_retries: int = 3) -> str:
    logger.info("Sending prompt to AI model")
    api_key = os.environ.get("OPEN_ROUTER_API_KEY")
    if not api_key:
        logger.error("OPEN_ROUTER_API_KEY is not set in the environment variables")
        raise ValueError("OPEN_ROUTER_API_KEY is not set in the environment variables")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/vahidbk/Tourix-Tourism",
        "X-Title": "Email Reservation Processor",
        "Content-Type": "application/json"
    }

    data = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that transforms email content into a standardized format."},
            {"role": "user", "content": prompt}
        ]
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1} to send request to AI model")
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            logger.info("Successfully received response from AI model")
            return result['choices'][0]['message']['content'].strip()
        except requests.RequestException as e:
            logger.error(f"Attempt {attempt + 1} failed: Error in AI model communication: {str(e)}")
            if attempt == max_retries - 1:
                raise

    logger.error("Max retries reached for AI model communication")
    raise Exception("Max retries reached for AI model communication")
    
def parse_date(date_str: str, current_year: int) -> date:
    """Parse a date string in the format DD/MM and return a date object."""
    day, month = map(int, date_str.split('/'))
    # Assume the current year, but if the resulting date is in the past, use next year
    year = current_year
    parsed_date = date(year, month, day)
    if parsed_date < date.today():
        year += 1
        parsed_date = date(year, month, day)
    return parsed_date

def calculate_nights(check_in: date, check_out: date) -> int:
    """Calculate the number of nights between check-in and check-out dates."""
    return (check_out - check_in).days

def transform_to_standard_format(email_body: str) -> str:
    logger.info("Transforming email content to standard format")
    current_date = datetime.now().date()
    current_year = current_date.year
    prompt = f"""
    Transform the following email content into a standardized format:
    
    Original Email:
    {email_body}
    
    Standardized Format:
    Check-in: [DATE]
    Check-out: [DATE]
    Adults: [NUMBER]
    Children: [NUMBER]
    Room Type: [TYPE]
    
    Please follow these guidelines carefully:
    1. Fill in the [PLACEHOLDERS] with the appropriate information from the email.
    2. If any information is missing, leave the placeholder empty.
    3. For dates in the format DD/MM (e.g., 3/10, 05/10), interpret them as follows:
       - Use the format YYYY-MM-DD in your output
       - Assume the current year ({current_year}) unless the date has already passed, in which case use the next year
       - Disregard any mentioned day of the week and focus solely on the numeric date
    4. Do not calculate or include the number of nights. This will be calculated separately.
    5. Pay special attention to date formats in different languages.
    6. Always include the full 4-digit year in your output dates.

    Current date for reference: {current_date.strftime("%Y-%m-%d")}

    Please provide your standardized output, followed by a brief explanation of how you interpreted the dates and any assumptions you made.
    """
    
    try:
        transformed_content = send_to_ai_model(prompt)
        logger.info(f"Standardized content: {transformed_content}")
        return transformed_content
    except Exception as e:
        logger.error(f"Error during email transformation: {str(e)}")
        raise


def process_email_content(email_body: str) -> Dict[str, Any]:
    logger.info("Processing email content")
    try:
        standardized_content = transform_to_standard_format(email_body)
        reservation_info = parse_standardized_content(standardized_content)
        reservation_info = post_process_reservation_info(reservation_info)
        logger.info(f"Processed email content: {reservation_info}")
        return reservation_info
    except Exception as e:
        logger.error(f"Error processing email content: {str(e)}")
        raise

        
def calculate_free_cancellation_date(check_in_date):
    logger.info(f"Calculating free cancellation date for check-in date: {check_in_date}")
    if isinstance(check_in_date, str):
        check_in_date = datetime.strptime(check_in_date, "%Y-%m-%d").date()
    
    free_cancellation_date = check_in_date - timedelta(days=20)
    
    if check_in_date.month == 11:
        if check_in_date.day == 9:
            free_cancellation_date = datetime(check_in_date.year, 10, 20).date()
        elif check_in_date.day == 10:
            free_cancellation_date = datetime(check_in_date.year, 10, 21).date()
    
    logger.info(f"Calculated free cancellation date: {free_cancellation_date}")
    return free_cancellation_date

def connect_to_imap(email_address, password, imap_server, imap_port=993):
    logger.info(f"Attempting to connect to IMAP server: {imap_server} on port {imap_port}")
    
    try:
        context = ssl.create_default_context()
        logger.info("Creating IMAP4_SSL client")
        imap = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=context)
        
        logger.info("Attempting to log in")
        imap.login(email_address, password)
        logger.info("Successfully logged in to IMAP server")
        return imap
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        raise

def get_email_content(msg):
    logger.info("Retrieving email content")
    subject = decode_header(msg["Subject"])[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_payload(decode=True).decode()
                logger.info(f"Retrieved multipart email content (first 100 chars): {content[:100]}...")
                return content
    else:
        content = msg.get_payload(decode=True).decode()
        logger.info(f"Retrieved simple email content (first 100 chars): {content[:100]}...")
        return content

def parse_numeric_fields(reservation_info):
    logger.info("Parsing numeric fields in reservation info")
    for num_key in ['adults', 'children', 'nights']:
        if num_key in reservation_info:
            try:
                reservation_info[num_key] = int(reservation_info[num_key])
            except ValueError:
                logger.warning(f"Failed to parse {num_key} as integer")
                del reservation_info[num_key]
    
    if 'adults' not in reservation_info:
        logger.info("Setting default value for 'adults' to 2")
        reservation_info['adults'] = 2
    logger.info(f"Parsed reservation info: {reservation_info}")
    return reservation_info

def is_greek(text):
    result = bool(re.search(r'[\u0370-\u03FF]', text))
    logger.info(f"Text language detection: {'Greek' if result else 'Not Greek'}")
    return result

def scrape_thekokoon_availability(check_in, check_out, adults, children):
    logger.info(f"Scraping availability for check-in: {check_in}, check-out: {check_out}, adults: {adults}, children: {children}")
    base_url = f"https://thekokoonvolos.reserve-online.net/?checkin={check_in.strftime('%Y-%m-%d')}&rooms=1&nights={(check_out - check_in).days}&adults={adults}&src=107"
    if children > 0:
        base_url += f"&children={children}"
    
    currencies = ['EUR', 'USD']
    all_availability_data = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for currency in currencies:
            url = f"{base_url}&currency={currency}"
            logger.info(f"Attempting to scrape availability data for {currency} from {url}")
            
            try:
                page = browser.new_page()
                page.set_default_timeout(60000)  # Increase timeout to 60 seconds
                
                logger.info(f"Navigating to {url}")
                response = page.goto(url)
                logger.info(f"Navigation complete. Status: {response.status}")
                
                logger.info("Waiting for page to load completely")
                page.wait_for_load_state('networkidle')
                
                logger.info("Checking for room name and price elements")
                room_names = page.query_selector_all('td.name')
                room_prices = page.query_selector_all('td.price')
                
                logger.info(f"Found {len(room_names)} room names and {len(room_prices)} room prices")
                
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
                        logger.info(f"Scraped data for room: {room_type}")
                        for price in prices:
                            logger.info(f"  {price['cancellation_policy']} Price: {price[f'price_{currency.lower()}']:.2f}")
                    except Exception as e:
                        logger.error(f"Error processing room {i + 1}:")
                        logger.error(str(e))
                
                all_availability_data[currency] = availability_data
                logger.info(f"Scraped availability data for {currency}: {availability_data}")
                
            except PlaywrightTimeoutError as e:
                logger.error(f"Timeout error for {currency}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error for {currency}: {type(e).__name__}: {e}")
            finally:
                page.close()
        
        browser.close()
    
    return all_availability_data

def send_email(to_address: str, subject: str, body: str) -> None:
    logger.info(f"Sending email to {to_address}")
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
        logger.info(f"Email sent successfully to {to_address}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_address}. Error: {str(e)}")
        raise

def send_autoresponse(staff_email: str, customer_email: str, reservation_info: Dict[str, Any], availability_data: Dict[str, List[Dict[str, Any]]], is_greek_email: bool, original_email) -> None:
    logger.info(f"Sending autoresponse to staff email: {staff_email}")
    if is_greek_email:
        subject = f"Νέο Αίτημα Κράτησης - {customer_email}"
        body = f"""
        Λήφθηκε νέο αίτημα κράτησης από {customer_email}.

        Λεπτομέρειες κράτησης:
        Ημερομηνία άφιξης: {reservation_info['check_in']}
        Ημερομηνία αναχώρησης: {reservation_info.get('check_out', 'Δεν διευκρινίστηκε')}
        Αριθμός διανυκτερεύσεων: {reservation_info.get('nights', 'Δεν διευκρινίστηκε')}
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
        Check-out date: {reservation_info.get('check_out', 'Not specified')}
        Number of nights: {reservation_info.get('nights', 'Not specified')}
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
    
    logger.info("Autoresponse content prepared")
    send_email_with_original(staff_email, subject, body, original_email)

def send_email_with_original(to_address: str, subject: str, body: str, original_email) -> None:
    logger.info(f"Sending email with original content to {to_address}")
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
        logger.info(f"Email with original content sent successfully to {to_address}")
    except Exception as e:
        logger.error(f"Failed to send email with original content to {to_address}. Error: {str(e)}")
        raise

def send_partial_info_response(staff_email: str, customer_email: str, reservation_info: Dict[str, Any], is_greek_email: bool, original_email) -> None:
    logger.info(f"Sending partial info response to staff email: {staff_email}")
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
    
    logger.info("Partial info response content prepared")
    send_email_with_original(staff_email, subject, body, original_email)

def send_error_notification(email_body: str, reservation_info: Dict[str, Any], original_email) -> None:
    logger.info("Sending error notification")
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
    logger.info("Error notification content prepared")
    send_email_with_original(staff_email, subject, body, original_email)


def process_email(email_msg: email.message.Message, sender_address: str) -> None:
    logger.info(f"Starting to process email from {sender_address}")
    email_body = get_email_content(email_msg)
    staff_email = get_staff_email()
    
    try:
        logger.info("Processing email content")
        standardized_content = transform_to_standard_format(email_body)
        reservation_info = parse_standardized_content(standardized_content)
        reservation_info = post_process_reservation_info(reservation_info)
        logger.info(f"Processed reservation info: {reservation_info}")
        
        if 'error' in reservation_info:
            logger.error(f"Error in reservation info: {reservation_info['error']}")
            send_error_notification(email_body, reservation_info, email_msg)
            return
        
        if 'check_in' in reservation_info and isinstance(reservation_info['check_in'], date):
            logger.info("Valid check-in data found, proceeding to web scraping")
            try:
                availability_data = scrape_thekokoon_availability(
                    reservation_info['check_in'],
                    reservation_info['check_out'],
                    reservation_info.get('adults', 2),
                    reservation_info.get('children', 0)
                )
                logger.info(f"Web scraping result: {availability_data}")
                
                if availability_data:
                    logger.info("Availability data found, sending detailed response to staff")
                    send_autoresponse(staff_email, sender_address, reservation_info, availability_data, is_greek(email_body), email_msg)
                else:
                    logger.info("No availability data found, sending partial information response to staff")
                    send_partial_info_response(staff_email, sender_address, reservation_info, is_greek(email_body), email_msg)
            except Exception as e:
                logger.error(f"Error during web scraping: {str(e)}")
                send_partial_info_response(staff_email, sender_address, reservation_info, is_greek(email_body), email_msg)
        else:
            logger.warning("Failed to parse valid check-in date. Sending error notification to staff.")
            send_error_notification(email_body, reservation_info, email_msg)
    
    except Exception as e:
        logger.error(f"Error during email processing: {str(e)}")
        send_error_notification(email_body, {}, email_msg)
    
    logger.info("Email processing completed")
    
def main():
    logger.info("Starting email processor script")
    email_address = os.environ['EMAIL_ADDRESS']
    password = os.environ['EMAIL_PASSWORD']
    imap_server = 'mail.kokoonvolos.gr'
    imap_port = 993

    logger.info(f"Email Address: {email_address}")
    logger.info(f"IMAP Server: {imap_server}")
    logger.info(f"IMAP Port: {imap_port}")

    try:
        imap = connect_to_imap(email_address, password, imap_server, imap_port)
        imap.select("INBOX")

        _, message_numbers = imap.search(None, "UNSEEN")
        if not message_numbers[0]:
            logger.info("No new messages found.")
        else:
            for num in message_numbers[0].split():
                logger.info(f"Processing message number: {num}")
                _, msg = imap.fetch(num, "(RFC822)")
                email_msg = email.message_from_bytes(msg[0][1])
                
                sender_address = email.utils.parseaddr(email_msg['From'])[1]
                logger.info(f"Sender: {sender_address}")
                
                email_body = get_email_content(email_msg)
                logger.info("Email body retrieved")
                
                process_email(email_msg, sender_address)
                logger.info(f"Finished processing message number: {num}")

        imap.logout()
        logger.info("Email processing completed successfully")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    main()
