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
from datetime import datetime, timedelta, date
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

def clean_email_body(email_body: str) -> str:
    """Remove forwarded message headers and unnecessary email formatting without breaking important content."""
    
    # Remove forwarded message header (preserve content after the header)
    email_body = re.sub(r'---------- Forwarded message ---------\n.*?\n\n', '', email_body, flags=re.DOTALL)
    
    # Remove common email headers (From:, Date:, Subject:, To:) at the beginning of the email
    email_body = re.sub(r'^(From|Date|Subject|To):.*$', '', email_body, flags=re.MULTILINE)
    
    # Remove only actual email-like headers (avoid stripping valid content with colons)
    # We add a stricter pattern to avoid removing lines that aren't headers
    email_body = re.sub(r'^[A-Za-z-]+:\s.*$', '', email_body, flags=re.MULTILINE)
    
    # Limit removal of multiple empty lines (keep 1 line break between paragraphs)
    email_body = re.sub(r'\n\s*\n', '\n\n', email_body)
    
    # Strip leading and trailing whitespace
    email_body = email_body.strip()
    
    logging.info("Cleaned email body:")
    logging.info(email_body)
    
    return email_body
###############################################################################################dds
def _greeklish_request(email_body: str) -> Optional[Dict[str, Any]]:
    """
    Parse Greeklish reservation requests in the format:
    [room type] [start date] me/eos [end date]
    Example: "ena diamerisma 4 noem me 16 noem"
    """
    logging.info("Parsing Greeklish email content:")
    logging.info(email_body)
    
    def translate_greeklish_month(month_str: str) -> str:
        greeklish_months = {
            # Short forms
            'ian': 'ιαν', 'gen': 'ιαν',
            'feb': 'φεβ', 'fev': 'φεβ',
            'mar': 'μαρ', 'mart': 'μαρ',
            'apr': 'απρ',
            'mai': 'μαι', 'may': 'μαι',
            'ioun': 'ιουν', 'iun': 'ιουν', 'jun': 'ιουν',
            'ioul': 'ιουλ', 'iul': 'ιουλ', 'jul': 'ιουλ',
            'aug': 'αυγ', 'avg': 'αυγ',
            'sep': 'σεπ', 'sept': 'σεπ',
            'okt': 'οκτ', 'oct': 'οκτ',
            'noe': 'νοε', 'nov': 'νοε',
            'dek': 'δεκ', 'dec': 'δεκ',
            
            # Full names and variations
            'ianouarios': 'ιανουάριος', 'ianuarios': 'ιανουάριος', 'genaris': 'ιανουάριος',
            'febrouarios': 'φεβρουάριος', 'fevruarios': 'φεβρουάριος', 'flevaris': 'φεβρουάριος',
            'martios': 'μάρτιος', 'martis': 'μάρτιος',
            'aprilios': 'απρίλιος', 'aprilis': 'απρίλιος',
            'maios': 'μάιος', 'mais': 'μάιος',
            'iounios': 'ιούνιος', 'junios': 'ιούνιος',
            'ioulios': 'ιούλιος', 'julios': 'ιούλιος',
            'augoustos': 'αύγουστος', 'avgustos': 'αύγουστος',
            'septembrios': 'σεπτέμβριος', 'septevrios': 'σεπτέμβριος',
            'oktobrios': 'οκτώβριος', 'octovrios': 'οκτώβριος',
            'noembrios': 'νοέμβριος', 'noemvrios': 'νοέμβριος',
            'dekembrios': 'δεκέμβριος', 'decemvrios': 'δεκέμβριος',
            
            # Additional variations
            'genaras': 'ιανουάριος', 'flevaris': 'φεβρουάριος',
            'maartios': 'μάρτιος', 'aprilos': 'απρίλιος',
            'mays': 'μάιος', 'lounis': 'ιούνιος',
            'loulis': 'ιούλιος', 'avghoustos': 'αύγουστος',
            'septemvris': 'σεπτέμβριος', 'octomvris': 'οκτώβριος',
            'noemvris': 'νοέμβριος', 'thekemvrios': 'δεκέμβριος'
        }
        month_str = month_str.lower()
        for greeklish, greek in greeklish_months.items():
            if month_str.startswith(greeklish):
                return greek
        return month_str  # If no match found, return original string
    
    def parse_greek_month(month_str: str) -> Optional[int]:
        greek_months = {
            'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαϊ': 5, 'μαι': 5, 'ιουν': 6,
            'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12,
            'ιανουάριος': 1, 'φεβρουάριος': 2, 'μάρτιος': 3, 'απρίλιος': 4, 'μάιος': 5,
            'ιούνιος': 6, 'ιούλιος': 7, 'αύγουστος': 8, 'σεπτέμβριος': 9,
            'οκτώβριος': 10, 'νοέμβριος': 11, 'δεκέμβριος': 12
        }
        month_str = month_str.lower()
        for key, value in greek_months.items():
            if month_str.startswith(key):
                return value
        return None
    
    # Regular expression pattern for Greeklish format
    pattern = r'([\w]+(?:\s+[\w]+)?)\s+(\d{1,2})?\s*([\w]{3,15})\s+(?:me|eos|mexri|os)\s+(\d{1,2})?\s*([\w]{3,15})'
    match = re.search(pattern, email_body, re.IGNORECASE)
    
    if match:
        logging.info(f"Matched Greeklish pattern: {match.group()}")
        room_type, start_day, start_month, end_day, end_month = match.groups()
        logging.info(f"Parsed Greeklish groups: room_type={room_type}, start_day={start_day}, start_month={start_month}, end_day={end_day}, end_month={end_month}")
        
        try:
            # Translate Greeklish months to Greek
            start_month_greek = translate_greeklish_month(start_month)
            end_month_greek = translate_greeklish_month(end_month)
            
            # Use the Greek month parsing logic
            start_month_num = parse_greek_month(start_month_greek)
            end_month_num = parse_greek_month(end_month_greek)
            
            if not start_month_num or not end_month_num:
                logging.error(f"Failed to parse Greeklish month: start_month={start_month}, end_month={end_month}")
                return None
            
            # If day is not provided, default to 1
            start_day = int(start_day) if start_day else 1
            end_day = int(end_day) if end_day else 1
            
            # Create date objects
            current_year = datetime.now().year
            start_date = datetime(current_year, start_month_num, start_day).date()
            end_date = datetime(current_year, end_month_num, end_day).date()
            
            # If end date is before start date, it might be in the next year
            if end_date < start_date:
                end_date = datetime(current_year + 1, end_month_num, end_day).date()
            
            # Calculate number of nights
            nights = (end_date - start_date).days
            
            result = {
                'room_type': room_type.strip().lower(),
                'check_in': start_date,
                'check_out': end_date,
                'nights': nights,
                'adults': 2  # Default to 2 adults if not specified
            }
            logging.info(f"Successfully parsed Greeklish reservation: {result}")
            return result
        except (ValueError, KeyError) as e:
            logging.error(f"Error parsing dates in Greeklish format: {str(e)}")
    else:
        logging.warning("Failed to match the pattern for Greeklish format")
    
    return None

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
    """
    Main function to parse English reservation requests.
    Combines existing parsing with the new concise format parsing.
    """
    reservation_info = {}
    
    # Try parsing with the existing method
    reservation_info.update(parse_existing_english_request(email_body))
    
    # If the existing method didn't parse critical information, try the concise method
    if not reservation_info.get('check_in') or not reservation_info.get('check_out'):
        concise_info = parse_concise_english_request(email_body)
        reservation_info.update(concise_info)
    
    return reservation_info

def parse_concise_english_request(email_body: str) -> Dict[str, Any]:
    """
    Parse concise English reservation requests in the format:
    [date] [room type] [number of nights]
    Example: "10/1 ONE APARTMENT 3 NIGHTS"
    """
    reservation_info = {}
    
    # Pattern to match the concise format
    pattern = r'(\d{1,2}/\d{1,2})\s+(.+?)\s+(\d+)\s+NIGHTS'
    match = re.search(pattern, email_body, re.IGNORECASE)
    
    if match:
        date_str, room_type, nights = match.groups()
        
        # Parse check-in date
        try:
            check_in = parse_english_date(date_str)
            reservation_info['check_in'] = check_in
            
            # Calculate check-out date
            reservation_info['check_out'] = check_in + timedelta(days=int(nights))
            
            # Set number of nights
            reservation_info['nights'] = int(nights)
            
            # Set room type
            reservation_info['room_type'] = room_type.strip().lower()
            
            # Default to 2 adults if not specified
            reservation_info['adults'] = 2
        except ValueError as e:
            logging.error(f"Failed to parse concise request: {str(e)}")
    
    return reservation_info

def parse_existing_english_request(email_body: str) -> Dict[str, Any]:
    """
    Existing parsing logic (unchanged from the original code)
    """
    reservation_info = {}

    # Extract check-in and check-out dates
    check_in_match = re.search(r'check\sin\s:?\s(.+)', email_body, re.IGNORECASE)
    check_out_match = re.search(r'check\sout\s:?\s(.+)', email_body, re.IGNORECASE)

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
    adults_match = re.search(r'(\d+)\s(?:adults?|persons?|people|guests?)', email_body, re.IGNORECASE)
    children_match = re.search(r'(\d+)\s(?:children|kids)', email_body, re.IGNORECASE)

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
    """
    Parse various Greek date formats into a datetime.date object.
    Handles formats like "9 Νοε 24", "9 Νοεμβρίου 2024", "9/11", "9/11/24".
    """
    logging.debug(f"Attempting to parse date: {date_str}")

    greek_months = {
        'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαι': 5, 'ιουν': 6,
        'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12,
        'ιανουαρίου': 1, 'φεβρουαρίου': 2, 'μαρτίου': 3, 'απριλίου': 4, 'μαΐου': 5,
        'ιουνίου': 6, 'ιουλίου': 7, 'αυγούστου': 8, 'σεπτεμβρίου': 9,
        'οκτωβρίου': 10, 'νοεμβρίου': 11, 'δεκεμβρίου': 12
    }
    
    date_str = date_str.lower().strip()

    # Handle DD/MM/YYYY or DD/MM format
    if '/' in date_str:
        try:
            parts = date_str.split('/')
            day = int(parts[0])
            month = int(parts[1])
            year = datetime.now().year if len(parts) < 3 else int(parts[2])
            if year < 100:  # Handle two-digit years
                year += 2000
            year = year if year >= 1900 else year + 1900  # Adjust for century
            return datetime(year, month, day).date()
        except ValueError:
            logging.debug(f"Failed to parse {date_str} as DD/MM/YYYY format")
    
    # Handle DD Month YYYY format
    parts = date_str.split()
    if len(parts) >= 2:
        try:
            day = int(parts[0])
            month_str = parts[1]
            month = greek_months.get(month_str[:3], None)  # Use first three letters or full name
            
            if month is None:
                raise ValueError(f"Unknown month: {month_str}")
            
            year = datetime.now().year  # Default to current year
            if len(parts) == 3 and parts[2].isdigit():
                year = int(parts[2])
                if year < 100:  # Handle two-digit years
                    year += 2000
                year = year if year >= 1900 else year + 1900  # Adjust for century

            return datetime(year, month, day).date()
        except ValueError:
            logging.debug(f"Failed to parse {date_str} as DD Month YYYY format")
    
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
    logging.info("Parsing email content (Format 2):")
    logging.info(email_body)
    
    pattern = r'(?:για|από)\s*(\d{1,2}/\d{1,2}).*?(?:εως|έως|μέχρι)\s*(\d{1,2}/\d{1,2})'
    match = re.search(pattern, email_body, re.IGNORECASE)
    if match:
        try:
            check_in = parse_greek_date(match.group(1))
            check_out = parse_greek_date(match.group(2))
            return {
                'check_in': check_in,
                'check_out': check_out,
                'nights': (check_out - check_in).days,
                'adults': 2,  # Default to 2 adults
                'children': 0,  # Default to 0 children
                'room_type': 'δωμάτιο'
            }
        except ValueError as e:
            logging.error(f"Error parsing dates in format 2: {str(e)}")
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

def parse_format_4(email_body: str) -> Optional[Dict[str, Any]]:
    """
    Parse Greek reservation requests in the format:
    [room type] [start date] εως [end date]
    Example: "ενα διαμερισμα 13 νοεμ εως 18 νοεμ"
    """
    logging.info("Parsing email content (Format 4):")
    logging.info(email_body)
    
    # Greek month names and abbreviations to numbers
    greek_months = {
        'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαϊ': 5, 'μαι': 5, 'ιουν': 6,
        'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12,
        'ιανουάριος': 1, 'φεβρουάριος': 2, 'μάρτιος': 3, 'απρίλιος': 4, 'μάιος': 5,
        'ιούνιος': 6, 'ιούλιος': 7, 'αύγουστος': 8, 'σεπτέμβριος': 9,
        'οκτώβριος': 10, 'νοέμβριος': 11, 'δεκέμβριος': 12
    }
    
    # Regular expression pattern for the new format
    pattern = r'([\wά-ώ]+(?:\s+[\wά-ώ]+)?)\s+(\d{1,2})?\s*([\wά-ώ]{3,10})\s+(?:εως|έως|μεχρι|μέχρι)\s+(\d{1,2})?\s*([\wά-ώ]{3,10})'
    match = re.search(pattern, email_body, re.IGNORECASE | re.UNICODE)
    
    if match:
        logging.info(f"Matched pattern: {match.group()}")
        room_type, start_day, start_month, end_day, end_month = match.groups()
        logging.info(f"Parsed groups: room_type={room_type}, start_day={start_day}, start_month={start_month}, end_day={end_day}, end_month={end_month}")
        
        def parse_greek_month(month_str):
            month_str = month_str.lower()
            for key, value in greek_months.items():
                if month_str.startswith(key):
                    return value
            return None

        try:
            # Convert Greek month names to numbers
            start_month_num = parse_greek_month(start_month)
            end_month_num = parse_greek_month(end_month)
            
            if not start_month_num or not end_month_num:
                logging.error(f"Failed to parse month: start_month={start_month}, end_month={end_month}")
                return None
            
            # If day is not provided, default to 1
            start_day = int(start_day) if start_day else 1
            end_day = int(end_day) if end_day else 1
            
            # Create date objects
            current_year = datetime.now().year
            start_date = datetime(current_year, start_month_num, start_day).date()
            end_date = datetime(current_year, end_month_num, end_day).date()
            
            # If end date is before start date, it might be in the next year
            if end_date < start_date:
                end_date = datetime(current_year + 1, end_month_num, end_day).date()
            
            # Calculate number of nights
            nights = (end_date - start_date).days
            
            result = {
                'room_type': room_type.strip().lower(),
                'check_in': start_date,
                'check_out': end_date,
                'nights': nights,
                'adults': 2  # Default to 2 adults if not specified
            }
            logging.info(f"Successfully parsed reservation: {result}")
            return result
        except (ValueError, KeyError) as e:
            logging.error(f"Error parsing dates in format 4: {str(e)}")
    else:
        logging.warning("Failed to match the pattern for Format 4")
    
    return None

def parse_format_5(email_body: str) -> Optional[Dict[str, Any]]:
    logging.info("Entering parse_format_5 function")
    logging.info(f"Original email content:\n{email_body}")

    def parse_and_standardize_date(date_str: str) -> date:
        """
        Parse a date string and return a standardized date object.
        Handles both YY and YYYY formats, assuming all dates are in the future.
        """
        parts = date_str.split('/')
        if len(parts) != 3:
            raise ValueError(f"Invalid date format: {date_str}")

        day, month, year = map(int, parts)
        
        current_year = datetime.now().year
        current_century = current_year // 100 * 100

        if year < 100:
            # If it's a two-digit year, assume it's in the future
            full_year = current_century + year
            if full_year < current_year:
                full_year += 100
        else:
            full_year = year

        return date(full_year, month, day)

    # Remove email footer
    email_body = re.split(r'sent with|unsubscribe', email_body, flags=re.IGNORECASE)[0]
    logging.info(f"Email content after footer removal:\n{email_body}")

    # Normalize the email content
    email_body = email_body.lower()
    logging.info(f"Lowercased email content:\n{email_body}")

    email_body = re.sub(r'\s+', ' ', email_body)
    logging.info(f"Normalized email content (spaces regularized):\n{email_body}")

    # Extract dates with more flexible pattern
    date_pattern = r'(\d{1,2}/\d{1,2}/\d{2,4})'
    date_matches = re.findall(date_pattern, email_body)
    logging.info(f"Found dates: {date_matches}")

    arrival_date = departure_date = None
    if len(date_matches) >= 2:
        try:
            arrival_date = parse_and_standardize_date(date_matches[0])
            departure_date = parse_and_standardize_date(date_matches[1])
        except ValueError as e:
            logging.error(f"Error parsing dates: {str(e)}")
            return None
    
    logging.info(f"Extracted arrival_date: {arrival_date}")
    logging.info(f"Extracted departure_date: {departure_date}")

    # Extract number of adults with more flexible pattern
    adults_pattern = r'(\d+)\s*(?:ενήλικ(?:ες|ας)|ατομ[αο]|adults?|persons?)'
    adults_match = re.search(adults_pattern, email_body)
    adults = int(adults_match.group(1)) if adults_match else None
    logging.info(f"Extracted adults: {adults}")

    if arrival_date and departure_date:
        nights = (departure_date - arrival_date).days

        result = {
            'check_in': arrival_date,
            'check_out': departure_date,
            'nights': nights,
            'adults': adults if adults is not None else 2  # Default to 2 adults if not specified
        }
        logging.info(f"Successfully parsed reservation: {result}")
        return result
    else:
        logging.warning("Failed to extract all required information")
        logging.info(f"Arrival date: {arrival_date}, Departure date: {departure_date}, Adults: {adults}")

    logging.info("Exiting parse_format_5 function without successful parse")
    return None

try:
    nlp = spacy.load("el_core_news_sm")
except IOError:
    spacy.cli.download("el_core_news_sm")
    nlp = spacy.load("el_core_news_sm")

def parse_with_spacy(email_body: str) -> Optional[Dict[str, Any]]:
    logging.info("Entering parse_with_spacy function")
    logging.info(f"Original email content:\n{email_body}")

    # Process the text with spaCy
    doc = nlp(email_body)

    # Extract dates and numbers
    dates = []
    numbers = []
    for ent in doc.ents:
        if ent.label_ == "DATE":
            dates.append(ent.text)
        elif ent.label_ == "CARDINAL":
            numbers.append(ent.text)

    logging.info(f"Extracted dates: {dates}")
    logging.info(f"Extracted numbers: {numbers}")
    logging.info(f"Extracted dates: {dates}")
    logging.info(f"Extracted numbers: {numbers}")

    # Attempt to identify check-in and check-out dates
    arrival_date = departure_date = None
    if len(dates) >= 2:
        arrival_date = dates[0]
        departure_date = dates[1]

    # Attempt to identify number of adults
    adults = None
    for num in numbers:
        if num.isdigit() and 1 <= int(num) <= 10:  # Assuming a reasonable range for number of adults
            adults = int(num)
            break

    logging.info(f"Identified arrival_date: {arrival_date}, departure_date: {departure_date}, adults: {adults}")

    if arrival_date and departure_date and adults is not None:
        try:
            # Convert extracted dates to datetime objects
            arrival = parse_flexible_date(arrival_date)
            departure = parse_flexible_date(departure_date)

            if arrival and departure:
                nights = (departure - arrival).days

                result = {
                    'check_in': arrival,
                    'check_out': departure,
                    'nights': nights,
                    'adults': adults
                }
                logging.info(f"Successfully parsed reservation with spaCy: {result}")
                return result
            else:
                logging.error("Failed to parse dates from extracted information")
        except ValueError as e:
            logging.error(f"Error parsing dates with spaCy: {str(e)}")
    else:
        logging.warning("Failed to extract all required information with spaCy")

    logging.info("Exiting parse_with_spacy function without successful parse")
    return None

def parse_flexible_date(date_string: str) -> Optional[datetime.date]:
    """
    Attempt to parse a date string into a datetime.date object using multiple formats.
    """
    date_formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d %B %Y",
        "%d %b %Y",
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_string, fmt).date()
        except ValueError:
            continue
    
    logging.error(f"Unable to parse date string: {date_string}")
    return None

def parse_greek_request(email_body: str) -> Dict[str, Any]:
    """
    Main function to parse Greek reservation requests.
    Now includes the spaCy backup parser.
    """
    logging.info("Starting to parse Greek reservation request")
    logging.info("Original email content:")
    logging.info(email_body)
    
    # Clean the email body
    cleaned_email = clean_email_body(email_body)
    logging.info("Cleaned email content:")
    logging.info(cleaned_email)
    
    parsing_functions = [parse_format_5, parse_format_4, parse_format_1, parse_format_2, parse_format_3, parse_with_spacy]
    
    for i, func in enumerate(parsing_functions, 1):
        logging.info(f"Attempting to parse with format {i}")
        result = func(cleaned_email)
        if result:
            logging.info(f"Successfully parsed using format {i}")
            return result
        else:
            logging.info(f"Format {i} parsing failed")
    
    logging.warning("Failed to parse the email with any known format, including spaCy backup")
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
        # Try Greeklish parsing first, then fall back to English if it fails
        reservation_info = parse_greeklish_request(normalized_text) or parse_english_request(normalized_text)
    
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

