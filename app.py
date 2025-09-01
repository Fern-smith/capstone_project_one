import os
import uuid
import psycopg2
import psycopg2.extras
import sys
import secrets
import urllib.request 
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from psycopg2 import sql, pool
from psycopg2.pool import ThreadedConnectionPool 
import requests
from datetime import datetime
import json
import time
from functools import wraps
from urllib.parse import urlparse
from PIL import Image
import io
import boto3
from botocore.exceptions import ClientError 
import logging

# Check if Pillow (PIL) is available for image processing
try:
    from PIL import Image
    IMAGE_PROCESSING_AVAILABLE = True
except ImportError:
    IMAGE_PROCESSING_AVAILABLE = False
from logging.handlers import RotatingFileHandler
from markupsafe import Markup
import re
from html import unescape

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

#Configure logging for production 
if not app.debug and os.environ.get('FLASK_ENV') == 'production':
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/recipe_app.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Recipe app startup')

# AWS S3 Configuration 
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
AWS_S3_REGION = os.environ.get('AWS_S3_REGION', 'us-east-1')

# Initialize S3 client 
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET: 
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID, 
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION
    )
    print(f"✅ AWS S3 configured: {AWS_S3_BUCKET}")
else: 
    s3_client = None
    print("⚠️  AWS S3 not configured. Check your environment variables.")
    
# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if 'DATABASE_URL' in os.environ:
      DATABASE_URL = os.environ['DATABASE_URL']
      url = urlparse(DATABASE_URL)
      DATABASE_CONFIG = {
        'host': url.hostname,
        'database': url.path[1:],
        'user': url.username,
        'password': url.password,
        'port': url.port or 5432,
        'sslmode': 'require'  
      }
      print(f"🐘 Using Neon.tech PostgreSQL: {url.hostname}")
else:
    print("❌DATABASE_URL not set!")
    exit(1)

# Spoonacular API configuration
SPOONACULAR_API_KEY = os.environ.get('SPOONACULAR_API_KEY')
SPOONACULAR_BASE_URL = 'https://api.spoonacular.com/recipes'

if not SPOONACULAR_API_KEY:
    print("⚠️  Warning: SPOONACULAR_API_KEY not set. API features will be disabled.")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Database connection helper
def get_db_connection():
    """Simple database connection without pooling"""
    try:
        conn = psycopg2.connect(**DATABASE_CONFIG)
        return conn
    except psycopg2.Error as e:
        print(f"❌ Error connecting to PostgreSQL: {e}")
        print(f"🔧 Check your DATABASE_CONFIG settings:")
        print(f"   Host: {DATABASE_CONFIG['host']}")
        print(f"   Database: {DATABASE_CONFIG['database']}")
        print(f"   User: {DATABASE_CONFIG['user']}")
        print(f"   Port: {DATABASE_CONFIG['port']}")
        if 'DATABASE_URL' in os.environ:
            print(f"💡 Make sure your Neon.tech DATABASE_URL is correct")
        else:
            print(f"💡 Make sure PostgreSQL is running and the database exists")
        if app.logger: 
            app.logger.error(f"Database connection failed: {e}")
        return None

def close_db_connection(conn):
    """Simple connection close"""
    if conn: 
        conn.close()

    
def clean_html_content(content):
    """Clean HTML content and return safe text"""
    if not content:
        return ""
    
    # First unescape HTML entities
    content = unescape(content)
    
    # Remove HTML tags using regex
    clean_text = re.sub(r'<[^>]+>', '', content)
    
    # Remove extra whitespace
    clean_text = ' '.join(clean_text.split())
    
    return clean_text


# AWS S3 Helper Functions
def upload_image_to_s3(image_data, filename, content_type='image/jpeg'):
    """Upload image data to S3 bucket with public read access"""
    if not s3_client:
        print("❌ S3 client not configured")
        return None
    
    try:
        # Upload to S3
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=filename,
            Body=image_data,
            ContentType=content_type,
            CacheControl='max-age=31536000', # Cache for 1 year
            ACL='public-read' #Make the object publicly readable.
        )
        
        # Generate S3 URL
        s3_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{filename}"
        print(f"✅ Image uploaded to S3: {s3_url}")
        return s3_url
    
    except ClientError as e:
        print(f"❌ Error uploading to S3: {e}")
        #If ACL fails, try without it 
        try: 
            s3_client.put_object(
                Bucket=AWS_S3_BUCKET,
                Key=filename,
                Body=image_data,
                ContentType=content_type,
                CacheControl='max-age=31536000'
            )
            s3_url = generate_public_s3_url(filename)
            print(f"✅ Image uploaded to S3 (no ACL): {s3_url}")
            return s3_url
        except Exception as e2:
            print(f"❌ Error uploading to S3 (retry): {e2}")
        return None

def save_image_locally(file, title="recipe"):
    """Save uploaded image to local static folder as fallback"""
    if not file or not file.filename:
        return None
    #create uploads directory if it doesn't exist 
    upload_dir = os.path.join(os.getcwd(), 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    try:
        # Generate unique filename
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        if file_ext not in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            return None
        
        unique_filename = f"{uuid.uuid4().hex}.{file_ext}"
        file_path = os.path.join(upload_dir, unique_filename)
        
        # Process and save image
        image = Image.open(file.stream)
        
        # Convert to RGB if needed
        if image.mode in ('RGBA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if 'A' in image.mode else None)
            image = background
        
        # Resize if too large
        if image.width > 800 or image.height > 600:
            image.thumbnail((800, 600), Image.Resampling.LANCZOS)
        
        # Save image
        image.save(file_path, 'JPEG', quality=85, optimize=True)
        
        # Return URL path for Flask
        return f"/static/uploads/{unique_filename}"
        
    except Exception as e:
        print(f"Error saving image locally: {e}")
        return None

def process_and_upload_user_image(file):
    """Process user uploaded file and upload to S3 with better error handling"""
    if not file or not file.filename:
        print("❌ No file provided")
        return None
    
    # Check if S3 is available
    if not s3_client:
        print("⚠️ S3 not configured - saving without image")
        return None
    
    # Check file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    
    if file_extension not in allowed_extensions:
        print(f"❌ Invalid file type: {file_extension}")
        return None
    
    try:
        # Read file data
        file_data = file.read()
        file.seek(0)  # Reset file pointer
        
        if len(file_data) == 0:
            print("❌ Empty file")
            return None
        
        # Check if we have PIL available
        if not IMAGE_PROCESSING_AVAILABLE:
            print("⚠️ PIL not available - uploading without processing")
            # Upload raw file
            unique_id = str(uuid.uuid4())
            filename = f"recipes/{unique_id}.{file_extension}"
            return upload_image_to_s3(file_data, filename, f'image/{file_extension}')
        
        # Process with Pillow
        try:
            with Image.open(io.BytesIO(file_data)) as img:
                # Verify it's actually an image
                img.verify()
        except Exception as e:
            print(f"❌ Invalid image file: {e}")
            return None
        
        # Reopen for processing (verify closes the image)
        with Image.open(io.BytesIO(file_data)) as img:
            # Convert to RGB if needed
            if img.mode in ('RGBA', 'P', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if 'A' in img.mode:
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            
            # Resize if too large
            if img.width > 800 or img.height > 600:
                img.thumbnail((800, 600), Image.Resampling.LANCZOS)
            
            # Convert to bytes
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', optimize=True, quality=85)
            img_buffer.seek(0)
            
            # Generate filename
            unique_id = str(uuid.uuid4())
            filename = f"recipes/{unique_id}.jpg"
            
            # Upload to S3
            s3_url = upload_image_to_s3(img_buffer.getvalue(), filename, 'image/jpeg')
            if s3_url:
                print(f"✅ Image uploaded successfully: {s3_url}")
            else:
                print("❌ S3 upload failed")
            return s3_url
            
    except Exception as e:
        print(f"❌ Error processing user image: {e}")
        import traceback
        traceback.print_exc()
        return None

def upload_image_to_s3(image_data, filename, content_type='image/jpeg'):
    """Upload image data to S3 bucket with better error handling"""
    if not s3_client:
        print("❌ S3 client not configured")
        return None
    
    if not AWS_S3_BUCKET:
        print("❌ S3 bucket not configured")
        return None
    
    try:
        # Upload to S3
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=filename,
            Body=image_data,
            ContentType=content_type,
            CacheControl='max-age=31536000',  # Cache for 1 year
            # Make sure the object is publicly readable
            ACL='public-read'
        )
        
        # Generate S3 URL
        s3_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{filename}"
        print(f"✅ Image uploaded to S3: {s3_url}")
        
        # Test if the URL is accessible
        try:
            import requests
            response = requests.head(s3_url, timeout=5)
            if response.status_code == 200:
                print("✅ Image URL is accessible")
            else:
                print(f"⚠️ Image URL returned status: {response.status_code}")
        except:
            print("⚠️ Could not verify image URL accessibility")
        
        return s3_url
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"❌ S3 ClientError ({error_code}): {e}")
        return None
    except Exception as e:
        print(f"❌ Error uploading to S3: {e}")
        return None

def download_and_upload_to_s3(image_url, recipe_title="recipe"):
    """Download image from URL and upload to S3 with fallback to original URL"""
    if not image_url:
        return None
    
    # If S3 is not configured, return the original URL
    if not s3_client:
        print("⚠️ S3 not configured - using original image URL")
        return image_url
    
    try:
        # Generate unique filename
        unique_id = str(uuid.uuid4())
        filename = f"recipes/{unique_id}.jpg"
        
        # Download image with better headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        import requests
        response = requests.get(image_url, headers=headers, timeout=15, stream=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            print(f"❌ Not an image: {content_type}")
            return image_url  # Return original URL
        
        # Read image data
        image_data = response.content
        
        if not IMAGE_PROCESSING_AVAILABLE:
            # Upload without processing
            return upload_image_to_s3(image_data, filename, 'image/jpeg')
        
        # Process image with Pillow
        with Image.open(io.BytesIO(image_data)) as img:
            # Convert to RGB if needed
            if img.mode in ('RGBA', 'P', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if 'A' in img.mode:
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            
            # Resize if too large
            if img.width > 800 or img.height > 600:
                img.thumbnail((800, 600), Image.Resampling.LANCZOS)
            
            # Convert to bytes
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', optimize=True, quality=85)
            img_buffer.seek(0)
            
            # Upload to S3
            s3_url = upload_image_to_s3(img_buffer.getvalue(), filename, 'image/jpeg')
            return s3_url if s3_url else image_url  # Fallback to original URL
            
    except Exception as e:
        print(f"❌ Error downloading and uploading image: {e}")
        print(f"🔄 Using original image URL: {image_url}")
        return image_url  

def generate_public_s3_url(filename):
    """Generate a public S3 URL"""
    if not AWS_S3_BUCKET or not filename: 
        return None
    
     # Use the public URL format
    return f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{filename}"
   
# Test database connection
def test_db_connection():
    print("🔍 Testing database connection...")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('SELECT version();')
            version = cur.fetchone()
            print(f"✅ PostgreSQL connection successful!")
            print(f"📊 PostgreSQL version: {version[0][:50]}...")
            cur.close()
            close_db_connection(conn)
            return True
        except Exception as e:
            print(f"❌ Error testing connection: {e}")
            close_db_connection(conn)
            return False
    else:
        print("❌ Could not establish database connection")
        return False

# Database setup

def init_db():
    print("🏗️  Initializing database tables...")
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database for initialization")
        return False
    try:
        cur = conn.cursor()
        
        # Users table
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        # Recipes table
        cur.execute('''CREATE TABLE IF NOT EXISTS recipes (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(255) NOT NULL,
                        description TEXT,
                        ingredients TEXT NOT NULL,
                        steps TEXT NOT NULL,
                        image_url VARCHAR(500),
                        author_id INTEGER REFERENCES users(id),
                        spoonacular_id INTEGER,
                        source VARCHAR(50) DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        conn.commit()
        print("✅ Database tables created successfully!")
        
        #Verify tables exist 
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
        tables = cur.fetchall()
        print(f"📋 Tables in database: {[table[0] for table in tables]}")
        
        return True 
        
    except psycopg2.Error as e: 
        print(f"❌ Error creating tables: {e}") 
        conn.rollback()
        return False
    finally: 
        cur.close()
        close_db_connection(conn)
                        
# Spoonacular API functions
def search_recipes_api(query, number=12):
    """Search recipes using Spoonacular API"""
    if not SPOONACULAR_API_KEY:
        print("⚠️  Spoonacular API key not configured")
        return None
        
    try:
        url = f"{SPOONACULAR_BASE_URL}/complexSearch"
        params = {
            'apiKey': SPOONACULAR_API_KEY,
            'query': query,
            'number': number,
            'addRecipeInformation': True,
            'fillIngredients': True
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e: 
        print(f"Error searching recipes: {e}")
        return None 

def get_recipe_details_api(recipe_id):
    """Get detailed recipe information from Spoonacular API"""
    if not SPOONACULAR_API_KEY:
        print("⚠️  Spoonacular API key not configured")
        return None
        
    try:
        url = f"{SPOONACULAR_BASE_URL}/{recipe_id}/information"
        params = {
            'apiKey': SPOONACULAR_API_KEY,
            'includeNutrition': True
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting recipe details: {e}")
        return None

def format_ingredients(ingredients_list):
    """Format ingredients list for database storage with HTML Cleaning"""
    if not ingredients_list:
        return ""
    
    formatted = []
    for ingredient in ingredients_list:
        if isinstance(ingredient, dict):
            amount = clean_html_content(str(ingredient.get('amount', '')))
            unit = clean_html_content(str(ingredient.get('unit', '')))
            name = clean_html_content(str(ingredient.get('name', ingredient.get('original', ''))))
            
            ingredient_text = f"{amount} {unit} {name}".strip()
            ingredient_text = ' '.join(ingredient_text.split())
            formatted.append(f"• {ingredient_text}")
        else:
            clean_ingredient = clean_html_content(str(ingredient))
            if clean_ingredient: 
                formatted.append(f"• {clean_ingredient}")
    
    return "\n".join(formatted)

def format_instructions(instructions_list):
    """Format instructions list for database storage"""
    if not instructions_list:
        return ""
    
    formatted = []
    for i, instruction in enumerate(instructions_list, 1):
        if isinstance(instruction, dict):
            step = clean_html_content(str(instruction.get('step', instruction.get('text', ''))))
        else:
            step = clean_html_content(str(instruction))
        
        if step:
            formatted.append(f"{i}. {step}")
    
    return "\n".join(formatted)

@app.template_filter('clean_html')
def clean_html_filter(content):
    """Template filter to clean HTML content"""
    return clean_html_content(content)

#Health check endpoint for AWS load balancers
@app.route('/health')
def health_check():
    """Health check endpoint for AWS load balancers"""
    try: 
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute('SELECT 1')
            result = cur.fetchone()
            cur.close()
            close_db_connection(conn)
            
            db_status = "healthy" if result else "unhealthy"
        else: 
            db_status = "unhealthy"
            
        #check S3 connection 
        s3_status = "healthy" if s3_client else "not_configured"
        
        overall_status = "healthy" if db_status == "healthy" and s3_status == "healthy" else "unhealthy"
        
        response = {
            'status': overall_status, 
            'database': db_status,
            's3': s3_status,
            'timestamp': datetime.now(). isoformat(),
            'version': '1.0.0'
        }
        
        status_code = 200 if overall_status == "healthy" else 503 
        return jsonify(response), status_code
    
    except Exception as e: 
        return jsonify({
            'status': 'unhealthy', 
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 503

# Routes
@app.route('/')
def home():
    print("🏠 Home route accessed")
    
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'error')
        return render_template('home.html', featured_recipes=[])
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('''SELECT r.*, u.email 
                    FROM recipes r
                    LEFT JOIN users u ON r.author_id = u.id 
                    ORDER BY r.created_at DESC 
                    LIMIT 4''')
        featured_recipes = cur.fetchall()
        print(f"✅ Found {len(featured_recipes)} featured recipes")
        
    except psycopg2.Error as e:
        print(f"❌ Error fetching recipes: {e}")
        featured_recipes = []
    finally:
        cur.close()
        close_db_connection(conn)
    
    return render_template('home.html', featured_recipes=featured_recipes)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    search_results = {'local': [], 'api': []}
    
    if query:
        # Search in local database
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                cur.execute('''SELECT r.*, u.email 
                               FROM recipes r
                               LEFT JOIN users u ON r.author_id = u.id 
                               WHERE r.title ILIKE %s OR r.description ILIKE %s
                               ORDER BY r.created_at DESC''', 
                            (f'%{query}%', f'%{query}%'))
                search_results['local'] = cur.fetchall()
            except psycopg2.Error as e:
                print(f"Error searching local recipes: {e}")
            finally:
                cur.close()
                close_db_connection(conn)
        
        # Search using Spoonacular API
        api_results = search_recipes_api(query)
        if api_results:
            search_results['api'] = api_results['results']
    
    return render_template('search.html', query=query, search_results=search_results)

@app.route('/api_recipe/<int:spoonacular_id>')
def api_recipe_detail(spoonacular_id):
    """Display recipe details from Spoonacular API"""
    print(f"🔍 Requesting recipe ID: {spoonacular_id}")
    print(f"🔑 API Key configured: {'Yes' if SPOONACULAR_API_KEY else 'No'}")
    
    recipe_data = get_recipe_details_api(spoonacular_id)
    print(f"📊 Recipe data type: {type(recipe_data)}")
    print(f"📊 Recipe data: {recipe_data is not None}")
    
    if recipe_data:
        print(f"📊 Recipe keys: {list(recipe_data.keys()) if isinstance(recipe_data, dict) else 'Not a dict'}")
    
    if not recipe_data:
        flash('Recipe not found', 'error')
        return redirect(url_for('home'))
    
    return render_template('api_recipe_detail.html', recipe=recipe_data)

# ... (existing code)

@app.route('/api/search')
def api_search():
    """
    Search for recipes from the Spoonacular API
    """
    query = request.args.get('q', '')
    if not SPOONACULAR_API_KEY:
        return jsonify({'error': 'Spoonacular API key is not configured'}), 500

    if not query:
        return jsonify([])

    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/complexSearch",
            params={
                "apiKey": SPOONACULAR_API_KEY,
                "query": query,
                "number": 10,
                "addRecipeInformation": True,
                "addRecipeNutrition": True,
            },
            timeout=10,
        )
        response.raise_for_status()
        search_data = response.json()
        results = search_data.get('results', [])
        
        api_recipes = []
        for res in results:
            image_url = res.get('image')
            
            # Use `download_and_upload_to_s3` to handle image URL
            processed_image_url = download_and_upload_to_s3(image_url, res.get('title'))
            
            # Use the processed URL
            res['image'] = processed_image_url
            api_recipes.append(res)
            
        return jsonify(api_recipes)

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Spoonacular API request failed: {e}")
        return jsonify({'error': 'Failed to retrieve recipes from external API.'}), 500


@app.route('/save_api_recipe/<int:spoonacular_id>', methods=['POST'])
@login_required
# 
def save_api_recipe(spoonacular_id):
    """Save a recipe from Spoonacular API to local database"""
    recipe_data = get_recipe_details_api(spoonacular_id)
    
    if not recipe_data:
        flash('Recipe not found', 'error')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'error')
        return redirect(url_for('home'))
    
    try:
        cur = conn.cursor()
        
        # Check if recipe already exists
        cur.execute('SELECT id FROM recipes WHERE spoonacular_id = %s', (spoonacular_id,))
        existing = cur.fetchone()
        
        if existing:
            flash('Recipe already saved!', 'info')
            return redirect(url_for('recipe_detail', recipe_id=existing[0]))
        
        # Format data for database
        title = recipe_data.get('title', '')
        
        #clean description and limit length
        raw_description = recipe_data.get('summary', '')
        description = clean_html_content(raw_description)[:500] if raw_description else ''
        
        #Format ingredient and instructions with html cleaning
        ingredients = format_ingredients(recipe_data.get('extendedIngredients', []))
        
        # Get instructions
        instructions = recipe_data.get('analyzedInstructions', [])
        steps = ""
        if instructions and len(instructions) > 0:
            steps = format_instructions(instructions[0].get('steps', []))
        elif recipe_data.get('instructions'):
            # Fallback to raw instructions if analyzedInstructions not available
            steps = clean_html_content(recipe_data['instructions'])    
        
        # Download and upload image to S3
        image_url = None
        if recipe_data.get('image'):
            print(f"📥 Downloading and uploading image to S3: {recipe_data['image']}")
            image_url = download_and_upload_to_s3(recipe_data['image'], title)
            if image_url:
                print(f"✅ Image uploaded to S3: {image_url}")
            else:
                print("⚠️ Failed to upload image to S3, using original URL")
                # Fallback to original URL if S3 upload fails
                image_url = recipe_data['image']
         
    
        # Save to database with S3 URL
        cur.execute('''INSERT INTO recipes (title, description, ingredients, steps, image_url, author_id, spoonacular_id, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                    (title, description, ingredients, steps, image_url, session['user_id'], spoonacular_id, 'spoonacular'))
        
        recipe_id = cur.fetchone()[0]
        conn.commit()
        
        if image_url and image_url.startswith('https'):
            flash('Recipe and image saved successfully!', 'success')
        else:
            flash('Recipe saved successfully! (Image upload failed)', 'warning')
        
        return redirect(url_for('recipe_detail', recipe_id=recipe_id))
        
    except psycopg2.Error as e:
        print(f"Error saving recipe: {e}")
        conn.rollback()
        flash('Error saving recipe', 'error')
        return redirect(url_for('home'))
    finally:
        cur.close()
        close_db_connection(conn)

@app.route('/debug/images')
def debug_images():
    """Debug route to check image URLs"""
    conn = get_db_connection()
    if not conn: 
        return "Database connection error"
    
    try: 
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id, title, image_url FROM recipes WHERE image_url IS NOT NULL LIMIT 10")
        recipes = cur.fetchall()
        
        html = "<h1>Image Debug</h1>"
        html += f"<p>S3 Configured: {'Yes' if s3_client else 'No'}</p>"
        html += f"<p>S3 Bucket: {AWS_S3_BUCKET}</p><hr>"
        
        for recipe in recipes:
            html += f"<div style='border: 1px solid #ccc; margin: 10px; padding: 10px;'>"
            html += f"<h3>{recipe['title']}</h3>"
            html += f"<p><strong>URL:</strong> {recipe['image_url']}</p>"
            
            if recipe['image_url']:
                html += f"<img src='{recipe['image_url']}' style='max-width: 200px; max-height: 150px;' "
                html += f"onerror='this.style.border=\"2px solid red\"; this.alt=\"Failed to load\";' />"
            else:
                html += "<p>No image URL</p>"
            
            html += "</div>"
        
        return html
        
    except Exception as e:
        return f"Error: {e}"
    finally:
        if 'cur' in locals():
            cur.close()
        close_db_connection(conn)    

def configure_s3_bucket():
    """Configure S3 bucket for public read access"""
    if not s3_client or not AWS_S3_BUCKET:
        print("⚠️ S3 not configured")
        return False
    
    try:
        # Check if bucket exists
        s3_client.head_bucket(Bucket=AWS_S3_BUCKET)
        print(f"✅ S3 bucket {AWS_S3_BUCKET} exists")
        
        # Set CORS configuration
        cors_configuration = {
            'CORSRules': [
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedOrigins': ['*'],
                    'MaxAgeSeconds': 3000
                }
            ]
        }
        
        s3_client.put_bucket_cors(
            Bucket=AWS_S3_BUCKET,
            CORSConfiguration=cors_configuration
        )
        print("✅ CORS configuration set")
        
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"❌ S3 bucket {AWS_S3_BUCKET} does not exist")
        else:
            print(f"❌ Error configuring S3: {e}")
        return False


@app.route('/login', methods=['GET', 'POST'])
# @csrf_required
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'error')
            return redirect(url_for('login'))
        
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cur.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['user_email'] = user['email']
                # Personalized welcome message
                flash(f"Welcome back, {user['email'].split('@')[0].title()}!", 'success')
                return redirect(url_for('home'))
            else:
                flash('Login failed, Please check your email or password', 'error')
                
        except psycopg2.Error as e:
            print(f"Error during login: {e}")
            flash('Login error occurred', 'error')
        finally:
            if 'cur' in locals() and cur is not None:
                cur.close()
            close_db_connection(conn)
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
# @csrf_required
def signup():
    if  request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'error')
            return redirect(url_for('signup'))  
        
        try:
            cur = conn.cursor()
            
            # Check if user already exists
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            if cur.fetchone():
                flash('An account with that Email already registered', 'warning')
            else:
                cur.execute('INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id',
                        (email, hashed_password))
                user_id = cur.fetchone()[0]
                conn.commit()
                
                session.clear()
                session['user_id'] = user_id
                session['user_email'] = email
                
                flash('Account created successfully! You are now logged in.', 'success')
                return redirect(url_for('home'))
        except psycopg2.Error as e:
                conn.rollback()
                print(f"Error during signup: {e}", file=sys.stderr)
                flash('An error occurred during signup.', 'error')
        finally:
            if 'cur' in locals() and cur is not None:
                cur.close()
            close_db_connection(conn)
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))

@app.route('/create_recipe', methods=['GET', 'POST'])
@login_required
def create_recipe():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        ingredients = request.form['ingredients']
        steps = request.form['steps']
        
        # Handle image upload with fallbacks
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                   image_url = process_and_upload_user_image(file)
              
        conn = get_db_connection()
        if conn is None:
            flash('Database connection error', 'error')
            return redirect(url_for('create_recipe'))
        
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(
                '''INSERT INTO recipes (title, description, ingredients, steps, image_url, user_id, author_info)
                           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id; 
                ''',
                (title, description, ingredients, steps, image_url, session['user_id'], session.get('user_email', 'Anonymous'))
            )
            recipe_id = cur.fetchone()['id']       
            conn.commit()
            flash('Recipe created successfully!', 'success')
            return redirect(url_for('recipe_detail', recipe_id=recipe_id))  
        except psycopg2.Error as e:
            print(f"Error creating recipe: {e}")
            conn.rollback()
            print(f"❌ Database error: {e}", file=sys.stderr)
            flash('Error creating recipe', 'error')
        finally:
            if 'cur' in locals() and cur is not None:
                cur.close()
            close_db_connection(conn)
    
    return render_template('create_recipe.html')

@app.route('/recipe/<int:recipe_id>')
def recipe_detail(recipe_id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'error')
        return redirect(url_for('home'))
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('''SELECT r.*, u.email 
                       FROM recipes r
                       LEFT JOIN users u ON r.author_id = u.id 
                       WHERE r.id = %s''', (recipe_id,))
        recipe = cur.fetchone()
        
        if not recipe:
            flash('Recipe not found', 'error')
            return redirect(url_for('home'))
        
        return render_template('recipe_detail.html', recipe=recipe)
    except psycopg2.Error as e:
        print(f"Error fetching recipe: {e}")
        flash('Error loading recipe', 'error')
        return redirect(url_for('home'))
    finally:
        cur.close()
        close_db_connection(conn)

@app.route('/edit_recipe/<int:recipe_id>', methods=['GET', 'POST'])
@login_required
def edit_recipe(recipe_id):
    conn = get_db_connection()
    if conn is None:
        flash('Database connection error', 'error')
        return redirect(url_for('home'))
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM recipes WHERE id = %s AND author_id = %s', 
                    (recipe_id, session['user_id']))
        recipe = cur.fetchone()
        
        if recipe is None:
            flash('Recipe not found or you do not have permission to edit it', 'error')
            return redirect(url_for('home'))
          
        if request.method == 'POST':
            title = request.form['title']
            description = request.form['description']
            ingredients = request.form['ingredients']
            steps = request.form['steps']
            image_url = recipe['image_url']  
            
            if 'image' in request.files:
                file = request.files['image']
                if file.filename != '':
                    print(f"📤 Uploading updated image to S3: {file.filename}")
                    new_image_url = process_and_upload_user_image(file)
                    if new_image_url:
                        image_url = new_image_url
                        print(f"✅ Updated image uploaded to S3: {image_url}")
                    else:
                        flash('Invalid image file. Please upload a valid image.', 'error')
                        return render_template('edit_recipe.html', recipe=recipe)
                       
            cur.execute('''UPDATE recipes 
                           SET title = %s, description = %s, ingredients = %s, steps = %s, image_url = %s
                           WHERE id = %s''',
                        (title, description, ingredients, steps, image_url, recipe_id))
            conn.commit()
            flash('Recipe updated successfully!', 'success')
            return redirect(url_for('recipe_detail', recipe_id=recipe_id))
        
        return render_template('edit_recipe.html', recipe=recipe)
    except psycopg2.Error as e:
        print(f"Error editing recipe: {e}")
        conn.rollback()
        flash('Error updating recipe', 'error')
        return redirect(url_for('home'))
    finally:
        if 'cur' in locals() and cur is not None:
            cur.close()
        close_db_connection(conn)
        
# Error Handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# Flask CLI Commands
@app.cli.command()
def init_database():
    """Initialize the database."""
    if init_db():
        print("✅ Database initialized!")
    else:
        print("❌ Database initialization failed!")

@app.cli.command()
def test_database():
    """Test database connection."""
    if test_db_connection():
        print("✅ Database connection test passed!")
    else:
        print("❌ Database connection test failed!")

def test_neon_connection():
    """Test connection to Neon PostgreSQL"""
    print("Testing Neon PostgreSQL connection...")
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("❌ DATABASE_URL not set in environment variables")
        print("Add this to your .env file:")
        print("DATABASE_URL=postgresql://username:password@ep-name-12345.region.aws.neon.tech/dbname?sslmode=require")
        return False
    
    print(f"Database URL: {DATABASE_URL[:50]}...")
    
    try:
        # Parse URL to show connection details
        url = urlparse(DATABASE_URL)
        print(f"Host: {url.hostname}")
        print(f"Database: {url.path[1:]}")
        print(f"User: {url.username}")
        print(f"Port: {url.port or 5432}")
        
        # Test connection
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Test basic query
        cur.execute('SELECT version();')
        version = cur.fetchone()
        print(f"✅ Connected to Neon PostgreSQL!")
        print(f"Version: {version[0][:80]}...")
        
        # Check connection info
        cur.execute('SELECT current_database(), current_user, inet_server_addr(), inet_server_port();')
        info = cur.fetchone()
        print(f"Database: {info[0]}")
        print(f"User: {info[1]}")
        print(f"Server: {info[2]}:{info[3]}")
        
        cur.close()
        conn.close()
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def init_neon_database():
    """Initialize tables in Neon database"""
    print("\nInitializing Neon database tables...")
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("❌ DATABASE_URL not set")
        return False
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Create users table
        print("Creating users table...")
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        # Create recipes table
        print("Creating recipes table...")
        cur.execute('''CREATE TABLE IF NOT EXISTS recipes (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(255) NOT NULL,
                        description TEXT,
                        ingredients TEXT NOT NULL,
                        steps TEXT NOT NULL,
                        image_url VARCHAR(500),
                        author_id INTEGER REFERENCES users(id),
                        spoonacular_id INTEGER,
                        source VARCHAR(50) DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        conn.commit()
        
        # Verify tables exist
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
        tables = cur.fetchall()
        print(f"✅ Tables created: {[table[0] for table in tables]}")
        
        # Check table structure
        cur.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'recipes' 
            ORDER BY ordinal_position;
        """)
        columns = cur.fetchall()
        print("\nRecipes table structure:")
        for col in columns:
            print(f"  {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
        
        cur.close()
        conn.close()
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Error creating tables: {e}")
        return False



@app.cli.command()        
def check_environment():
    """Check environment variables."""
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_S3_BUCKET']
    missing_vars = []       
    
    for var in required_vars: 
        if not os.environ.get(var):
            missing_vars.append(var)
        
        if missing_vars: 
            print("❌ Missing required environment variables:")
            for var in missing_vars:
                print(f"  -{var}")
            print("\nPlease add these to your .env file:")
            print("AWS_ACCESS_KEY_ID=your_access_key_here")
            print("AWS_SECRET_ACCESS_KEY=your_secret_key_here")
            print("AWS_S3_BUCKET=your-unique-bucket-name")
            print("AWS_S3_REGION=us-east-1  # optional, defaults to us-east-1")
            return False
        
        return True
    
def setup_s3_bucket():
    """Set up S3 bucket with proper permissions for recipe app"""
    
    if not check_environment():
        return False
    
    # Get environment variables
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
    AWS_S3_REGION = os.environ.get('AWS_S3_REGION', 'us-east-1')
    
    print(f"🚀 Setting up S3 bucket: {AWS_S3_BUCKET}")
    print(f"📍 Region: {AWS_S3_REGION}")
    print("-" * 50)
    
    # Initialize S3 client
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_S3_REGION
        )
        print("✅ Connected to AWS S3")
    except Exception as e:
        print(f"❌ Failed to connect to AWS: {e}")
        print("Please check your AWS credentials and try again.")
        return False
    
    # Check if bucket exists, create if it doesn't
    try:
        s3_client.head_bucket(Bucket=AWS_S3_BUCKET)
        print(f"✅ Bucket '{AWS_S3_BUCKET}' exists")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"📦 Creating bucket '{AWS_S3_BUCKET}'...")
            try:
                if AWS_S3_REGION != 'us-east-1':
                    s3_client.create_bucket(
                        Bucket=AWS_S3_BUCKET,
                        CreateBucketConfiguration={'LocationConstraint': AWS_S3_REGION}
                    )
                else:
                    s3_client.create_bucket(Bucket=AWS_S3_BUCKET)
                print(f"✅ Created bucket '{AWS_S3_BUCKET}'")
            except ClientError as create_error:
                print(f"❌ Failed to create bucket: {create_error}")
                return False
        elif error_code == '403':
            print(f"❌ Access denied to bucket '{AWS_S3_BUCKET}'")
            print("Either the bucket name is taken or you don't have permission.")
            return False
        else:
            print(f"❌ Error accessing bucket: {e}")
            return False
    
    # Set up CORS configuration
    print("🔧 Setting up CORS configuration...")
    cors_configuration = {
        'CORSRules': [
            {
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedOrigins': ['*'],
                'MaxAgeSeconds': 3000
            }
        ]
    }
    
    try:
        s3_client.put_bucket_cors(
            Bucket=AWS_S3_BUCKET,
            CORSConfiguration=cors_configuration
        )
        print("✅ CORS configuration applied")
    except ClientError as e:
        print(f"⚠️ Could not set CORS: {e}")
    
    # Set up bucket policy for public read access to images
    print("🔧 Setting up public read policy for recipe images...")
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{AWS_S3_BUCKET}/recipes/*"
            }
        ]
    }
    
    try:
        s3_client.put_bucket_policy(
            Bucket=AWS_S3_BUCKET,
            Policy=json.dumps(bucket_policy)
        )
        print("✅ Public read policy applied to recipes folder")
    except ClientError as e:
        print(f"⚠️ Could not set bucket policy: {e}")
        print("   This might be due to account restrictions.")
        print("   You can set this manually in AWS Console if needed.")
    
    # Test upload and download
    print("🧪 Testing upload and download...")
    test_key = f"recipes/test-{uuid.uuid4().hex[:8]}.txt"
    test_content = b"Test content for recipe app setup"
    
    try:
        # Test upload
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=test_key,
            Body=test_content,
            ContentType='text/plain'
        )
        print("✅ Test upload successful")
        
        # Test download
        response = s3_client.get_object(Bucket=AWS_S3_BUCKET, Key=test_key)
        downloaded_content = response['Body'].read()
        
        if downloaded_content == test_content:
            print("✅ Test download successful")
        else:
            print("⚠️ Test download content mismatch")
        
        # Test public URL
        public_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{test_key}"
        print(f"🔗 Test file public URL: {public_url}")
        
        # Clean up test file
        s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=test_key)
        print("✅ Test file cleaned up")
        
    except ClientError as e:
        print(f"❌ Test upload/download failed: {e}")
        return False
    
    print("-" * 50)
    print("🎉 S3 setup completed successfully!")
    print(f"📦 Bucket: {AWS_S3_BUCKET}")
    print(f"📍 Region: {AWS_S3_REGION}")
    print(f"🔗 Recipe images will be stored at: https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/recipes/")
    print("\nYour Flask app is now ready to upload and serve images from S3!")
    
    return True

def main():
    """Main function"""
    print("Neon PostgreSQL Setup for Recipe App")
    print("=" * 50)
    
    # Test connection
    if not test_neon_connection():
        print("\n❌ Setup failed. Please check your DATABASE_URL and try again.")
        return
    
    # Initialize database
    if not init_neon_database():
        print("\n❌ Database initialization failed.")
        return
   
 
    print("\n" + "=" * 50)
    print("✅ Neon PostgreSQL setup complete!")
    print("\nNext steps:")
    print("1. Run your Flask app: python app.py")
    print("2. Create an account and test recipe creation")
    print("3. Check that images save and display properly")
    print("\nYour app is now using Neon PostgreSQL in the cloud!")

@app.cli.command()
def setup_neon():
    """Setup Neon.tech database."""
    if 'DATABASE_URL' not in os.environ:
        print("❌ DATABASE_URL not set. Please add your Neon.tech connection string to .env")
        return
    
    print("🔄 Testing Neon.tech connection...")
    if test_db_connection():
        print("✅ Neon.tech connection successful!")
        if init_db():
            print("✅ Neon.tech database initialized!")
        else:
            print("❌ Neon.tech database initialization failed!")
    else:
        print("❌ Neon.tech connection failed!")

if __name__ == '__main__':
    if init_db():
        print("🚀 Starting Recipe App...")
        print("=" * 50)
    
    # Test database connection first
    if not test_db_connection():
        print("❌ Cannot start app without database connection!")
        exit(1)
    
    # Initialize database
    if not init_db():
        print("❌ Database initialization failed!")
        exit(1)
        
     # Configure S3 if available
    if s3_client:
        configure_s3_bucket()     
    
    print("🌐 Server starting...")
    app.run(
        debug=True,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 8080)),
        use_reloader=False
    )

