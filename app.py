

# Import all the libraries we need
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from datetime import datetime
import pytz
import pandas as pd
from io import BytesIO
import os

# Create the Flask application
app = Flask(__name__)
CORS(app)

# Connect to MongoDB database
mongodb_client = MongoClient('mongodb://localhost:27017/')
database = mongodb_client['email_scheduler_db']
schedules_collection = database['schedules']
sent_logs_collection = database['sent_logs']

# Email configuration
SMTP_SERVER_ADDRESS = 'smtp.gmail.com'
SMTP_SERVER_PORT = 587
SENDER_EMAIL_ADDRESS = 'geethveer27@gmail.com'
SENDER_EMAIL_PASSWORD = 'zhcucbiduafbllrb'

# Create scheduler for background tasks
background_scheduler = BackgroundScheduler()
background_scheduler.start()


def get_weather_data_from_api(latitude_value, longitude_value):
    """
    This function gets weather data from the Open-Meteo API
    """
    try:
        weather_api_url = f'https://api.open-meteo.com/v1/forecast?latitude={latitude_value}&longitude={longitude_value}&current_weather=true'
        api_response = requests.get(weather_api_url)
        weather_data = api_response.json()
        return weather_data
    except Exception as error:
        print(f'Error getting weather data: {error}')
        return None


def send_email_via_smtp(recipient_email, subject_line, email_body_content):
    """
    This function sends an email using SMTP
    """
    try:
        email_message = MIMEMultipart()
        email_message['From'] = SENDER_EMAIL_ADDRESS
        email_message['To'] = recipient_email
        email_message['Subject'] = subject_line
        
        email_message.attach(MIMEText(email_body_content, 'plain'))
        
        smtp_server = smtplib.SMTP(SMTP_SERVER_ADDRESS, SMTP_SERVER_PORT)
        smtp_server.starttls()
        smtp_server.login(SENDER_EMAIL_ADDRESS, SENDER_EMAIL_PASSWORD)
        
        email_text = email_message.as_string()
        smtp_server.sendmail(SENDER_EMAIL_ADDRESS, recipient_email, email_text)
        smtp_server.quit()
        
        print(f'Email sent successfully to {recipient_email}')
        return True
        
    except Exception as error:
        print(f'Error sending email: {error}')
        return False


def compose_email_content(schedule_data, weather_data):
    """
    This function creates the email content with weather information
    """
    current_temperature = weather_data['current_weather']['temperature']
    current_windspeed = weather_data['current_weather']['windspeed']
    weather_time = weather_data['current_weather']['time']
    
    email_content = f"""
Hello!

This is your scheduled email with weather information.

Current Weather Report:
- Temperature: {current_temperature} degrees Celsius
- Wind Speed: {current_windspeed} km/h
- Time: {weather_time}
- Location: Latitude {weather_data['latitude']}, Longitude {weather_data['longitude']}

This email was scheduled for: {schedule_data['scheduled_time']}
Timezone: {schedule_data['timezone']}

Best regards,
Email Scheduler System
    """
    
    return email_content


def check_and_send_scheduled_emails():
    """
    This function checks if any emails need to be sent now
    """
    print('Checking for emails to send...')
    
    current_time = datetime.now(pytz.UTC)
    pending_schedules = schedules_collection.find({'status': 'pending'})
    
    for schedule in pending_schedules:
        scheduled_datetime = schedule['scheduled_time']
        schedule_timezone = pytz.timezone(schedule['timezone'])
        
        if isinstance(scheduled_datetime, str):
            scheduled_datetime = datetime.fromisoformat(scheduled_datetime.replace('Z', '+00:00'))
        
        if scheduled_datetime.tzinfo is None:
            scheduled_datetime = schedule_timezone.localize(scheduled_datetime)
        
        scheduled_datetime_utc = scheduled_datetime.astimezone(pytz.UTC)
        
        if current_time >= scheduled_datetime_utc:
            print(f'Time to send email for schedule {schedule["_id"]}')
            
            weather_data = get_weather_data_from_api(
                schedule['latitude'],
                schedule['longitude']
            )
            
            if weather_data:
                email_content = compose_email_content(schedule, weather_data)
                
                # ✅ ACTUALLY SEND THE EMAIL VIA SMTP
                email_sent = send_email_via_smtp(
                    schedule['recipient'],
                    schedule['subject'],
                    email_content
                )
                
                if email_sent:
                    print('=' * 50)
                    print('✅ EMAIL SENT SUCCESSFULLY!')
                    print(f'To: {schedule["recipient"]}')
                    print(f'Subject: {schedule["subject"]}')
                    print('=' * 50)
                    
                    # Update status to sent
                    schedules_collection.update_one(
                        {'_id': schedule['_id']},
                        {'$set': {'status': 'sent'}}
                    )
                    
                    # Log the sent email
                    log_entry = {
                        'schedule_id': str(schedule['_id']),
                        'recipient': schedule['recipient'],
                        'subject': schedule['subject'],
                        'content': email_content,
                        'weather_data': weather_data,
                        'sent_at': datetime.now(pytz.UTC)
                    }
                    sent_logs_collection.insert_one(log_entry)
                else:
                    print(f'❌ Failed to send email to {schedule["recipient"]}')
                    print('Check your email credentials in app.py')
            else:
                print(f'❌ Failed to get weather data for schedule {schedule["_id"]}')
@app.route('/api/schedules', methods=['POST'])
def create_new_schedule():
    """
    API endpoint to create a new email schedule
    """
    try:
        request_data = request.get_json()
        
        recipient_email = request_data.get('recipient')
        subject_line = request_data.get('subject')
        scheduled_time = request_data.get('scheduled_time')
        timezone_value = request_data.get('timezone', 'UTC')
        latitude_value = request_data.get('latitude', '25.276987')
        longitude_value = request_data.get('longitude', '55.296249')
        
        if not recipient_email or not subject_line or not scheduled_time:
            return jsonify({'error': 'Missing required fields'}), 400
        
        new_schedule = {
            'recipient': recipient_email,
            'subject': subject_line,
            'scheduled_time': scheduled_time,
            'timezone': timezone_value,
            'latitude': latitude_value,
            'longitude': longitude_value,
            'status': 'pending',
            'created_at': datetime.now(pytz.UTC)
        }
        
        result = schedules_collection.insert_one(new_schedule)
        
        return jsonify({
            'message': 'Schedule created successfully',
            'schedule_id': str(result.inserted_id)
        }), 201
        
    except Exception as error:
        print(f'Error creating schedule: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/schedules', methods=['GET'])
def get_all_schedules():
    """
    API endpoint to get all email schedules
    """
    try:
        all_schedules = list(schedules_collection.find())
        
        for schedule in all_schedules:
            schedule['_id'] = str(schedule['_id'])
            schedule['created_at'] = schedule['created_at'].isoformat()
            if isinstance(schedule['scheduled_time'], datetime):
                schedule['scheduled_time'] = schedule['scheduled_time'].isoformat()
        
        return jsonify(all_schedules), 200
        
    except Exception as error:
        print(f'Error getting schedules: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/schedules/<schedule_id>', methods=['GET'])
def get_single_schedule(schedule_id):
    """
    API endpoint to get one specific schedule
    """
    try:
        from bson.objectid import ObjectId
        
        schedule = schedules_collection.find_one({'_id': ObjectId(schedule_id)})
        
        if not schedule:
            return jsonify({'error': 'Schedule not found'}), 404
        
        schedule['_id'] = str(schedule['_id'])
        schedule['created_at'] = schedule['created_at'].isoformat()
        if isinstance(schedule['scheduled_time'], datetime):
            schedule['scheduled_time'] = schedule['scheduled_time'].isoformat()
        
        return jsonify(schedule), 200
        
    except Exception as error:
        print(f'Error getting schedule: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/schedules/<schedule_id>/cancel', methods=['PUT'])
def cancel_schedule(schedule_id):
    """
    API endpoint to cancel a schedule
    """
    try:
        from bson.objectid import ObjectId
        
        result = schedules_collection.update_one(
            {'_id': ObjectId(schedule_id)},
            {'$set': {'status': 'cancelled'}}
        )
        
        if result.matched_count == 0:
            return jsonify({'error': 'Schedule not found'}), 404
        
        return jsonify({'message': 'Schedule cancelled successfully'}), 200
        
    except Exception as error:
        print(f'Error cancelling schedule: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/schedules/<schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    """
    API endpoint to delete a schedule
    """
    try:
        from bson.objectid import ObjectId
        
        result = schedules_collection.delete_one({'_id': ObjectId(schedule_id)})
        
        if result.deleted_count == 0:
            return jsonify({'error': 'Schedule not found'}), 404
        
        return jsonify({'message': 'Schedule deleted successfully'}), 200
        
    except Exception as error:
        print(f'Error deleting schedule: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/logs', methods=['GET'])
def get_sent_logs():
    """
    API endpoint to get all sent email logs
    """
    try:
        all_logs = list(sent_logs_collection.find())
        
        for log in all_logs:
            log['_id'] = str(log['_id'])
            log['sent_at'] = log['sent_at'].isoformat()
        
        return jsonify(all_logs), 200
        
    except Exception as error:
        print(f'Error getting logs: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/schedules/upload', methods=['POST'])
def upload_schedules_from_excel():
    """
    API endpoint to upload schedules from Excel or CSV file
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename.endswith('.csv'):
            dataframe = pd.read_csv(file)
        elif file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
            dataframe = pd.read_excel(file)
        else:
            return jsonify({'error': 'Invalid file format. Use CSV or Excel'}), 400
        
        schedules_created = 0
        
        for index, row in dataframe.iterrows():
            try:
                new_schedule = {
                    'recipient': str(row['recipient']),
                    'subject': str(row['subject']),
                    'scheduled_time': str(row['scheduled_time']),
                    'timezone': str(row.get('timezone', 'UTC')),
                    'latitude': str(row.get('latitude', '25.276987')),
                    'longitude': str(row.get('longitude', '55.296249')),
                    'status': 'pending',
                    'created_at': datetime.now(pytz.UTC)
                }
                
                schedules_collection.insert_one(new_schedule)
                schedules_created += 1
                
            except Exception as row_error:
                print(f'Error processing row {index}: {row_error}')
                continue
        
        return jsonify({
            'message': f'Successfully created {schedules_created} schedules',
            'count': schedules_created
        }), 201
        
    except Exception as error:
        print(f'Error uploading file: {error}')
        return jsonify({'error': str(error)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    API endpoint to check if service is running
    """
    return jsonify({'status': 'ok', 'message': 'Email Scheduler is running'}), 200


background_scheduler.add_job(
    func=check_and_send_scheduled_emails,
    trigger='interval',
    minutes=1,
    id='email_checker_job',
    name='Check and send scheduled emails',
    replace_existing=True
)


if __name__ == '__main__':
    print('Starting Email Scheduler Service...')
    print('Scheduler is checking for emails every minute')
    print('API is running on http://localhost:5000')
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
