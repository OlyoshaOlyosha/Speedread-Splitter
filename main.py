import configparser
import json
import logging
import os
import re
import tkinter as tk
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from tkinter import filedialog

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from tqdm import tqdm

__version__ = "1.0.0"
__app_name__ = "Book Splitter for Speed Reading"

def load_translations(lang: str) -> dict:
    """Load translations from JSON files."""
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    lang_file = os.path.join(locales_dir, f'{lang}.json')
    
    # Fallback to English if language file not found
    if not os.path.exists(lang_file):
        lang_file = os.path.join(locales_dir, 'en.json')
    
    try:
        with open(lang_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        # Emergency fallback if no files exist
        return {
            "header": "=== Book Splitter for Speed Reading ===\n",
            "language_prompt": "Choose interface language / Выберите язык интерфейса (en/ru) [en]: ",
            "invalid_language": "Please enter en or ru"
        }


def extract_text_from_fb2(path):
    """Extract clean text from FB2 or FB2.zip files."""
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path, 'r') as z:
            fb2_file = [name for name in z.namelist() if name.endswith('.fb2')][0]
            with z.open(fb2_file) as f:
                tree = ET.parse(f)
    else:
        tree = ET.parse(path)
    
    root = tree.getroot()
    namespaces = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
    
    text_parts = []
    for p in root.findall('.//fb:p', namespaces):
        text = ''.join(p.itertext()).strip()
        if text:
            text_parts.append(text)
    for p in root.findall('.//fb:v', namespaces):
        text = ''.join(p.itertext()).strip()
        if text:
            text_parts.append(text)
    
    return '\n\n'.join(text_parts)


def extract_text_from_epub(path):
    """Extract text from EPUB files."""
    book = epub.read_epub(path)
    text_parts = []
    
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if text:
                text_parts.append(text)
    
    return '\n\n'.join(text_parts)


def load_config():
    """Load settings from config.ini file."""
    config = {'minutes_per_day': 8, 'words_per_minute': 350, 'language': 'en', '_first_run': False}
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    
    if os.path.exists(config_path):
        parser = configparser.ConfigParser()
        parser.read(config_path, encoding='utf-8')
        if 'reading' in parser:
            config['minutes_per_day'] = parser.getint('reading', 'minutes_per_day', fallback=config['minutes_per_day'])
            config['words_per_minute'] = parser.getint('reading', 'words_per_minute', fallback=config['words_per_minute'])
            if parser.has_option('reading', 'language'):
                config['language'] = parser.get('reading', 'language')
            else:
                config['_first_run'] = True  # Language not found in existing config
    else:
        config['_first_run'] = True  # No config file exists
    
    # Validate language
    if config['language'] not in ['en', 'ru']:
        config['language'] = 'en'
        config['_first_run'] = True
    
    return config


def save_config(minutes, wpm, language='en'):
    """Save settings to config.ini file."""
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    
    # Create config with comments if it doesn't exist
    if not os.path.exists(config_path):
        # Choose template based on language
        if language == 'ru':
            template = """# Настройки для скорочтения

[reading]
# Рекомендуемое время ежедневных тренировок (минуты)
# 5-10 минут достаточно для начала без переутомления
minutes_per_day = {minutes}

# Целевая скорость чтения (слов в минуту)
# Средняя скорость: 200-300 слов/мин
# 350-500 - хорошая цель для начала скорочтения
words_per_minute = {wpm}

# Язык интерфейса. Доступны: 'en' (английский), 'ru' (русский)
language = {language}
"""
        else:
            template = """# Settings for speed reading

[reading]
# Recommended daily training time (minutes)
# 5-10 minutes is enough to start without overexertion
minutes_per_day = {minutes}

# Target reading speed (words per minute)
# Average speed: 200-300 words/min
# 350-500 is a good goal to start speed reading
words_per_minute = {wpm}

# Interface language. Available: 'en' (English), 'ru' (Russian)
language = {language}
"""
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template.format(minutes=minutes, wpm=wpm, language=language))
    else:
        # Update existing config by replacing only values, preserving comments
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Update only the values, keep everything else
        for i, line in enumerate(lines):
            if line.strip().startswith('minutes_per_day'):
                lines[i] = f'minutes_per_day = {minutes}\n'
            elif line.strip().startswith('words_per_minute'):
                lines[i] = f'words_per_minute = {wpm}\n'
            elif line.strip().startswith('language'):
                lines[i] = f'language = {language}\n'
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)


def clean_text(text):
    """Remove references, figures and tables from text."""
    # Remove numbered references [1], [2], etc. and figure/table mentions
    for i in range(1, 1000):
        text = text.replace(f'[{i}]', '')
        text = text.replace(f'Рис. {i}. ', '')
        text = text.replace(f'Таблица {i}. ', '')
    return text


def count_words(text):
    """Count words in Russian text using regex."""
    return len(re.findall(r'\b\w+\b', text))


def split_book():
    """Main function to split books for speed reading."""
    # Setup logging
    logging.basicConfig(filename='splitter.log', level=logging.INFO, encoding='utf-8', 
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Load config and check for first run
    config = load_config()
    lang = config['language']
    
    # Ask for language on first run (when language was not found in config)
    if lang == 'en' and config.get('_first_run', False):
        while True:
            choice = input("Choose interface language / Выберите язык интерфейса (en/ru) [en]: ").strip().lower()
            if choice in ['ru', 'русский', 'russian']:
                lang = 'ru'
                break
            elif choice in ['', 'en', 'english']:
                lang = 'en'
                break
            else:
                print("Please enter en or ru / Введите en или ru")
        
        # Load translations for first-time setup
        t = load_translations(lang)
        
        # Ask for reading speed on first run
        while True:
            try:
                user_input = input(t['wpm_prompt'].format(current=config['words_per_minute'])).strip()
                words_per_minute = int(user_input) if user_input else config['words_per_minute']
                if words_per_minute <= 0:
                    print(t['speed_positive'])
                    continue
                break
            except ValueError:
                print(t['positive_number'])
        
        # Ask for minutes per day on first run
        while True:
            try:
                user_input = input(t['minutes_prompt'].format(current=config['minutes_per_day'])).strip()
                minutes_per_day = int(user_input) if user_input else config['minutes_per_day']
                if minutes_per_day <= 0:
                    print(t['time_positive'])
                    continue
                break
            except ValueError:
                print(t['positive_number'])
        
        # Save initial configuration
        save_config(minutes_per_day, words_per_minute, lang)
        config['language'] = lang
        config['minutes_per_day'] = minutes_per_day
        config['words_per_minute'] = words_per_minute
    else:
        # Use existing config values
        words_per_minute = config['words_per_minute']
        minutes_per_day = config['minutes_per_day']
    
    # Load translations
    t = load_translations(lang)
    
    print(t['header'].format(version=__version__))
    
    # File selection dialog
    root = tk.Tk()
    root.withdraw()
    root.update()
    
    file_path = filedialog.askopenfilename(
        title=t['select_book'],
        filetypes=[
            ("Books", "*.fb2 *.epub *.fb2.zip *.txt"),
            ("FB2 files", "*.fb2"),
            ("EPUB files", "*.epub"),
            ("FB2 in archive", "*.fb2.zip"),
            ("TXT files", "*.txt"),
            ("All files", "*.*")
        ]
    )
    
    root.destroy()
    
    if not file_path:
        print(t['no_file_selected'])
        return
    
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ['.fb2', '.epub', '.zip', '.txt']:
        print(t['unsupported_format'])
        return
    
    print(t['reading_book'])
    try:
        if ext in ['.fb2', '.zip']:
            full_text = extract_text_from_fb2(file_path)
        elif ext == '.epub':
            full_text = extract_text_from_epub(file_path)
        else:  # .txt
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
        logging.info(f"Successfully read file: {file_path}")
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        print(t['error_reading_file'])
        return
    
    # Ask about text cleaning
    while True:
        clean_input = input(t['clean_footnotes_prompt']).strip().lower()
        if clean_input in ['', 'да', 'д', 'yes', 'y']:
            full_text = clean_text(full_text)
            print(t['cleaned'])
            break
        elif clean_input in ['нет', 'н', 'no', 'n']:
            print(t['not_cleaned'])
            break
        else:
            print(t['invalid_choice'])
    
    total_words = count_words(full_text)
    print(t['total_words'].format(total_words=total_words))
    logging.info(f"Book statistics: {total_words} words, file: {file_path}")
    
    # For non-first-run users, allow changing settings
    if not config.get('_first_run', False):
        # Input reading speed
        while True:
            try:
                user_input = input(t['wpm_prompt'].format(current=config['words_per_minute'])).strip()
                if user_input:  # Only update if user entered something
                    new_wpm = int(user_input)
                    if new_wpm <= 0:
                        print(t['speed_positive'])
                        continue
                    words_per_minute = new_wpm
                break
            except ValueError:
                print(t['positive_number'])
        
        # Input minutes per day
        while True:
            try:
                user_input = input(t['minutes_prompt'].format(current=config['minutes_per_day'])).strip()
                if user_input:  # Only update if user entered something
                    new_minutes = int(user_input)
                    if new_minutes <= 0:
                        print(t['time_positive'])
                        continue
                    minutes_per_day = new_minutes
                break
            except ValueError:
                print(t['positive_number'])
        
        # Save updated config if values changed
        if words_per_minute != config['words_per_minute'] or minutes_per_day != config['minutes_per_day']:
            save_config(minutes_per_day, words_per_minute, lang)
    
    words_per_chunk = words_per_minute * minutes_per_day
    print(t['calculation'].format(wpm=words_per_minute, minutes=minutes_per_day, chunk=words_per_chunk))
    
    # Determine book name and folder
    book_name = os.path.splitext(os.path.basename(file_path))[0]
    book_name = re.sub(r'[<>:"/\\|?*]', '', book_name)
    folder_name = f"{book_name} {words_per_minute}wpm"
    output_dir = os.path.join(os.path.dirname(file_path), folder_name)
    
    # Check if folder exists
    if os.path.exists(output_dir) and os.listdir(output_dir):
        while True:
            overwrite = input(t['folder_exists'].format(folder=folder_name)).strip().lower()
            if overwrite in ['да', 'д', 'yes', 'y']:
                break
            elif overwrite in ['нет', 'н', 'no', 'n']:
                print(t['operation_cancelled'])
                return
            else:
                print(t['invalid_choice'])
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Ask for starting phrase
    start_text = input(t['start_phrase_prompt']).strip()
    
    if start_text:
        current_pos = full_text.find(start_text)
        if current_pos == -1:
            print(t['phrase_not_found'].format(phrase=start_text))
            return
        print(t['found_position'].format(pos=current_pos))
    else:
        current_pos = 0
        print(t['start_from_beginning'])
    
    # Ask for start date
    date_input = input(t['date_prompt']).strip()
    if date_input:
        try:
            current_date = datetime.strptime(date_input, '%Y-%m-%d')
        except Exception as e:
            logging.error(f"Date parsing error '{date_input}': {e}")
            print(t['invalid_date'])
            current_date = datetime.now()
    else:
        current_date = datetime.now()
    
    chunk_count = 0
    
    # Progress bar
    pbar = tqdm(total=total_words, 
                desc=t['splitting_progress'], 
                unit=t['words_unit'],
                unit_scale=False)
    
    # Main splitting loop
    while current_pos < len(full_text):
        chunk_start = current_pos
        words_in_chunk = 0
        last_match_end = current_pos
        
        for match in re.finditer(r'\b\w+\b', full_text[current_pos:]):
            words_in_chunk += 1
            last_match_end = current_pos + match.end()
            
            if words_in_chunk >= words_per_chunk:
                break
        
        if words_in_chunk == 0:
            break
        
        # Find sentence/paragraph boundary
        chunk_end = last_match_end
        next_para = full_text.find('\n\n', last_match_end)
        next_dot = full_text.find('. ', last_match_end)
        
        if next_para != -1 and next_para < last_match_end + 100:
            chunk_end = next_para + 2
        elif next_dot != -1 and next_dot < last_match_end + 100:
            chunk_end = next_dot + 2
        else:
            chunk_end = last_match_end
        
        chunk_text = full_text[chunk_start:chunk_end].strip()
        
        if not chunk_text:
            break
        
        # Recount words in cleaned chunk
        actual_words = count_words(chunk_text)
        
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{book_name}_{date_str}_{actual_words}-{t['words_unit']}_{words_per_minute}wpm.txt"
        filepath = os.path.join(output_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(chunk_text)
        except Exception as e:
            logging.error(f"File writing error {filepath}: {e}")
            print(t['error_writing_file'])
            pbar.close()
            return
        
        current_pos = chunk_end
        current_date += timedelta(days=1)
        chunk_count += 1
        
        # Update progress bar
        pbar.update(actual_words)
    
    pbar.close()
    
    print(t['done'].format(count=chunk_count))
    print(t['output_dir'].format(dir=output_dir))
    
    # Statistics
    total_hours = total_words / words_per_minute / 60
    avg_chunk_words = total_words // chunk_count if chunk_count > 0 else 0
    print(t['stats_header'])
    print(t['stats_days'].format(days=chunk_count))
    print(t['stats_total_time'].format(hours=total_hours))
    print(t['stats_avg_chunk'].format(avg=avg_chunk_words))
    
    # Log final statistics
    logging.info(f"Splitting completed: {chunk_count} files, {total_hours:.1f} hours, average chunk {avg_chunk_words} words")

if __name__ == "__main__":
    # Main entry point
    split_book()
    
    # Load translations for exit message
    config = load_config()
    t = load_translations(config['language'])
    input(t['exit_prompt'])