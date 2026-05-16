import os
import time
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import threading
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///whatsapp.db')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Fix for Render PostgreSQL
if app.config['SQLALCHEMY_DATABASE_URI'] and app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

db = SQLAlchemy(app)

# Database Models
class MessageTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone_number = db.Column(db.String(20), nullable=False)
    group_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MessageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('message_template.id'), nullable=True)
    phone_number = db.Column(db.String(20))
    status = db.Column(db.String(20))
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

# WhatsApp Web Automation Class (Optimized for server)
class WhatsAppWebAutomation:
    def __init__(self):
        self.driver = None
        self.is_logged_in = False
        
    def init_driver(self):
        """Initialize Chrome driver for server environment"""
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")  # Headless mode for server
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-data-dir=/tmp/chrome_profile")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Use Chromium path for Render/Railway
        chrome_options.binary_location = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome')
        
        service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH', '/usr/bin/chromedriver'))
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        
    def check_login_status(self):
        """Check if WhatsApp Web is logged in"""
        try:
            self.driver.get("https://web.whatsapp.com")
            time.sleep(3)
            
            # Check for chat list (logged in)
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@data-testid="chat-list"]'))
                )
                self.is_logged_in = True
                return True
            except:
                self.is_logged_in = False
                return False
        except Exception as e:
            print(f"Error checking login: {e}")
            return False
    
    def get_qr_code(self):
        """Get QR code for login"""
        try:
            self.driver.get("https://web.whatsapp.com")
            time.sleep(3)
            
            qr_element = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//canvas[@aria-label="Scan me!"]'))
            )
            # Take screenshot of QR code area
            qr_element.screenshot('/tmp/qr_code.png')
            return True
        except:
            return False
    
    def send_message(self, phone_number, message):
        """Send message to a phone number"""
        try:
            phone_number = str(phone_number).replace('+', '').replace(' ', '').replace('-', '')
            
            url = f"https://web.whatsapp.com/send?phone={phone_number}&text={message}"
            self.driver.get(url)
            time.sleep(3)
            
            try:
                # Check for invalid number
                if self.driver.find_elements(By.XPATH, '//div[contains(text(), "Phone number shared via url is invalid")]'):
                    return False, "Invalid phone number"
                
                # Send message
                message_box = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]'))
                )
                message_box.send_keys(Keys.ENTER)
                time.sleep(2)
                
                return True, "Message sent"
                
            except:
                # Alternative send method
                try:
                    send_button = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//button[@data-tab="11"]'))
                    )
                    send_button.click()
                    return True, "Message sent"
                except:
                    return False, "Failed to send"
                    
        except Exception as e:
            return False, str(e)
    
    def close(self):
        if self.driver:
            self.driver.quit()

# Global instance
whatsapp_instance = None
whatsapp_lock = threading.Lock()

def get_whatsapp():
    global whatsapp_instance
    if whatsapp_instance is None:
        whatsapp_instance = WhatsAppWebAutomation()
        whatsapp_instance.init_driver()
    return whatsapp_instance

# Routes
@app.route('/')
def index():
    templates_count = MessageTemplate.query.count()
    contacts_count = Contact.query.count()
    messages_sent = MessageLog.query.filter_by(status='sent').count()
    total_messages = MessageLog.query.count()
    success_rate = round((messages_sent / total_messages * 100) if total_messages > 0 else 0, 1)
    
    return render_template('dashboard.html', 
                         templates_count=templates_count,
                         contacts_count=contacts_count,
                         messages_sent=messages_sent,
                         success_rate=success_rate)

@app.route('/whatsapp/status')
def whatsapp_status():
    try:
        wa = get_whatsapp()
        is_logged_in = wa.check_login_status()
        return jsonify({
            'status': 'connected' if is_logged_in else 'disconnected',
            'logged_in': is_logged_in
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/whatsapp/login')
def whatsapp_login():
    try:
        wa = get_whatsapp()
        wa.driver.get("https://web.whatsapp.com")
        return jsonify({
            'status': 'success', 
            'message': 'WhatsApp Web opened. Please scan QR code in the browser console.',
            'url': 'https://web.whatsapp.com'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/send-message')
def send_message_page():
    templates = MessageTemplate.query.all()
    return render_template('send_message.html', templates=templates)

@app.route('/send-message/single', methods=['POST'])
def send_single_message():
    try:
        phone = request.form.get('phone')
        message = request.form.get('message')
        
        if not phone or not message:
            return jsonify({'status': 'error', 'message': 'Phone and message required'})
        
        with whatsapp_lock:
            wa = get_whatsapp()
            if not wa.check_login_status():
                return jsonify({'status': 'error', 'message': 'WhatsApp not logged in'})
            
            success, msg = wa.send_message(phone, message)
        
        log = MessageLog(phone_number=phone, status='sent' if success else 'failed')
        db.session.add(log)
        db.session.commit()
        
        return jsonify({'status': 'success' if success else 'error', 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/send-message/bulk', methods=['POST'])
def send_bulk_messages():
    try:
        template_id = request.form.get('template_id')
        
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'})
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Read contacts
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath)
            
            # Find phone column
            phone_col = None
            for col in ['phone', 'phone_number', 'Phone', 'Phone Number', 'mobile', 'Mobile']:
                if col in df.columns:
                    phone_col = col
                    break
            
            if phone_col is None:
                os.remove(filepath)
                return jsonify({'status': 'error', 'message': 'No phone column found'})
            
            phone_numbers = df[phone_col].dropna().tolist()
            
            # Get template
            template = MessageTemplate.query.get(template_id) if template_id else None
            message_content = template.content if template else request.form.get('message', '')
            
            if not message_content:
                os.remove(filepath)
                return jsonify({'status': 'error', 'message': 'No message content'})
            
            # Send in background
            def send_bulk():
                with app.app_context():
                    with whatsapp_lock:
                        wa = get_whatsapp()
                        if not wa.check_login_status():
                            return
                        
                        for i, phone in enumerate(phone_numbers):
                            try:
                                phone_str = str(phone).strip()
                                success, msg = wa.send_message(phone_str, message_content)
                                
                                log = MessageLog(
                                    template_id=template_id,
                                    phone_number=phone_str,
                                    status='sent' if success else 'failed'
                                )
                                db.session.add(log)
                                db.session.commit()
                                
                                if i < len(phone_numbers) - 1:
                                    time.sleep(3)  # Anti-spam delay
                            except:
                                continue
            
            thread = threading.Thread(target=send_bulk)
            thread.daemon = True
            thread.start()
            
            os.remove(filepath)
            
            return jsonify({
                'status': 'success',
                'message': f'Sending to {len(phone_numbers)} contacts'
            })
            
        except Exception as e:
            os.remove(filepath)
            return jsonify({'status': 'error', 'message': str(e)})
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/templates')
def manage_templates():
    templates = MessageTemplate.query.all()
    return render_template('templates.html', templates=templates)

@app.route('/templates/create', methods=['POST'])
def create_template():
    try:
        name = request.form.get('name')
        content = request.form.get('content')
        
        if not name or not content:
            flash('Name and content are required', 'error')
            return redirect(url_for('manage_templates'))
        
        template = MessageTemplate(name=name, content=content)
        db.session.add(template)
        db.session.commit()
        
        flash('Template created successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('manage_templates'))

@app.route('/templates/delete/<int:id>')
def delete_template(id):
    template = MessageTemplate.query.get_or_404(id)
    db.session.delete(template)
    db.session.commit()
    flash('Template deleted!', 'success')
    return redirect(url_for('manage_templates'))

@app.route('/contacts')
def manage_contacts():
    contacts = Contact.query.all()
    return render_template('contacts.html', contacts=contacts)

@app.route('/contacts/upload', methods=['POST'])
def upload_contacts():
    try:
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(url_for('manage_contacts'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('manage_contacts'))
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        if filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)
        
        contacts_added = 0
        for _, row in df.iterrows():
            try:
                phone = None
                name = None
                
                for col in df.columns:
                    col_lower = col.lower()
                    if 'phone' in col_lower or 'mobile' in col_lower:
                        phone = str(row[col]).strip()
                    if 'name' in col_lower:
                        name = str(row[col]).strip()
                
                if phone:
                    existing = Contact.query.filter_by(phone_number=phone).first()
                    if not existing:
                        contact = Contact(name=name, phone_number=phone)
                        db.session.add(contact)
                        contacts_added += 1
            except:
                continue
        
        db.session.commit()
        os.remove(filepath)
        
        flash(f'{contacts_added} contacts added!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('manage_contacts'))

@app.route('/message-logs')
def message_logs():
    logs = MessageLog.query.order_by(MessageLog.sent_at.desc()).limit(100).all()
    return render_template('message_logs.html', logs=logs)

# Create tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)