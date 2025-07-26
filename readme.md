# 🍳 ME-COOKBOOK - Recipe Sharing Web Application

A modern, responsive web application for discovering, creating, and sharing recipes. Built with Flask and PostgreSQL, enchanced
with the Spoonacular API for discovering new recipes. 

## ✨ Features

### 🔐 User Authentication
- **User Registration & Login**: Secure account creation and authentication
- **Session Management**: Persistent login sessions with user-specific content
- **Password Security**: Hashed passwords using Werkzeug security

### 📝 Recipe Management
- **Create Recipes**: Add your own recipes with ingredients, steps, and images
- **Edit Recipes**: Update your recipes anytime
- **Recipe Images**: Upload and display recipe photos
- **Recipe Categories**: Organize recipes by meal type and dietary preferences

### 🔍 Smart Search
- **Local Search**: Search through your saved recipes
- **API Integration**: Discover new recipes using Spoonacular API
- **Category Browsing**: Browse recipes by breakfast, lunch, dinner, dessert, etc.
- **Dual Results**: See both your saved recipes and new discoveries

### 🌐 External Recipe Discovery
- **Spoonacular Integration**: Access thousands of recipes from Spoonacular
- **Detailed Recipe Info**: Nutrition facts, cooking time, servings
- **Save External Recipes**: Save discovered recipes to your collection
- **Recipe Source Tracking**: Know which recipes are yours vs. external

### 📱 Modern UI/UX
- **Responsive Design**: Works perfectly on desktop, tablet, and mobile
- **Modern Interface**: Clean, card-based layout with smooth animations
- **User-Friendly Navigation**: Intuitive menu and search functionality
- **Welcome Personalization**: Personalized greetings for logged-in users

## 🛠️ Tech Stack

### Backend
- **Framework**: Flask 3.0.3
- **Database**: PostgreSQL with psycopg2
- **Authentication**: Werkzeug Security (password hashing)
- **File Handling**: Werkzeug Utils (secure filename handling)

### Frontend
- **Template Engine**: Jinja2
- **Styling**: Custom CSS with modern design principles
- **Responsive**: Mobile-first responsive design
- **Icons**: Unicode emojis and custom styling

### External APIs
- **Spoonacular API**: Recipe discovery and detailed recipe information
- **HTTP Requests**: Python Requests library for API integration

### Prerequisites
- Python 3.9+ 
- PostgreSQL 12+
- Git

### Local Development Setup

1. **Clone the repository**
   ``bash
   git clone https://github.com/Fern-smith/capstone_project_one.git
   cd me-cookbook
   ```
2. **Set up Python environment**
   ``bash
#Using conda (recommended)
conda create -n recipe-app python=3.9
conda activate recipe-app

#Using venv (alternative)
python -m venv recipe-app
source recipe-app/bin/activate
```

3. **Install dependencies**
```bash

#Using Conda 
conda install flask requests psycopg2 -c conda-forge 

#Using pip
pip install -r requirements.txt 

4. **Set up PostgreSQL database**
```bash
#Start PostgreSQL
brew services start postgresql #macOS
sudo systemctl start postgresql #Linux

#Create database and user
psql postgres
```

In PostgreSQL shell:
   ```sql
   CREATE DATABASE recipes_db;
   CREATE USER recipe_user WITH PASSWORD 'your_secure_password';
   GRANT ALL PRIVILEGES ON DATABASE recipes_db TO recipe_user;
   \c recipes_db;
   GRANT ALL ON SCHEMA public TO recipe_user;
   \q
   ```

5. **Configure the application**
   
   Update `DATABASE_CONFIG` in `app.py`:
   ```python
   DATABASE_CONFIG = {
       'host': 'localhost',
       'database': 'recipes_db',
       'user': 'recipe_user',
       'password': 'me-cookbook-app',
       'port': 5432
   }
   ```  

6. **Get Spoonacular API Key** (Optional but recommended)
   - Sign up at [Spoonacular API](https://spoonacular.com/food-api)
   - Replace `SPOONACULAR_API_KEY` in `app.py` with your key

7. **Run the application**
   ```bash
   python app.py
   ```  

8. **Access the application**
   - Open your browser and go to `http://localhost:8080`
   - Sign up for a new account
   - Start creating and discovering recipes!

## 📁 Project Structure

```
me-cookbook/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Procfile              # Heroku deployment configuration
├── runtime.txt           # Python version specification
├── README.md             # Project documentation
├── static/
│   ├── css/
│   │   └── styles.css    # Application styling
│   └── uploads/          # User-uploaded recipe images
├── templates/
│   ├── base.html         # Base template with navigation
│   ├── home.html         # Homepage with featured recipes
│   ├── login.html        # User login page
│   ├── signup.html       # User registration page
│   ├── search.html       # Recipe search and results
│   ├── create_recipe.html # Recipe creation form
│   ├── recipe_detail.html # Individual recipe display
│   ├── edit_recipe.html  # Recipe editing form
│   └── api_recipe_detail.html # External recipe display
└── .gitignore            # Git ignore file
```   


