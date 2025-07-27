from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
from psycopg2 import sql
import os
import requests
from datetime import datetime
import json
from functools import wraps
from urllib.parse import urlparse
 
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Database configuration
if 'DATABASE_URL' in os.environ:
    # Production (Render, Heroku, etc.)
    DATABASE_URL = os.environ['DATABASE_URL']
    # Parse the URL
    url = urlparse(DATABASE_URL)
    DATABASE_CONFIG = {
        'host': url.hostname,
        'database': url.path[1:],
        'user': url.username,
        'password': url.password,
        'port': url.port or 5432,
        'sslmode': 'require'  # Required for most cloud providers
    }
    print(f"🐘 Using production database: {url.hostname}")
else:
    # Local development - PostgreSQL
    DATABASE_CONFIG = {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'database': os.environ.get('DB_NAME', 'recipes_db'),
        'user': os.environ.get('DB_USER', 'recipe_user'),
        'password': os.environ.get('DB_PASSWORD', 'me-cookbook-app'),
        'port': int(os.environ.get('DB_PORT', 5432))
    }
    print("🐘 Using local development database")

# Spoonacular API configuration
SPOONACULAR_API_KEY = os.environ.get('SPOONACULAR_API_KEY')
SPOONACULAR_BASE_URL = 'https://api.spoonacular.com/recipes'

if not SPOONACULAR_API_KEY:
    print("⚠️  Warning: SPOONACULAR_API_KEY not set. API features will be disabled.")

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Helper decorator for login requirement
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
        return None

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
            print(f"📊 PostgreSQL version: {version[0]}")
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Error testing connection: {e}")
            conn.close()
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
                        image_filename VARCHAR(255),
                        author_id INTEGER REFERENCES users(id),
                        spoonacular_id INTEGER,
                        source VARCHAR(50) DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        conn.commit()
        print("✅ Database tables created successfully!")
        
        # Check if tables exist
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = cur.fetchall()
        print(f"📋 Tables in database: {[table[0] for table in tables]}")
        
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Error creating tables: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

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
    """Format ingredients list for database storage"""
    if not ingredients_list:
        return ""
    
    formatted = []
    for ingredient in ingredients_list:
        if isinstance(ingredient, dict):
            amount = ingredient.get('amount', '')
            unit = ingredient.get('unit', '')
            name = ingredient.get('name', ingredient.get('original', ''))
            formatted.append(f"• {amount} {unit} {name}".strip())
        else:
            formatted.append(f"• {ingredient}")
    
    return "\n".join(formatted)

def format_instructions(instructions_list):
    """Format instructions list for database storage"""
    if not instructions_list:
        return ""
    
    formatted = []
    for i, instruction in enumerate(instructions_list, 1):
        if isinstance(instruction, dict):
            step = instruction.get('step', instruction.get('text', ''))
        else:
            step = instruction
        formatted.append(f"{i}. {step}")
    
    return "\n".join(formatted)

# Routes
@app.route('/test')
def test():
    return '''
    <h1>Flask + PostgreSQL Test 🐘</h1>
    <p>Flask is running successfully!</p>
    <p><a href="/">Go to Home</a></p>
    '''

@app.route('/')
def home():
    print("📍 Home route accessed")
    
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'error')
        return render_template('home.html', featured_recipes=[])
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('''SELECT r.*, u.email 
                       FROM recipes r
                       LEFT JOIN users u ON r.author_id = u.id 
                       ORDER BY r.created_at DESC LIMIT 4''')
        featured_recipes = cur.fetchall()
        print(f"✅ Found {len(featured_recipes)} featured recipes")
        
    except psycopg2.Error as e:
        print(f"❌ Error fetching recipes: {e}")
        featured_recipes = []
    finally:
        cur.close()
        conn.close()
    
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
                conn.close()
        
        # Search using Spoonacular API
        api_results = search_recipes_api(query)
        if api_results:
            search_results['api'] = api_results['results']
    
    return render_template('search.html', query=query, search_results=search_results)

@app.route('/api_recipe/<int:spoonacular_id>')
def api_recipe_detail(spoonacular_id):
    """Display recipe details from Spoonacular API"""
    recipe_data = get_recipe_details_api(spoonacular_id)
    
    if not recipe_data:
        flash('Recipe not found', 'error')
        return redirect(url_for('home'))
    
    return render_template('api_recipe_detail.html', recipe=recipe_data)

@app.route('/save_api_recipe/<int:spoonacular_id>', methods=['POST'])
@login_required
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
        description = recipe_data.get('summary', '')[:500] if recipe_data.get('summary') else ''
        ingredients = format_ingredients(recipe_data.get('extendedIngredients', []))
        
        # Get instructions
        instructions = recipe_data.get('analyzedInstructions', [])
        steps = ""
        if instructions and len(instructions) > 0:
            steps = format_instructions(instructions[0].get('steps', []))
        
        # Save to database
        cur.execute('''INSERT INTO recipes (title, description, ingredients, steps, author_id, spoonacular_id, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                    (title, description, ingredients, steps, session['user_id'], spoonacular_id, 'spoonacular'))
        
        recipe_id = cur.fetchone()[0]
        conn.commit()
        flash('Recipe saved successfully!', 'success')
        return redirect(url_for('recipe_detail', recipe_id=recipe_id))
        
    except psycopg2.Error as e:
        print(f"Error saving recipe: {e}")
        conn.rollback()
        flash('Error saving recipe', 'error')
        return redirect(url_for('home'))
    finally:
        cur.close()
        conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'error')
            return render_template('login.html')
        
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cur.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['user_email'] = user['email']

                #Personalized welcome message
                username = user['email'].split('@')[0].title()
                flash(f'Welcome back, {username}! 🎉', 'success')
                return redirect(url_for('home'))
            else:
                flash('Invalid email or password', 'error')
                
        except psycopg2.Error as e:
            print(f"Error during login: {e}")
            flash('Login error occurred', 'error')
        finally:
            cur.close()
            conn.close()
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'error')
            return render_template('signup.html')
        
        try:
            cur = conn.cursor()
            
            # Check if user already exists
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            if cur.fetchone():
                flash('Email already registered', 'error')
                return render_template('signup.html')
            
            # Create new user
            password_hash = generate_password_hash(password)
            cur.execute('INSERT INTO users (email, password_hash) VALUES (%s, %s)',
                        (email, password_hash))
            conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
            
        except psycopg2.Error as e:
            print(f"Error during signup: {e}")
            conn.rollback()
            flash('Registration error occurred', 'error')
        finally:
            cur.close()
            conn.close()
    
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
        
        # Handle file upload
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'error')
            return render_template('create_recipe.html')
        
        try:
            cur = conn.cursor()
            cur.execute('''INSERT INTO recipes (title, description, ingredients, steps, image_filename, author_id, source)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                        (title, description, ingredients, steps, image_filename, session['user_id'], 'user'))
            conn.commit()
            flash('Recipe created successfully!', 'success')
            return redirect(url_for('home'))
        except psycopg2.Error as e:
            print(f"Error creating recipe: {e}")
            conn.rollback()
            flash('Error creating recipe', 'error')
        finally:
            cur.close()
            conn.close()
    
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
        conn.close()

@app.route('/edit_recipe/<int:recipe_id>', methods=['GET', 'POST'])
@login_required
def edit_recipe(recipe_id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'error')
        return redirect(url_for('home'))
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM recipes WHERE id = %s AND author_id = %s', 
                    (recipe_id, session['user_id']))
        recipe = cur.fetchone()
        
        if not recipe:
            flash('Recipe not found or you do not have permission to edit it', 'error')
            return redirect(url_for('home'))
        
        if request.method == 'POST':
            title = request.form['title']
            description = request.form['description']
            ingredients = request.form['ingredients']
            steps = request.form['steps']
            
            # Handle file upload
            image_filename = recipe['image_filename']
            if 'image' in request.files:
                file = request.files['image']
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_filename = filename
            
            cur.execute('''UPDATE recipes 
                           SET title = %s, description = %s, ingredients = %s, steps = %s, image_filename = %s
                           WHERE id = %s''',
                        (title, description, ingredients, steps, image_filename, recipe_id))
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
        cur.close()
        conn.close()

if __name__ == '__main__':
    print("🚀 Starting Flask Recipe App with PostgreSQL")
    print("=" * 50)
    
    # Test database connection first
    if not test_db_connection():
        print("\n❌ Cannot start app without database connection!")
        print("🔧 Please check your PostgreSQL setup and DATABASE_CONFIG")
        exit(1)
    
    # Initialize database
    if not init_db():
        print("\n❌ Database initialization failed!")
        exit(1)
    
    print("\n🌐 Server starting...")
    print("📱 Access your app at: http://127.0.0.1:8080")
    print("🧪 Test route: http://127.0.0.1:8080/test")
    print("=" * 50)
    
    try:
        app.run(
            debug=True,
            host='0.0.0.0',  # Changed to 0.0.0.0 for deployment
            port=int(os.environ.get('PORT', 8080)),
            use_reloader=False
        )
    except Exception as e:
        print(f"❌ Error starting Flask: {e}")
        print("💡 Trying alternative port...")
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8081)))